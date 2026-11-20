"""Commander deck builder - Streamlit app (entry point).

Run:
    /home/t9/venv/bin/streamlit run streamlit_app.py

Pages (menu at the top; the card page is reached by clicking a card name):
    app_pages/builder.py   build and check a deck (default page)
    app_pages/watch.py     rising cards (EDHREC), price risers, your watch list
    app_pages/tournaments.py  cEDH events from EDHTop16 (MagicCon...): cards, commanders, lists
    app_pages/card.py      one card: every printing with picture, set and price
"""

import streamlit as st

st.set_page_config(page_title="Commander deck builder", page_icon=":material/style:", layout="wide")

page = st.navigation(
    [
        st.Page("app_pages/builder.py", title="Deck builder", icon=":material/construction:", default=True,
                help="Pick a commander and a budget, build a legal deck, see its cards and combos."),
        st.Page("app_pages/watch.py", title="Watch list", icon=":material/trending_up:", url_path="watch",
                help="Cards rising on EDHREC this week, cards whose price is climbing, and your own watch list."),
        st.Page("app_pages/tournaments.py", title="Tournaments", icon=":material/emoji_events:",
                url_path="tournaments",
                help="cEDH events from EDHTop16 (e.g. MagicCon): commanders, most-played cards, decklists."),
        st.Page("app_pages/card.py", title="Card", icon=":material/style:", url_path="card", visibility="hidden",
                help="One card: every printing with its picture, set, price and a Scryfall link."),
    ],
    position="top",
)
page.run()
