"""Commander deck builder - Streamlit page (Slice 7).

Run:
    /home/t9/venv/bin/streamlit run streamlit_app.py

Pick a commander (and a second one for partners / Backgrounds / Doctors) and
a budget, optionally use your scanned collection, then
build with the no-LLM baseline or with Claude. Every deck is checked by the
full validator before it is shown. Card images come from Scryfall.
"""

import streamlit as st

import deck_service
import edhrec_client
import llm_deck
from collection import Collection
from flip_card import flip_card
from scan_binder import ScanError, make_client

st.set_page_config(page_title="Commander deck builder", page_icon=":material/style:", layout="wide")

GRID_COLUMNS = 6
MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
ROLE_TITLES = {"land": "Lands", "ramp": "Ramp", "draw": "Card draw", "removal": "Removal",
               "wipe": "Board wipes", "synergy": "Synergy"}

st.session_state.setdefault("result", None)


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


@st.cache_data(ttl="1d", max_entries=50)
def load_partners(commander):
    db = deck_service.open_db()
    try:
        return deck_service.partner_names(commander, db)
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
def load_prep(commander, partner, owned, max_card_price):
    db = deck_service.open_db()
    try:
        return deck_service.prepare(commander, db, frozenset(owned), partner, max_card_price)
    finally:
        db.close()


@st.cache_data(ttl="1d", max_entries=50, show_spinner="Asking Commander Spellbook...")
def load_combos(commanders, main):
    import combos
    db = deck_service.open_db()
    try:
        return combos.find_combos(list(commanders), list(main), db)
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
        help="Type to search. Ordered by how many decks each commander leads (EDHREC, past 2 years).",
    )
    partners = load_partners(commander)
    partner = None
    if partners:
        partner = st.selectbox(
            "Second commander", partners, index=None, key=f"partner-{commander}",
            placeholder="None (build with one commander)",
            help="Cards that can share the command zone with this one: partners, Backgrounds or Doctors.",
        )
    budget = st.number_input("Budget (USD, commander included)", min_value=0, max_value=5000, value=100,
                             step=10, key="budget")
    max_card = st.number_input("Max price per card (USD, optional)", min_value=0.0, max_value=1000.0, value=None,
                               step=1.0, key="max_card_price", placeholder="No limit",
                               help="Cards you'd have to buy above this price are left out. Owned cards and the "
                                    "commander don't count.")
    use_owned = st.toggle("Use my collection (owned cards cost $0)", key="use_owned",
                          disabled=not collection["all"],
                          help=None if collection["all"] else "Scan binder pages first (scan_binder.py --binder).")
    binder = st.selectbox("Binder", ["All binders", *collection["binders"]], key="binder",
                          disabled=not use_owned)
    builder = st.segmented_control("Builder", ["Code only", "Claude"], default="Code only", key="builder",
                                   required=True)
    model = st.selectbox("Claude model", MODELS, key="model", disabled=builder != "Claude",
                         help="Opus won the eval (see README). Roughly $0.20 / $0.09 / $0.01 per deck.")
    build = st.button("Build deck", type="primary", icon=":material/construction:", width="stretch", key="build")
    st.caption("Card images and prices from Scryfall; deck data from EDHREC. Unofficial fan project, "
               "not affiliated with Wizards of the Coast.")

st.title("Commander deck builder")

# ---------------------------------------------------------------------------
# Build (only when the button is pressed)
# ---------------------------------------------------------------------------

if build:
    owned = owned_names(binder) if use_owned else ()
    try:
        prep = load_prep(commander, partner, owned, max_card)
        db = deck_service.open_db()
        try:
            if builder == "Claude":
                with st.spinner(f"{model} is picking cards (about 20-60 seconds)..."):
                    result = deck_service.build_claude(prep, budget, db, claude_client(), frozenset(owned), model)
            else:
                result = deck_service.build_code(prep, budget, db, frozenset(owned), owned_mode=use_owned)
        finally:
            db.close()
    except (LookupError, ScanError, OSError, edhrec_client.EdhrecError) as exc:
        st.error(f"Couldn't build the deck: {exc}", icon=":material/error:")
        result = None
    if result is not None:
        st.session_state.result = result | {"commander": prep["commander"], "budget": budget}

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
                       file_name=f"{edhrec_client.slugify(cmd['name'])}_{result['budget']}.txt",
                       icon=":material/download:", help="Paste into Moxfield or Archidekt.")
    basics = ", ".join(f"{n} {b}" for b, n in sorted(deck["basics"].items()))
    st.caption(f"Basic lands (free): {basics or 'none'}")

