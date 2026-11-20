"""Watch list page: spec signals, new-commander radar, rising cards on EDHREC,
price risers, and your own list.

Data and storage live in ``watchlist.py``; this page only shows them.
"""

import datetime as dt
import time
from urllib.parse import quote

import streamlit as st

import alerts
import archidekt
import backtest
import card_db
import combos
import deck_service
import edhrec_client
import explain
import portfolio
import watchlist

COLORS = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green"}
VIEWS = ["Spec signals", "New commanders", "Combo spikes", "Casual meta", "Rising on EDHREC", "Price risers",
         "My watch list", "My cards", "Digest"]


def with_db(fn, *args):
    db = deck_service.open_db()
    wl = watchlist.WatchList()
    try:
        return fn(db, wl, *args)
    finally:
        wl.close()
        db.close()


@st.cache_data(ttl="1h", show_spinner="Checking for today's prices...")
def take_snapshot():
    """Today's price + EDHREC popularity snapshots (once per date; cheap if they exist).

    Catch-up for the cron job: cron can't run while the laptop sleeps, so opening
    this page asks Scryfall for a new daily file on the same 6-hour schedule as
    the cron job (one small request; the download only when Scryfall has a new one)."""
    db = card_db.open_db(max_age_hours=watchlist.SCRYFALL_CHECK_HOURS, log=lambda *_: None)
    wl = watchlist.WatchList()
    try:
        date, new = wl.snapshot(db)
        try:
            wl.snapshot_edhrec(watchlist.fetch_top("week"))
        except edhrec_client.EdhrecError:
            pass  # prices still work; popularity history just skips a day
        return date, new, len(wl.dates()), len(wl.edhrec_dates())
    finally:
        wl.close()
        db.close()


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


@st.cache_data(ttl="6h", show_spinner="Asking Commander Spellbook about new cards (first time ~20 s)...")
def load_spikes(max_usd):
    rising = load_rising()
    db = deck_service.open_db()
    try:
        return combos.combo_spikes(db, combos.new_cards(db, rising=rising), max_usd=max_usd)
    finally:
        db.close()


@st.cache_data(ttl="1h", show_spinner=False)
def load_backtest(horizon):
    return with_db(lambda db, wl: backtest.run(db, wl, horizon=horizon))


@st.cache_data(ttl="5m")
def claude_available():
    import os
    from dotenv import load_dotenv
    from scan_binder import ENV_PATH
    load_dotenv(ENV_PATH)
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def watched_rows(rising):
    return with_db(lambda db, wl: wl.watched(db, rising))


def add_cards(names):
    added = with_db(lambda db, wl: [wl.add(db, n) for n in names])
    st.toast(f"Watching {', '.join(added)}.", icon=":material/star:")


def signed_money(v):
    return f"{'-' if v < 0 else '+'}${abs(v):,.2f}"


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

import updater

STEP_OF_SOURCE = {"Card data (Scryfall)": "card data", "Prices": "prices", "Buylist (Card Kingdom)": "buylist",
                  "EDHREC popularity": "popularity", "Digest": "digest", "Casual decks (Archidekt)": "casual decks",
                  "Tournaments (EDHTop16)": "tournaments", "Card tags (Scryfall Tagger)": "card tags"}


