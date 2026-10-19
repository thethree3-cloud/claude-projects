"""Commander deck builder - Streamlit page (Slice 7).

Run:
    /home/t9/venv/bin/streamlit run streamlit_app.py

Pick a commander and a budget, optionally use your scanned collection, then
build with the no-LLM baseline or with Claude. Every deck is checked by the
full validator before it is shown. Card images come from Scryfall.
"""

import streamlit as st

import deck_service
import llm_deck
from collection import Collection
from scan_binder import ScanError, make_client

st.set_page_config(page_title="Commander deck builder", page_icon=":material/style:", layout="wide")

GRID_COLUMNS = 6
MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
ROLE_TITLES = {"land": "Lands", "ramp": "Ramp", "draw": "Card draw", "removal": "Removal",
               "wipe": "Board wipes", "synergy": "Synergy"}

st.session_state.setdefault("result", None)
st.session_state.setdefault("flipped", set())


# ---------------------------------------------------------------------------
# Cached data
# ---------------------------------------------------------------------------


@st.cache_data(ttl="1d", show_spinner="Loading card data...")
def load_commanders():
    db = deck_service.open_db()
    try:
        return deck_service.commander_names(db)
    finally:
        db.close()


@st.cache_data(ttl="1m")
def load_collection():
    col = Collection()
    try:
        return {"binders": [b["binder"] for b in col.binders()], "all": sorted(col.names())}
    finally:
        col.close()


@st.cache_data(ttl="1h", max_entries=20, show_spinner="Fetching EDHREC data...")
def load_prep(commander, owned):
    db = deck_service.open_db()
    try:
        return deck_service.prepare(commander, db, frozenset(owned))
    finally:
        db.close()


@st.cache_resource
def claude_client():
    return make_client().with_options(timeout=600, max_retries=4)


def owned_names(binder):
    if binder == "All binders":
        return tuple(load_collection()["all"])
    col = Collection()
    try:
        return tuple(sorted(col.names(binder=binder)))
    finally:
        col.close()


def toggle_flip(name):
    flipped = st.session_state.flipped
    flipped.symmetric_difference_update({name})


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------

commanders = load_commanders()
collection = load_collection()

with st.sidebar:
    st.header("Build a deck")
    commander = st.selectbox(
        "Commander", commanders, index=commanders.index("Kestia, the Cultivator")
        if "Kestia, the Cultivator" in commanders else 0, key="commander",
        help="Type to search. Ordered by how often the card is played.",
    )
    budget = st.number_input("Budget (USD, commander included)", min_value=0, max_value=5000, value=100,
                             step=10, key="budget")
    use_owned = st.toggle("Use my collection (owned cards cost $0)", key="use_owned",
                          disabled=not collection["all"],
                          help=None if collection["all"] else "Scan binder pages first (scan_binder.py --binder).")
    binder = st.selectbox("Binder", ["All binders", *collection["binders"]], key="binder",
                          disabled=not use_owned)
    builder = st.segmented_control("Builder", ["Code only", "Claude"], default="Code only", key="builder",
                                   required=True)
    model = st.selectbox("Claude model", MODELS, key="model", disabled=builder != "Claude",
                         help="Opus won the eval (see README). Roughly $0.20 / $0.09 / $0.01 per deck.")
    build = st.button("Build deck", type="primary", icon=":material/construction:", width="stretch")
    st.caption("Card images and prices from Scryfall; deck data from EDHREC. Unofficial fan project, "
               "not affiliated with Wizards of the Coast.")

st.title("Commander deck builder")

# ---------------------------------------------------------------------------
# Build (only when the button is pressed)
# ---------------------------------------------------------------------------

if build:
    owned = owned_names(binder) if use_owned else ()
    try:
        prep = load_prep(commander, owned)
        db = deck_service.open_db()
        try:
            if builder == "Claude":
                with st.spinner(f"{model} is picking cards (about 20-60 seconds)..."):
                    result = deck_service.build_claude(prep, budget, db, claude_client(), frozenset(owned), model)
            else:
                result = deck_service.build_code(prep, budget, db, frozenset(owned), owned_mode=use_owned)
        finally:
            db.close()
    except (LookupError, ScanError, OSError) as exc:
        st.error(f"Couldn't build the deck: {exc}", icon=":material/error:")
        result = None
    if result is not None:
        st.session_state.result = result | {"commander": prep["commander"], "budget": budget}
        st.session_state.flipped = set()

