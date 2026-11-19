"""Watch list page: spec signals, new-commander radar, rising cards on EDHREC,
price risers, and your own list.

Data and storage live in ``watchlist.py``; this page only shows them.
"""

import datetime as dt
from urllib.parse import quote

import streamlit as st

import deck_service
import edhrec_client
import watchlist

COLORS = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green"}
VIEWS = ["Spec signals", "New commanders", "Rising on EDHREC", "Price risers", "My watch list"]


def with_db(fn, *args):
    db = deck_service.open_db()
    wl = watchlist.WatchList()
    try:
        return fn(db, wl, *args)
    finally:
        wl.close()
        db.close()


@st.cache_data(ttl="1h", show_spinner=False)
def take_snapshot():
    """Today's price + EDHREC popularity snapshots (once per date; cheap if they exist)."""
    def take(db, wl):
        date, new = wl.snapshot(db)
        try:
            wl.snapshot_edhrec(watchlist.fetch_top("week"))
        except edhrec_client.EdhrecError:
            pass  # prices still work; popularity history just skips a day
        return date, new, len(wl.dates()), len(wl.edhrec_dates())
    return with_db(take)


@st.cache_data(ttl="1h", show_spinner="Scoring cards...")
def load_spec(min_usd, max_usd, include_new, out_of_print):
    rising = load_rising()
    return with_db(lambda db, wl: watchlist.spec_signals(db, wl, rising, min_usd, max_usd, include_new,
                                                          out_of_print_only=out_of_print))


@st.cache_data(ttl="6h", show_spinner="Reading rising commanders' EDHREC pages (first time ~10 s)...")
def load_radar(max_usd, per_commander):
    db = deck_service.open_db()
    try:
        return watchlist.commander_radar(db, per_commander=per_commander, max_usd=max_usd)
    finally:
        db.close()


@st.cache_data(ttl="6h", show_spinner="Reading EDHREC's top cards (first time ~10 s)...")
def load_rising():
    db = deck_service.open_db()
    try:
        return watchlist.rising_cards(db)
    finally:
        db.close()


@st.cache_data(ttl="1h", show_spinner=False)
def load_price_risers(days, min_usd):
    return with_db(lambda db, wl: wl.price_risers(db, days, min_usd, limit=100))


@st.cache_data(ttl="1d", show_spinner=False)
def all_names():
    db = deck_service.open_db()
    try:
        return [r[0] for r in db.conn.execute("SELECT name FROM cards ORDER BY edhrec_rank IS NULL, edhrec_rank")]
    finally:
        db.close()


def watched_rows(rising):
    return with_db(lambda db, wl: wl.watched(db, rising))


def add_cards(names):
    added = with_db(lambda db, wl: [wl.add(db, n) for n in names])
    st.toast(f"Watching {', '.join(added)}.", icon=":material/star:")


def card_url(name):
    return f"card?name={quote(name)}"


def colors_label(identity):
    return "".join(identity) if identity else ("C" if identity == "" else "")


def fits(identity, chosen):
    """Card fits a deck of the chosen colors (no colors chosen = any card)."""
    return not chosen or (identity is not None and set(identity) <= set(chosen))


def selected_names(event, rows):
    return [rows[i]["name"] for i in (event.selection.rows if event else [])]


# ---------------------------------------------------------------------------

st.title("Card watch list")
date, _, days_of_history, edhrec_days = take_snapshot()
st.caption(f"Popularity from EDHREC (past week vs past 2 years); prices from Scryfall. Both saved daily: "
           f"{days_of_history} day{'s' if days_of_history != 1 else ''} of prices, {edhrec_days} of popularity "
           f"(latest {date}). Signals to research, not predictions.")

view = st.segmented_control("View", VIEWS, default=VIEWS[0], key="watch_view", required=True,
                            label_visibility="collapsed", persist_state="session")

# ---------------------------------------------------------------------------
# Spec signals
# ---------------------------------------------------------------------------