@st.fragment(run_every="3s" if updater.running() else None)
def data_status():
    """Freshness of every source, the last update run, and the Update button. Polls while running."""
    pid = updater.running()
    status = updater.load_status()
    was_running = st.session_state.get("update_was_running", False)
    st.session_state.update_was_running = bool(pid)
    if was_running and not pid:
        st.cache_data.clear()  # new data: reload every view
        st.rerun()
    started, finished = status.get("started"), status.get("finished")
    label = ("Updating now..." if pid else
             f"Data status: last update {finished[:16] if finished else 'never (cron runs it hourly)'}")
    with st.expander(label, expanded=bool(pid), icon=":material/sync:" if pid else ":material/database:"):
        rows = []
        for source, latest, detail in updater.freshness():
            step = status["steps"].get(STEP_OF_SOURCE.get(source, ""), {})
            rows.append({"Source": source, "Latest": latest or "n/a", "Detail": detail,
                         "Last update": (("ok" if step.get("ok") else "failed") + f" {step.get('at', '')}") if step else "",
                         "Result": step.get("message", "")})
        st.dataframe(rows, hide_index=True, key="status_table")
        with st.container(horizontal=True, vertical_alignment="center"):
            force = st.checkbox("Force (re-run today's daily steps)", key="update_force", disabled=bool(pid),
                                help="Normally steps that already ran today are skipped. Sources still only change "
                                     "when they publish (Scryfall about 3 AM).")
            if st.button("Update everything now", type="primary", icon=":material/sync:", key="update_now",
                         disabled=bool(pid), help="Runs the daily job in the background (about 5-6 minutes "
                                                  "when everything is due); the app stays usable."):
                if updater.start_background(force=force):
                    st.session_state.update_was_running = True
                    time.sleep(1)
                    st.rerun(scope="app")
                else:
                    st.warning("An update is already running.", icon=":material/hourglass_top:")
        if pid:
            st.caption(f"Running since {started} (process {pid}). This panel refreshes every few seconds.")
        try:
            log_lines = updater.LOG_PATH.read_text().splitlines()
        except OSError:
            log_lines = []
        if log_lines:
            st.code("\n".join(log_lines[-12:]), language=None, height="content")


data_status()

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

    st.markdown("#### Why these cards?")
    cached = sorted(explain.CACHE_DIR.glob(f"{dt.date.today().isoformat()}_*.json")) if explain.CACHE_DIR.exists() else []
    if cached:
        import json as _json
        res = _json.loads(cached[-1].read_text())
        for r in res["rows"]:
            st.markdown(f"- **{r['name']}**: {r['why'] or '_no line returned_'}")
        st.caption(f"Written by {res['model']} from the facts above only (today's top out-of-print signals, "
                   f"cost ${res['cost_usd'] or 0:.3f}). Explanations, not advice.")
    elif claude_available():
        if st.button("Explain today's top 15 with Claude (about $0.02)", icon=":material/smart_toy:",
                     key="spec_explain"):
            from scan_binder import ScanError, make_client
            try:
                with st.spinner("Claude is writing one line per card..."):
                    with_db(lambda db, wl: explain.explain_today(db, wl, make_client(), top=15,
                                                                  rising=load_rising()))
                st.rerun()
            except ScanError as exc:
                st.error(f"Claude couldn't explain: {exc}", icon=":material/error:")
    else:
        st.caption("Claude explanations need an ANTHROPIC_API_KEY.")

    bt = load_backtest(7)
    st.markdown("#### Do the signals work?")
    if bt["needed"]:
        st.caption(f"Backtest not possible yet: it {bt['needed']}. It checks whether the top-scored cards rose "
                   "more than the rest over the next 7 days.")
    else:
        t, a = bt["top"], bt["all"]
        with st.container(horizontal=True):
            st.metric("Top 20: average 7-day change", f"{t['mean']:+.1f}%", border=True)
            st.metric("All scored cards", f"{a['mean']:+.1f}%", border=True)
            st.metric("Top 20 that rose 10%+", f"{t['hit_rate']:.0f}%", border=True,
                      delta=f"{t['hit_rate'] - a['hit_rate']:+.0f} pts vs all")
        st.caption(f"{len(bt['days'])} day(s) scored so far; noisy until several weeks of history.")

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
# Combo spikes
# ---------------------------------------------------------------------------

