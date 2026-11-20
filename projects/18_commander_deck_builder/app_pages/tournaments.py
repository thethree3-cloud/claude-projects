"""Tournaments page: import cEDH events from EDHTop16 (e.g. MagicCon) and study them.

Data and parsing live in ``tournaments.py``; this page shows saved events:
commanders and how they finished, the most-played cards (all decks vs the top
cut, with today's price and overall EDHREC rank), and every decklist.
"""

from urllib.parse import quote

import streamlit as st

import deck_service
import tournaments
import watchlist

TOP_CHOICES = [4, 8, 16]


@st.cache_data(ttl="1h", show_spinner=False)
def load_event(tid, imported_at):
    return tournaments.load_event(tid)


@st.cache_data(ttl="1h", show_spinner=False)
def load_tables(tid, imported_at, top):
    event = tournaments.load_event(tid)
    db = deck_service.open_db()
    try:
        return tournaments.commander_table(event), tournaments.card_table(event, db, top)
    finally:
        db.close()


@st.cache_data(ttl="1h", show_spinner=False)
def load_check(tid, imported_at, deck_id):
    event = tournaments.load_event(tid)
    entry = next(e for e in event["entries"] if e["id"] == deck_id)
    db = deck_service.open_db()
    try:
        return tournaments.check_deck(entry, db)
    finally:
        db.close()


def add_cards(names):
    db, wl = deck_service.open_db(), watchlist.WatchList()
    try:
        added = [wl.add(db, n) for n in names]
    finally:
        wl.close()
        db.close()
    st.toast(f"Watching {', '.join(added)}.", icon=":material/star:")


def card_url(name):
    return f"card?name={quote(name)}"


# ---------------------------------------------------------------------------

st.title("Tournaments")
st.caption("cEDH events and their decklists from EDHTop16 (data from TopDeck.gg). Competitive decks: fast mana, "
           "tutors and combos, so expect pricier lists than at a casual table.")

with st.form("import_event", border=True):
    with st.container(horizontal=True, vertical_alignment="bottom"):
        link = st.text_input("Import an event", key="event_link",
                             placeholder="https://edhtop16.com/tournament/...",
                             help="Paste an EDHTop16 tournament link. Each decklist is fetched once, about one "
                                  "per second, then kept.")
        go = st.form_submit_button("Import", icon=":material/download:")
    if go and link:
        try:
            with st.spinner("Fetching the event and its decklists (about 1 second per deck)..."):
                event = tournaments.import_event(link, log=lambda *_: None)
            st.session_state.event_pick = event["tid"]
            st.toast(f"Imported {len(event['entries'])} decklists.", icon=":material/check:")
        except tournaments.TournamentError as exc:
            st.error(str(exc), icon=":material/error:")

events = tournaments.saved_events()
if not events:
    st.info("No events yet. Try the MagicCon Atlanta cEDH Open: "
            "https://edhtop16.com/tournament/tagc-x-bad-naus-magiccon-atlanta-cedh-open",
            icon=":material/emoji_events:")
    st.stop()

by_tid = {e["tid"]: e for e in events}
tid = st.selectbox("Event", list(by_tid), key="event_pick",
                   format_func=lambda t: f"{by_tid[t]['date']} - {by_tid[t]['name']}")
meta = tournaments.load_event(tid)
event = load_event(tid, meta["imported_at"])

with st.container(horizontal=True):
    st.metric("Date", event["date"], border=True)
    st.metric("Players", event["size"], border=True)
    st.metric("Decklists", len(event["entries"]), border=True)
    winner = next((e for e in event["entries"] if e["standing"] == 1), None)
    st.metric("Winner", winner["commander"] if winner else "n/a", border=True,
              help=winner["player"] if winner else None)
links = [f"[EDHTop16]({event['url']})"] + ([f"[bracket]({event['bracket_url']})"] if event.get("bracket_url") else [])
st.caption(" · ".join(links) + f" · imported {event['imported_at']}"
           + (f" · {len(event['failed'])} lists couldn't be read" if event.get("failed") else ""))

top = st.segmented_control("Top cut", TOP_CHOICES, default=16, key="event_top", required=True,
                           format_func=lambda n: f"Top {n}")
commanders, cards = load_tables(tid, meta["imported_at"], top)
cards_tab, cmd_tab, decks_tab = st.tabs(["Most-played cards", "Commanders", "Decklists"])