if view == "Spec signals":
    with st.container(horizontal=True, vertical_alignment="bottom"):
        out_of_print = st.toggle("Out of print only", value=True, key="spec_oop", persist_state="session",
                                 help="Last printed over a year ago, so no set is still adding copies")
        include_new = st.toggle("Include new cards", key="spec_new", persist_state="session",
                                help=f"Cards first printed in the last {watchlist.NEW_CARD_DAYS} days (new-set hype)")
        min_usd = st.number_input("Min price", min_value=0.0, value=0.5, step=0.5, key="spec_min",
                                  persist_state="session")
        max_usd = st.number_input("Max price", min_value=0.0, value=None, step=1.0, key="spec_max",
                                  placeholder="Any", persist_state="session")
    try:
        rows = load_spec(min_usd, max_usd, include_new, out_of_print)
    except edhrec_client.EdhrecError as exc:
        st.error(f"Couldn't read EDHREC: {exc}", icon=":material/error:")
        st.stop()
    st.caption("Cards gaining players on EDHREC while the price hasn't caught up, weighted by supply. "
               "Score = EDHREC trend (+ our own 7-day popularity gain once there are two days) x supply x price. "
               "The weights are a first guess until enough history exists to test them. Select rows to watch.")
    if not rows:
        st.info("No cards match. Try turning off **Out of print only** or widening the price range.",
                icon=":material/filter_alt_off:")
        st.stop()
    event = st.dataframe(
        [{"Card": r["name"], "Score": r["score"], "Price": r["usd"],
          "Popularity": "new on list" if r["new"] else f"{r['change_pts']:+.1f} pts",
          "7-day popularity": r["pop_change_pts"], "7-day price": None if r["price_change_pct"] is None
          else r["price_change_pct"] / 100, "Supply": r["supply"], "Why": "; ".join(r["reasons"]),
          "Page": card_url(r["name"])} for r in rows[:200]],
        column_config={
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=max(r["score"] for r in rows),
                                                     format="%.1f"),
            "Price": st.column_config.NumberColumn(format="dollar"),
            "7-day popularity": st.column_config.NumberColumn(format="%+.2f pts",
                                                              help="From our daily EDHREC snapshots"),
            "7-day price": st.column_config.NumberColumn(format="percent"),
            "Page": st.column_config.LinkColumn(display_text="Open"),
        },
        hide_index=True, on_select="rerun", selection_mode="multi-row", key="spec_table",
    )
    picked = selected_names(event, rows)
    if st.button(f"Watch {len(picked)} selected" if picked else "Select cards to watch", key="spec_add",
                 icon=":material/star:", disabled=not picked):
        add_cards(picked)

# ---------------------------------------------------------------------------
# New-commander radar
# ---------------------------------------------------------------------------

elif view == "New commanders":
    with st.container(horizontal=True, vertical_alignment="bottom"):
        max_usd = st.number_input("Max card price", min_value=0.5, value=10.0, step=1.0, key="radar_max",
                                  persist_state="session")
        per = st.segmented_control("Cards per commander", [5, 8, 12], default=8, key="radar_per", required=True,
                                   persist_state="session")
    try:
        radar = load_radar(max_usd, per)
    except edhrec_client.EdhrecError as exc:
        st.error(f"Couldn't read EDHREC: {exc}", icon=":material/error:")
        st.stop()
    st.caption("Commanders gaining fastest on EDHREC this week, and their cheap cards with the highest synergy "
               "(played far more with this commander than elsewhere): what new decks for them will buy.")
    for c in radar:
        with st.container(border=True):
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(f"**{c['commander']}**", width="content")
                st.badge(f"trend {c['trend']}", color="orange", icon=":material/trending_up:")
                st.caption(f"{c['week_decks']:,} decks this week")
                st.page_link("app_pages/card.py", label="Card page", query_params={"name": c["commander"]},
                             icon=":material/open_in_new:")
            if not c["cards"]:
                st.caption("No high-synergy cards under that price.")
                continue
            st.dataframe(
                [{"Card": x["name"], "Synergy": x["synergy"], "Played in": x["inclusion"], "Price": x["usd"],
                  "Supply": x["supply"], "Page": card_url(x["name"])} for x in c["cards"]],
                column_config={
                    "Synergy": st.column_config.NumberColumn(format="percent"),
                    "Played in": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                    "Price": st.column_config.NumberColumn(format="dollar"),
                    "Page": st.column_config.LinkColumn(display_text="Open"),
                },
                hide_index=True, key=f"radar-{c['commander']}",
            )