elif view == "Combo spikes":
    max_usd = st.number_input("Max price", min_value=0.5, value=20.0, step=1.0, key="spike_max",
                              persist_state="session")
    try:
        spikes = load_spikes(max_usd)
    except combos.ComboError as exc:
        st.error(f"Couldn't reach Commander Spellbook: {exc}", icon=":material/error:")
        st.stop()
    st.caption("Older cards (first printed over a year ago) that complete a combo with a new or upcoming card, "
               "from Commander Spellbook. When a new card creates a combo, the older piece often jumps. "
               "Select rows to watch them.")
    if not spikes:
        st.info("No older combo pieces under that price.", icon=":material/filter_alt_off:")
        st.stop()
    rows = spikes[:150]
    event = st.dataframe(
        [{"Card": e["name"], "Price": e["usd"], "New card(s)": ", ".join(dict.fromkeys(c["new_card"] for c in e["combos"])),
          "Combo makes": ", ".join(e["combos"][0]["produces"][:2]), "Supply": e["supply"],
          "Combo": e["combos"][0]["url"], "Page": card_url(e["name"])} for e in rows],
        column_config={"Price": st.column_config.NumberColumn(format="dollar"),
                       "Combo": st.column_config.LinkColumn(display_text="Spellbook"),
                       "Page": st.column_config.LinkColumn(display_text="Open")},
        hide_index=True, on_select="rerun", selection_mode="multi-row", key="spike_table",
    )
    picked = selected_names(event, rows)
    if st.button(f"Watch {len(picked)} selected" if picked else "Select cards to watch", key="spike_add",
                 icon=":material/star:", disabled=not picked):
        add_cards(picked)

# ---------------------------------------------------------------------------
# Casual meta (Archidekt)
# ---------------------------------------------------------------------------

elif view == "Casual meta":
    a = archidekt.Archidekt()
    try:
        counts = a.brackets()
        total = sum(counts.values())
        with st.container(horizontal=True, vertical_alignment="bottom"):
            options = [None] + [b for b in (1, 2, 3, 4, 5) if counts.get(b)]
            bracket = st.segmented_control(
                "Bracket", options, default=None, key="casual_bracket",
                format_func=lambda b: "All" if b is None else f"Bracket {b} ({counts.get(b, 0)})")
            if st.button("Fetch new decks now (about 2 minutes)", icon=":material/refresh:", key="casual_sample"):
                with st.spinner("Reading Archidekt's newest decks, 1 per second..."):
                    try:
                        a.sample(max_new=100, log=lambda *_: None)
                    except archidekt.ArchidektError as exc:
                        st.error(str(exc), icon=":material/error:")
                st.rerun()
        t = a.trends(bracket=bracket)
    finally:
        a.close()
    st.caption(f"New public Commander decks on Archidekt (complete 99+ card lists), sampled daily: {total:,} saved, "
               f"{counts.get(None, 0):,} without a bracket. Last 7 days ({t['recent_decks']} decks) vs the 28 days "
               f"before ({t['base_decks']}). Casual players, so this complements EDHREC's long-run averages.")
    if not t["recent_decks"]:
        st.info("No decks yet for this filter; the daily job adds about 150 a day.", icon=":material/hourglass_top:")
        st.stop()
    if not t["base_decks"]:
        st.info("Change vs earlier weeks shows once there are decks from before the last 7 days; for now this is "
                "what's in this week's new decks.", icon=":material/hourglass_top:")
    with st.container(horizontal=True):
        hide_staples = st.toggle("Hide staples", value=True, key="casual_staples",
                                 help="Leave out cards in EDHREC's overall top 300")
    db = deck_service.open_db()
    try:
        info = db.get_many([c["name"] for c in t["cards"][:600]])
    finally:
        db.close()
    rows = [c for c in t["cards"][:600]
            if not (hide_staples and info.get(c["name"]) and (info[c["name"]]["edhrec_rank"] or 99999) <= 300)][:200]
    event = st.dataframe(
        [{"Card": c["name"], "New decks": c["share"], "Change": None if c["change_pts"] is None else c["change_pts"],
          "Before": c["base_share"], "Price": info[c["name"]]["usd"] if c["name"] in info else None,
          "Page": card_url(c["name"])} for c in rows],
        column_config={"New decks": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                       "Change": st.column_config.NumberColumn(format="%+.1f pts"),
                       "Before": st.column_config.NumberColumn(format="percent"),
                       "Price": st.column_config.NumberColumn(format="dollar"),
                       "Page": st.column_config.LinkColumn(display_text="Open")},
        hide_index=True, on_select="rerun", selection_mode="multi-row", key="casual_table",
    )
    picked = selected_names(event, rows)
    if st.button(f"Watch {len(picked)} selected" if picked else "Select cards to watch", key="casual_add",
                 icon=":material/star:", disabled=not picked):
        add_cards(picked)
    st.markdown("**Commanders in new decks**")
    st.dataframe([{"Commander": c["commander"], "Last 7 days": c["decks"], "28 days before": c["base_decks"]}
                  for c in t["commanders"][:30]], hide_index=True, key="casual_commanders")

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

