"""Card page: every printing of one card, with picture, set, prices and a Scryfall link.

Opened from a card name in the deck builder (``card?name=Sol Ring``). Works on
its own too, so a link opened in a new tab shows the card without a deck.
"""

import streamlit as st

import card_db
import deck_service
from flip_card import flip_card

GRID_COLUMNS = 5
FIRST_BATCH = 20
COLOR_NAMES = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green"}
SORTS = {
    "Newest": lambda p: (p["released_at"] or "",),
    "Oldest": lambda p: (p["released_at"] or "9999",),
    "Cheapest": lambda p: (min((x for x in (p["usd"], p["usd_foil"], p["usd_etched"]) if x is not None),
                               default=float("inf")),),
}


@st.cache_data(ttl="1d", max_entries=200, show_spinner=False)
def load_card(name):
    db = deck_service.open_db()
    try:
        card = db.get(name)
        if card is None:
            guess = db.find_name(name)
            return None, [], guess
        return card, db.printings(card["name"]), None
    finally:
        db.close()


@st.cache_data(ttl="1d", show_spinner=False)
def all_names():
    db = deck_service.open_db()
    try:
        return [r[0] for r in db.conn.execute("SELECT name FROM cards ORDER BY edhrec_rank IS NULL, edhrec_rank")]
    finally:
        db.close()


def money(value):
    return f"${value:,.2f}" if value is not None else None


def prices_line(p):
    parts = [f"{label} {money(v)}" for label, v in (("normal", p["usd"]), ("foil", p["usd_foil"]),
                                                       ("etched", p["usd_etched"])) if v is not None]
    return " · ".join(parts) or "no price"


# ---------------------------------------------------------------------------
# Which card
# ---------------------------------------------------------------------------

if st.session_state.get("result"):
    st.page_link("app_pages/builder.py", label="Back to your deck", icon=":material/arrow_back:")
else:
    st.page_link("app_pages/builder.py", label="Open the deck builder", icon=":material/construction:")

name = st.query_params.get("name")
if not name:
    st.title("Card versions")
    picked = st.selectbox("Card", all_names(), index=None, placeholder="Type a card name...", key="card_search")
    if picked:
        st.query_params["name"] = picked
        st.rerun()
    st.stop()

card, printings, guess = load_card(name)
if card is None:
    st.title("Card versions")
    st.error(f"No card named {name!r}." + (f" Did you mean {guess}?" if guess else ""), icon=":material/error:")
    if guess:
        st.page_link("app_pages/card.py", label=f"Open {guess}", query_params={"name": guess})
    st.stop()

# ---------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------

st.title(card["name"])
left, right = st.columns([1, 3], gap="large")
with left:
    if card["image_url"] and card["image_url_back"]:
        flip_card(card["name"], card["image_url"], card["image_url_back"], key="flip-main")
    elif card["image_url"]:
        st.image(card["image_url"], width="stretch", alt=card["name"])
with right:
    st.markdown(f"**{card['type_line']}**")
    st.markdown(card["oracle_text"].replace("\n", "  \n") or "_No rules text._")
    colors = ", ".join(COLOR_NAMES[c] for c in card["color_identity"]) or "Colorless"
    with st.container(horizontal=True):
        st.badge(f"Color identity: {colors}", color="gray")
        st.badge("Legal in Commander" if card["legal_commander"] else "Banned in Commander",
                 color="green" if card["legal_commander"] else "red")
        if card["game_changer"]:
            st.badge("Game Changer", color="orange")
        if card_db.can_be_commander(card):
            st.badge("Can be a commander", color="blue")
    if card["usd"] is not None:
        st.markdown(f"**Deck builder price:** {money(card['usd'])} "
                    f"({card['price_printing']}, the cheapest regular printing)")

# ---------------------------------------------------------------------------
# Every printing
# ---------------------------------------------------------------------------

st.subheader(f"Printings ({len(printings)})")
with st.container(horizontal=True, vertical_alignment="bottom"):
    sort = st.segmented_control("Sort", list(SORTS), default="Newest", key="printing_sort", required=True)
    hide_promos = st.toggle("Hide promos", key="hide_promos")
    only_priced = st.toggle("Only priced", key="only_priced")

shown = [p for p in printings if not (hide_promos and p["promo"])
         and not (only_priced and p["usd"] is None and p["usd_foil"] is None and p["usd_etched"] is None)]
shown.sort(key=SORTS[sort], reverse=sort == "Newest")
if not shown:
    st.info("No printings match these filters.", icon=":material/filter_alt_off:")
    st.stop()

show_all = st.session_state.get(f"show_all-{card['name']}", False)
batch = shown if show_all or len(shown) <= FIRST_BATCH else shown[:FIRST_BATCH]
price_printing = card["price_printing"]

for start in range(0, len(batch), GRID_COLUMNS):
    cols = st.columns(GRID_COLUMNS)
    for col, p in zip(cols, batch[start:start + GRID_COLUMNS]):
        with col, st.container(border=True):
            label = f"{p['set_name']} ({p['set_code'].upper()}) #{p['collector_number']}"
            if p["image_url"] and p["image_url_back"]:
                flip_card(card["name"], p["image_url"], p["image_url_back"],
                          key=f"flip-{p['set_code']}-{p['collector_number']}")
            elif p["image_url"]:
                st.image(p["image_url"], width="stretch", alt=f"{card['name']}, {label}")
            st.markdown(f"**{label}**")
            details = [d for d in ((p["released_at"] or "")[:4], (p["rarity"] or "").title(), p["treatment"],
                                   "promo" if p["promo"] else "") if d]
            st.caption(" · ".join(details))
            st.caption(prices_line(p))
            if p["artist"]:
                st.caption(f"Art: {p['artist']}")
            if f"{p['set_code']} #{p['collector_number']}" == price_printing:
                st.badge("Price used by the deck builder", icon=":material/sell:", color="green")
            if p["scryfall_url"]:
                st.link_button("Scryfall", p["scryfall_url"], icon=":material/open_in_new:", width="stretch")

if len(batch) < len(shown):
    if st.button(f"Show all {len(shown)} printings", icon=":material/expand_more:", key="show_all"):
        st.session_state[f"show_all-{card['name']}"] = True
        st.rerun()

st.caption("Card images, prices and printings from Scryfall (daily bulk data). Unofficial fan project, "
           "not affiliated with Wizards of the Coast.")