# ---------------------------------------------------------------------------
# Rising on EDHREC
# ---------------------------------------------------------------------------

elif view == "Rising on EDHREC":
    try:
        rising = load_rising()
    except edhrec_client.EdhrecError as exc:
        st.error(f"Couldn't read EDHREC: {exc}", icon=":material/error:")
        st.stop()
    with st.container(horizontal=True, vertical_alignment="bottom"):
        chosen = st.pills("Fits these colors", list(COLORS), selection_mode="multi", key="rise_colors",
                          format_func=lambda c: COLORS[c], persist_state="session")
        max_price = st.number_input("Max price (USD)", min_value=0.0, value=None, step=1.0, key="rise_max",
                                    placeholder="Any", persist_state="session")
        hide_lands = st.toggle("Hide lands", value=True, key="rise_lands", persist_state="session")
        new_only = st.toggle("New this week only", key="rise_new", persist_state="session")
    rows = [r for r in rising
            if fits(r["color_identity"], chosen)
            and (max_price is None or (r["usd"] is not None and r["usd"] <= max_price))
            and not (hide_lands and r["type_line"] and "Land" in r["type_line"].split(" // ")[0])
            and (not new_only or r["new"])][:200]
    st.caption(f"{len(rows)} of the {len(rising)} cards in EDHREC's top list this week, most rising first. "
               "Trend is EDHREC's score (higher = gaining faster). Select rows to watch them.")
    event = st.dataframe(
        [{"Card": r["name"], "Trend": r["trend"], "This week": r["week_inclusion"],
          "Past 2 years": r["year_inclusion"],
          "Change": "new" if r["new"] else f"{r['change_pts']:+.1f} pts",
          "Price": r["usd"], "Colors": colors_label(r["color_identity"]),
          "Type": (r["type_line"] or "").split(" — ")[0], "Page": card_url(r["name"])} for r in rows],
        column_config={
            "This week": st.column_config.ProgressColumn("This week", format="percent", min_value=0, max_value=1,
                                                         help="Share of decks that could play it that do, past week"),
            "Past 2 years": st.column_config.NumberColumn(format="percent"),
            "Price": st.column_config.NumberColumn(format="dollar"),
            "Page": st.column_config.LinkColumn(display_text="Open", help="Card page with every printing"),
        },
        hide_index=True, on_select="rerun", selection_mode="multi-row", key="rise_table",
    )
    picked = selected_names(event, rows)
    if st.button(f"Watch {len(picked)} selected" if picked else "Select cards to watch", key="rise_add",
                 icon=":material/star:", disabled=not picked):
        add_cards(picked)

# ---------------------------------------------------------------------------
# Price risers
# ---------------------------------------------------------------------------