elif view == "My watch list":
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
    for h in with_db(lambda db, wl: wl.target_hits(db)):
        st.success(f"**{h['name']}** is ${h['usd']:.2f}, {h['direction']} your ${h['target']:.2f} target.",
                   icon=":material/notifications_active:")
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
    if len(picked) == 1:
        row = next(r for r in rows if r["name"] == picked[0])
        with st.form(f"target-{row['name']}", border=True):
            st.markdown(f"**Price alerts for {row['name']}** (shown here and in the daily digest)")
            with st.container(horizontal=True, vertical_alignment="bottom"):
                above = st.number_input("Alert at or above (USD)", min_value=0.0, value=row["target_above"],
                                        step=0.5, placeholder="none", key=f"tgt_up-{row['name']}")
                below = st.number_input("Alert at or below (USD)", min_value=0.0, value=row["target_below"],
                                        step=0.5, placeholder="none", key=f"tgt_down-{row['name']}")
                if st.form_submit_button("Save alerts", icon=":material/notifications:"):
                    with_db(lambda db, wl: wl.set_target(row["name"], above, below))
                    st.toast("Alerts saved.", icon=":material/notifications:")
                    st.rerun()
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

# ---------------------------------------------------------------------------
# My cards: binder value + buy log
# ---------------------------------------------------------------------------