result = st.session_state.result

if result is None:
    st.info("Pick a commander and a budget in the sidebar, then press **Build deck**.", icon=":material/info:")
    st.stop()

# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

cmd = result["commander"]
if result["deck"] is None:
    st.error(f"Claude didn't produce a valid deck in {len(result['attempts'])} attempts, so nothing is shown.",
             icon=":material/block:")
    for e in result["attempts"][-1]["errors"]:
        st.write(f"- {e}")
    st.stop()

deck, check = result["deck"], result["check"]
owned_cards = [c for c in deck["cards"] if c["owned"]]

st.subheader(f"{cmd['name']} - ${result['budget']:,} budget, {result['builder']}")
with st.container(horizontal=True):
    st.metric("Cost to buy", f"${check['stats']['cost_to_buy']:.2f}", border=True)
    st.metric("Lands", check["stats"]["lands"], border=True)
    st.metric("Avg mana value", f"{check['stats']['average_mana_value']:.2f}", border=True)
    st.metric("Owned cards used", len(owned_cards), border=True)
    st.metric("Validator", "Pass" if check["ok"] else "Fail", border=True)
    if result.get("cost_usd") is not None:
        st.metric("API cost", f"${result['cost_usd']:.2f}", border=True,
                  help=f"{len(result['attempts'])} attempt(s)")

if result.get("strategy"):
    st.markdown(f":material/lightbulb: **Strategy:** {result['strategy']}")
for w in dict.fromkeys(deck["warnings"] + check["warnings"]):  # Claude decks already carry the validator's
    st.warning(w, icon=":material/warning:")
for e in check["errors"]:
    st.error(e, icon=":material/error:")

with st.container(horizontal=True):
    st.download_button("Download import list", result["text"] + "\n",
                       file_name=f"{deck_service.edhrec_client.slugify(cmd['name'])}_{result['budget']}.txt",
                       icon=":material/download:", help="Paste into Moxfield or Archidekt.")
    basics = ", ".join(f"{n} {b}" for b, n in sorted(deck["basics"].items()))
    st.caption(f"Basic lands (free): {basics or 'none'}")

cards_tab, list_tab = st.tabs(["Cards", "List"])

with list_tab:
    st.dataframe(
        [{"Card": c["name"], "Role": ROLE_TITLES[c["role"]], "Price": deck_service.price_label(c),
          "EDHREC inclusion": c["inclusion"] if c["listed"] else None, "Why": c.get("reason", "")}
         for _, group in deck_service.grouped(deck) for c in group],
        column_config={"EDHREC inclusion": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)},
        hide_index=True,
    )


@st.fragment
def card_grid(deck):
    """Image grid by role. Flipping a two-faced card only reruns this fragment."""
    if cmd.get("image_url"):
        st.image(cmd["image_url"], caption=f"Commander: {cmd['name']}", width=180)
    for role, cards in deck_service.grouped(deck):
        st.markdown(f"#### {ROLE_TITLES[role]} ({len(cards)})")
        for start in range(0, len(cards), GRID_COLUMNS):
            cols = st.columns(GRID_COLUMNS)
            for col, card in zip(cols, cards[start:start + GRID_COLUMNS]):
                with col:
                    flipped = card["name"] in st.session_state.flipped and card.get("image_url_back")
                    url = card["image_url_back"] if flipped else card.get("image_url")
                    if url:
                        st.image(url, width="stretch")
                    else:
                        st.write(card["name"])
                    st.caption(f"{card['name']} - {deck_service.price_label(card)}")
                    if card.get("reason"):
                        st.caption(f":material/smart_toy: {card['reason']}")
                    if card.get("image_url_back"):
                        st.button("Flip", key=f"flip-{card['name']}", icon=":material/flip:",
                                  on_click=toggle_flip, args=(card["name"],), width="stretch")


with cards_tab:
    card_grid(deck)