elif view == "Price risers":
    with st.container(horizontal=True, vertical_alignment="bottom"):
        days = st.segmented_control("Over", [7, 30], default=7, key="price_days", required=True,
                                    format_func=lambda d: f"{d} days", persist_state="session")
        min_usd = st.number_input("Ignore cards under (USD)", min_value=0.0, value=1.0, step=0.5, key="price_min",
                                  persist_state="session")
    found = load_price_risers(days, min_usd)
    if found["from"] is None:
        st.info("Price history starts today, so there's nothing to compare yet. A snapshot is saved each day "
                "the app (or `python watchlist.py snapshot`) runs; risers show up from the second day.",
                icon=":material/hourglass_top:")
        st.stop()
    rows = found["rows"]
    span = (dt.date.fromisoformat(found["to"]) - dt.date.fromisoformat(found["from"])).days
    st.caption(f"Price change from {found['from']} to {found['to']} ({span} days"
               + (", all the history so far" if span < days else "")
               + "). Cheapest regular printing, from Scryfall. Select rows to watch them.")
    if not rows:
        st.info("No card at or above that price went up in this window.", icon=":material/trending_flat:")
        st.stop()
    event = st.dataframe(
        [{"Card": r["name"], "Change": r["change_pct"] / 100, "Then": r["old"], "Now": r["new"],
          "Colors": colors_label(r["color_identity"]), "Type": (r["type_line"] or "").split(" — ")[0],
          "Page": card_url(r["name"])} for r in rows],
        column_config={
            "Change": st.column_config.NumberColumn(format="percent"),
            "Then": st.column_config.NumberColumn(format="dollar"),
            "Now": st.column_config.NumberColumn(format="dollar"),
            "Page": st.column_config.LinkColumn(display_text="Open"),
        },
        hide_index=True, on_select="rerun", selection_mode="multi-row", key="price_table",
    )
    picked = selected_names(event, rows)
    if st.button(f"Watch {len(picked)} selected" if picked else "Select cards to watch", key="price_add",
                 icon=":material/star:", disabled=not picked):
        add_cards(picked)

# ---------------------------------------------------------------------------
# My watch list
# ---------------------------------------------------------------------------

else:
    with st.form("watch_add", border=True):
        with st.container(horizontal=True, vertical_alignment="bottom"):
            name = st.selectbox("Add a card", all_names(), index=None, placeholder="Type a card name...",
                                key="watch_new")
            note = st.text_input("Note (optional)", key="watch_note", placeholder="e.g. for the Kestia deck")
            submitted = st.form_submit_button("Watch", icon=":material/star:")
        if submitted and name:
            with_db(lambda db, wl: wl.add(db, name, note))
            st.toast(f"Watching {name}.", icon=":material/star:")

    try:
        rising = load_rising()
    except edhrec_client.EdhrecError:
        rising = []  # the list still works without EDHREC
    rows = watched_rows(rising)
    if not rows:
        st.info("Nothing on your list yet. Add a card above, star one on its card page, or select rows in "
                "the rising lists.", icon=":material/star_border:")
        st.stop()

    def pct(value):
        return None if value is None else value / 100

    event = st.dataframe(
        [{"Card": r["name"], "Price": r["usd"], "Since added": pct(r["since_added_pct"]),
          "7 days": pct(r["change_7d_pct"]), "30 days": pct(r["change_30d_pct"]),
          "EDHREC trend": r["trend"], "This week": r["week_inclusion"], "Added": r["added_at"],
          "Note": r["note"], "Page": card_url(r["name"])} for r in rows],
        column_config={
            "Price": st.column_config.NumberColumn(format="dollar"),
            "Since added": st.column_config.NumberColumn(format="percent"),
            "7 days": st.column_config.NumberColumn(format="percent"),
            "30 days": st.column_config.NumberColumn(format="percent"),
            "EDHREC trend": st.column_config.NumberColumn(help="Only for cards in EDHREC's top list this week"),
            "This week": st.column_config.NumberColumn(format="percent"),
            "Page": st.column_config.LinkColumn(display_text="Open"),
        },
        hide_index=True, on_select="rerun", selection_mode="multi-row", key="watch_table",
    )
    picked = selected_names(event, rows)
    if st.button(f"Remove {len(picked)} selected" if picked else "Select cards to remove", key="watch_remove",
                 icon=":material/delete:", disabled=not picked):
        with_db(lambda db, wl: [wl.remove(n) for n in picked])
        st.rerun()

    charted = [r for r in rows if len(r["history"]) >= 2 and (not picked or r["name"] in picked)]
    st.subheader("Price history")
    if charted:
        series = {}
        for r in charted:
            for date, usd in r["history"]:
                series.setdefault(date, {})[r["name"]] = usd
        st.line_chart([{"Date": d, **v} for d, v in sorted(series.items())], x="Date", y=[r["name"] for r in charted],
                      y_label="USD", alt="Price history of watched cards")
    else:
        st.caption("Charts appear once there are two or more days of prices.")
