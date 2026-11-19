"""Commander deck builder - Streamlit app (entry point).

Run:
    /home/t9/venv/bin/streamlit run streamlit_app.py

Two pages, no menu (the card page is reached by clicking a card name):
    app_pages/builder.py   build and check a deck (default page)
    app_pages/card.py      one card: every printing with picture, set and price
"""

import streamlit as st

st.set_page_config(page_title="Commander deck builder", page_icon=":material/style:", layout="wide")

page = st.navigation(
    [
        st.Page("app_pages/builder.py", title="Deck builder", icon=":material/construction:", default=True,
                help="Pick a commander and a budget, build a legal deck, see its cards and combos."),
        st.Page("app_pages/card.py", title="Card", icon=":material/style:", url_path="card",
                help="One card: every printing with its picture, set, price and a Scryfall link."),
    ],
    position="hidden",
)
page.run()