cards_tab, list_tab, combos_tab = st.tabs(["Cards", "List", "Combos"])

with combos_tab:
    combo_key = (tuple(c["name"] for c in cmd.get("members") or [cmd]), tuple(sorted(c["name"] for c in deck["cards"])))
    if st.session_state.get("combos_for") != combo_key:
        st.caption("Combos already in this deck, and combos one card away, from Commander Spellbook.")
        if st.button("Find combos", icon=":material/join_inner:", key="find_combos"):
            try:
                st.session_state.combos = load_combos(*combo_key)
                st.session_state.combos_for = combo_key
                st.rerun()
            except Exception as exc:  # network / API shape problems
                st.error(f"Couldn't reach Commander Spellbook: {exc}", icon=":material/error:")
    else:
        found = st.session_state.combos
        st.markdown(f"#### In this deck ({len(found['in_deck'])})")
        if not found["in_deck"]:
            st.caption("None found.")
        for c in found["in_deck"]:
            with st.expander(" + ".join(c["cards"])):
                st.markdown(f"**Produces:** {', '.join(c['produces']) or 'see link'}")
                if c["prerequisites"]:
                    st.markdown(f"**Needs:** {c['prerequisites']}")
                st.markdown(c["description"].replace("\n", "  \n"))
                st.link_button("Open on Commander Spellbook", c["url"], icon=":material/open_in_new:")
        st.markdown(f"#### One card away ({len(found['one_card_away'])})")
        if found["one_card_away"]:
            st.dataframe(
                [{"Add": c["missing"][0], "Price": f"${c['missing_usd']:.2f}" if c["missing_usd"] is not None else "n/a",
                  "Combo": " + ".join(c["cards"]), "Produces": ", ".join(c["produces"][:3]), "Link": c["url"]}
                 for c in found["one_card_away"]],
                column_config={"Link": st.column_config.LinkColumn(display_text="Open")}, hide_index=True)
        else:
            st.caption("None.")
        st.caption("Combo data: Commander Spellbook. The builder doesn't add combos on its own.")

with list_tab:
    st.dataframe(
        [{"Card": c["name"], "Role": ROLE_TITLES[c["role"]], "Price": deck_service.price_label(c),
          "EDHREC inclusion": c["inclusion"] if c["listed"] else None, "Why": c.get("reason", "")}
         for _, group in deck_service.grouped(deck) for c in group],
        column_config={"EDHREC inclusion": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)},
        hide_index=True,
    )


def card_image(card, key, width="stretch"):
    """A card picture; two-faced cards turn over in 3D when clicked (in the browser, no rerun)."""
    if card.get("image_url") and card.get("image_url_back"):
        flip_card(card["name"], card["image_url"], card["image_url_back"], key=key)
    elif card.get("image_url"):
        st.image(card["image_url"], width=width, alt=card["name"])
    else:
        st.write(card["name"])


def card_grid(deck):
    """Image grid by role."""
    members = cmd.get("members") or [cmd]
    with st.container(horizontal=True):
        for member in members:
            with st.container(width=180):
                card_image(member, key=f"flip-cmd-{member['name']}")
                st.caption(f"Commander: {member['name']}")
    for role, cards in deck_service.grouped(deck):
        st.markdown(f"#### {ROLE_TITLES[role]} ({len(cards)})")
        for start in range(0, len(cards), GRID_COLUMNS):
            cols = st.columns(GRID_COLUMNS)
            for col, card in zip(cols, cards[start:start + GRID_COLUMNS]):
                with col:
                    card_image(card, key=f"flip-{card['name']}")
                    st.caption(f"{card['name']} - {deck_service.price_label(card)}")
                    if card.get("reason"):
                        st.caption(f":material/smart_toy: {card['reason']}")


with cards_tab:
    card_grid(deck)