elif view == "My cards":
    def _binder(db, wl):
        portfolio.track_owned(db, wl)
        return portfolio.binder_value(db, wl)
    b = with_db(_binder)
    st.subheader("Your binder")
    with st.container(horizontal=True):
        st.metric("Value today", f"${b['total']:,.2f}", border=True)
        st.metric("Cards", f"{b['cards']} ({b['copies']} copies)", border=True)
        st.metric("Card Kingdom would pay", f"${b['buylist_total']:,.2f}", border=True,
                  help=f"Buylist offers for the {b['buylist_cards']} cards Card Kingdom buys (MTGJSON); "
                       "stores pay less than market price.")
    if len(b["history"]) >= 2:
        st.line_chart([{"Date": d, "Value": v} for d, v in b["history"]], x="Date", y="Value", y_label="USD",
                      alt="Binder value over time")
    if b["risers"]:
        st.markdown("**Rising cards you own (7 days)**")
        for c in b["risers"]:
            st.markdown(f"- {c['name']}: {c['change_pct']:+.1f}% (now ${c['usd']:.2f})")
    if b["top"]:
        st.caption("Most valuable: " + ", ".join(f"{c['name']} ${(c['usd'] or 0) * c['qty']:.2f}" for c in b["top"][:5]))

    st.subheader("Buy log")
    with st.form("buy_add", border=True):
        with st.container(horizontal=True, vertical_alignment="bottom"):
            name = st.selectbox("Card", all_names(), index=None, placeholder="Type a card name...", key="buy_name")
            qty = st.number_input("Copies", min_value=1, value=1, step=1, key="buy_qty")
            price = st.number_input("Paid each (USD)", min_value=0.0, value=0.0, step=0.25, key="buy_price")
            day = st.date_input("Bought on", value=dt.date.today(), key="buy_date")
            if st.form_submit_button("Log buy", icon=":material/add_shopping_cart:") and name:
                with_db(lambda db, wl: portfolio.Portfolio(wl).buy(db, name, int(qty), float(price), day.isoformat()))
                st.toast(f"Logged {qty}x {name}.", icon=":material/check:")
                st.rerun()
    summary = with_db(lambda db, wl: portfolio.Portfolio(wl).summary(db))
    with st.container(horizontal=True):
        st.metric("Open: cost", f"${summary['open_cost']:,.2f}", border=True)
        st.metric("Open: value today", f"${summary['open_value']:,.2f}", border=True)
        st.metric("If sold now", signed_money(summary["unrealized"]), border=True,
                  help=f"After {portfolio.FEE_RATE:.0%} fees and ${portfolio.SHIPPING:.2f} shipping per sale")
        st.metric("Realized", signed_money(summary["realized"]), border=True)
        st.metric("Card Kingdom would pay", f"${summary['open_buylist']:,.2f}", border=True,
                  help="Buylist offers for your open buys, no fees")
    rows = summary["rows"]
    if rows:
        event = st.dataframe(
            [{"#": r["id"], "Card": r["name"], "Status": r["status"], "Qty": r["qty"], "Paid each": r["price_each"],
              "Now": r["usd_now"], "Buylist": r["buylist_now"], "Sold each": r["sold_each"], "Profit": r["profit"],
              "Profit %": None if r["profit_pct"] is None else r["profit_pct"] / 100, "Bought": r["bought_on"]}
             for r in rows],
            column_config={c: st.column_config.NumberColumn(format="dollar")
                           for c in ("Paid each", "Now", "Buylist", "Sold each", "Profit")}
            | {"Profit %": st.column_config.NumberColumn(format="percent")},
            hide_index=True, on_select="rerun", selection_mode="single-row", key="buy_table",
        )
        sel = event.selection.rows if event else []
        if sel:
            r = rows[sel[0]]
            with st.container(horizontal=True, vertical_alignment="bottom"):
                if r["status"] == "open":
                    sold = st.number_input("Sold each (USD)", min_value=0.0, value=r["usd_now"] or 0.0, step=0.25,
                                           key=f"sell-{r['id']}")
                    if st.button("Mark sold", icon=":material/sell:", key=f"sell_btn-{r['id']}"):
                        with_db(lambda db, wl: portfolio.Portfolio(wl).sell(r["id"], float(sold)))
                        st.rerun()
                if st.button("Delete entry", icon=":material/delete:", key=f"del_buy-{r['id']}"):
                    with_db(lambda db, wl: portfolio.Portfolio(wl).remove(r["id"]))
                    st.rerun()
        st.caption(f"Profit counts {portfolio.FEE_RATE:.0%} selling fees and ${portfolio.SHIPPING:.2f} shipping per "
                   "sale. \"Now\" is a market price, not a store's buylist offer (stores pay less).")
    else:
        st.caption("No buys logged yet.")

# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

else:
    files = sorted(alerts.DIGEST_DIR.glob("*.md")) if alerts.DIGEST_DIR.exists() else []
    settings_ok = alerts.email_settings() is not None
    st.caption("A digest is written for each new price day (by the cron job or this app) to data/digests/. "
               + ("It is also emailed." if settings_ok else
                  "Email is off: add WATCH_SMTP_HOST, WATCH_SMTP_USER, WATCH_SMTP_PASSWORD and WATCH_EMAIL_TO "
                  "to the repo's .env to get it by email."))
    if not files:
        st.info("No digest yet; one is written after the next new price snapshot.", icon=":material/mail:")
        st.stop()
    pick = st.selectbox("Day", [f.stem for f in reversed(files)], key="digest_day")
    st.markdown((alerts.DIGEST_DIR / f"{pick}.md").read_text())