with cards_tab:
    n_top = cards[0]["top_size"] if cards else 0
    with st.container(horizontal=True, vertical_alignment="bottom"):
        hide_staples = st.toggle("Hide staples", key="event_hide_staples",
                                 help="Leave out cards in EDHREC's overall top 1,000 (Sol Ring, fetch lands...)")
        hide_lands = st.toggle("Hide lands", key="event_hide_lands")
        max_price = st.number_input("Max price", min_value=0.0, value=None, step=1.0, placeholder="Any",
                                    key="event_max_price")
    rows = [r for r in cards
            if not (hide_staples and r["edhrec_rank"] is not None and r["edhrec_rank"] <= 1000)
            and not (hide_lands and "Land" in r["type"].split(" // ")[0])
            and (max_price is None or (r["usd"] is not None and r["usd"] <= max_price))][:200]
    st.caption(f"Cards (not commanders or basics) by how many of the {n_top} top-{top} decks with a published "
               f"list played them, then all {len(event['entries'])} decks. A high EDHREC rank number means the card "
               "is rare in Commander overall: an unusual pick here. Select rows to watch them.")
    event_sel = st.dataframe(
        [{"Card": r["name"], f"Top {top}": r["top_share"], "All decks": r["share"], "Price": r["usd"],
          "EDHREC rank": r["edhrec_rank"], "Type": r["type"].split(" — ")[0], "Page": card_url(r["name"])}
         for r in rows],
        column_config={
            f"Top {top}": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
            "All decks": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
            "Price": st.column_config.NumberColumn(format="dollar"),
            "EDHREC rank": st.column_config.NumberColumn(help="Overall popularity in Commander (1 = most played)"),
            "Page": st.column_config.LinkColumn(display_text="Open"),
        },
        hide_index=True, on_select="rerun", selection_mode="multi-row", key="event_cards",
    )
    picked = [rows[i]["name"] for i in event_sel.selection.rows] if event_sel else []
    if st.button(f"Watch {len(picked)} selected" if picked else "Select cards to watch", key="event_watch",
                 icon=":material/star:", disabled=not picked):
        add_cards(picked)

with cmd_tab:
    st.dataframe(
        [{"Best finish": c["best"], "Commander": c["commander"], "Decks": c["decks"], "Average finish": c["average"],
          "Record (W-L-D)": f"{c['wins']}-{c['losses']}-{c['draws']}", "Players": ", ".join(p or "?" for p in c["players"])}
         for c in commanders],
        hide_index=True, key="event_commanders",
    )

with decks_tab:
    entries = event["entries"]
    deck_sel = st.dataframe(
        [{"Finish": e["standing"], "Player": e["player"], "Commander": e["commander"],
          "Record": f"{e['wins']}-{e['losses']}-{e['draws']}", "Deck price": e["price_usd"],
          "TopDeck": e["topdeck_url"]} for e in entries],
        column_config={"Deck price": st.column_config.NumberColumn(format="dollar", help="EDHTop16's estimate"),
                       "TopDeck": st.column_config.LinkColumn(display_text="List")},
        hide_index=True, on_select="rerun", selection_mode="single-row", key="event_decks",
    )
    sel = deck_sel.selection.rows if deck_sel else []
    if not sel:
        st.caption("Select a deck to see its cards, check it and download it.")
    else:
        entry = entries[sel[0]]
        check = load_check(tid, meta["imported_at"], entry["id"])
        st.subheader(f"#{entry['standing']} {entry['player']}: {entry['commander']}")
        with st.container(horizontal=True, vertical_alignment="center"):
            st.badge("Passes the validator" if check["ok"] else "Validator found problems",
                     color="green" if check["ok"] else "red",
                     icon=":material/check:" if check["ok"] else ":material/error:")
            st.caption(f"{check['stats'].get('lands', '?')} lands, average mana value "
                       f"{check['stats'].get('average_mana_value', 0):.2f}, "
                       f"lowest bracket {check['stats'].get('lowest_bracket', '?')}")
            st.download_button("Download import list", tournaments.deck_text(entry) + "\n",
                               file_name=f"{tid}_{entry['standing']}_{entry['id'][:6]}.txt",
                               icon=":material/download:", key=f"dl-{entry['id']}")
        for e in check["errors"]:
            st.error(e, icon=":material/error:")
        groups = {}
        for c in entry["cards"]:
            kind = deck_service.card_type({"type_line": c["type"]})
            groups.setdefault(kind, []).append(c)
        cols = st.columns(3)
        for i, kind in enumerate(k for k in (*deck_service.CARD_TYPES, "Other") if k in groups):
            with cols[i % 3]:
                st.markdown(f"**{kind} ({sum(c['count'] for c in groups[kind])})**")
                st.markdown("\n".join(f"- {c['count']} [{c['name']}]({card_url(c['name'])})"
                                      for c in sorted(groups[kind], key=lambda c: c["name"])))
