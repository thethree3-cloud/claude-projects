"""Card watch list: rising cards on EDHREC, price risers, and your own list.

- **Rising on EDHREC:** EDHREC's top-card lists for the past week and the past
  2 years (first ``TOP_PAGES`` x 100 cards each, cached for a day). Each card
  has a trend score from EDHREC (``trend_zscore``, higher = gaining faster)
  and an inclusion rate (decks playing it / decks that could) for each window,
  so the gain in percentage points is visible too. Cards in this week's list
  but not in the 2-year one are new arrivals.
- **Price risers:** a daily snapshot of every card's price from the Scryfall
  bulk file we already download (``data/watchlist.sqlite``), compared over 7
  or 30 days. History starts the day snapshots start; Scryfall has no past
  prices to backfill.
- **My watch list:** cards you add; their price history is kept for good
  (other cards' snapshots are pruned after ``KEEP_DAYS``).

- **Spec signals:** cards gaining players while the price hasn't moved,
  weighted by supply (printings, last printed, Reserved List, a reprint on the
  way). Every row lists its reasons.
- **New-commander radar:** commanders rising on EDHREC this week and their
  cheap, high-synergy cards (what new decks for them will buy).

CLI (e.g. from cron, so price history has no gaps):
    python watchlist.py snapshot
    python watchlist.py spec --max-usd 10
    python watchlist.py radar --commanders 5
    python watchlist.py rising --limit 20
    python watchlist.py prices --days 7
    python watchlist.py add "The One Ring" | remove NAME | list
"""

import argparse
import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path

import card_db
import edhrec_client

DATA_DIR = Path(__file__).parent / "data"
DB_NAME = "watchlist.sqlite"
TOP_PAGES = 10  # x100 cards per EDHREC window
KEEP_DAYS = 120  # price snapshots older than this are pruned (watched cards are kept)
MIN_TRACK_USD = 0.25  # cheaper cards aren't snapshotted (unless watched): their % moves are noise
WINDOWS = {"week": "top/week", "year": "top/year",  # EDHREC's "year" page is the past 2 years
           "commanders_week": "commanders/week"}
RADAR_COMMANDERS = 10  # rising commanders whose pages the radar reads
SCRYFALL_CHECK_HOURS = 6  # the CLI asks Scryfall for a new daily file this often (one small request;
                          # the ~80 MB download only happens when Scryfall has published a new one)
NEW_CARD_DAYS = 30  # cards first printed this recently are new-set hype, hidden from spec signals by default

# Compact on purpose (~16k priced cards a day): small integer card ids, dates
# as YYYYMMDD integers, prices in cents, no rowid -> ~0.3 MB per day.
SCHEMA = """
CREATE TABLE IF NOT EXISTS card_ids (
    id INTEGER PRIMARY KEY,
    oracle_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS snapshots (
    day INTEGER NOT NULL,        -- Scryfall bulk date as YYYYMMDD
    card INTEGER NOT NULL,       -- card_ids.id
    cents INTEGER NOT NULL,
    eur_cents INTEGER,           -- cheapest regular Cardmarket price (None if unknown)
    buy_cents INTEGER,           -- Card Kingdom buylist offer for that printing (MTGJSON)
    PRIMARY KEY (day, card)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS tracked (     -- always snapshotted and never pruned (owned / bought cards)
    oracle_id TEXT PRIMARY KEY,
    why TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS edhrec_names (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS edhrec_days (   -- EDHREC's past-week top list, saved daily
    day INTEGER NOT NULL,                  -- YYYYMMDD (local date it was saved)
    name INTEGER NOT NULL,                 -- edhrec_names.id
    decks INTEGER NOT NULL,
    potential INTEGER NOT NULL,
    trend_milli INTEGER,                   -- trend z-score x 1000
    PRIMARY KEY (day, name)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS watched (
    name TEXT PRIMARY KEY,
    oracle_id TEXT NOT NULL,
    added_at TEXT NOT NULL,
    usd_when_added REAL,
    note TEXT NOT NULL DEFAULT '',
    target_above REAL,               -- alert when the price reaches this or more
    target_below REAL                -- alert when the price drops to this or less
);
"""


# ---------------------------------------------------------------------------
# EDHREC: rising cards
# ---------------------------------------------------------------------------


def fetch_top(window, pages=TOP_PAGES, cache_dir=edhrec_client.CACHE_DIR, get=None):
    """EDHREC top cards for a window ("week" or "year"): ``[{name, num_decks,
    potential_decks, trend_zscore}]`` in EDHREC's order. Cached for a day."""
    cache_file = Path(cache_dir) / f"edhrec_top_{window}_{pages}.json"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < 86400:
        return json.loads(cache_file.read_text())
    get = get or (lambda path: edhrec_client._get_json(f"{edhrec_client.PAGES_URL}/{path}.json", path))
    views, path = [], WINDOWS[window]
    for _ in range(pages):
        page = get(path)
        try:
            if "container" in page:  # first page
                lists = page["container"]["json_dict"]["cardlists"]
                found = [v for cl in lists for v in cl.get("cardviews", [])]
                more = lists[0].get("more") if lists else None
            else:  # later pages are bare lists
                found, more = page.get("cardviews", []), page.get("more")
        except (KeyError, TypeError, AttributeError) as exc:
            raise edhrec_client.EdhrecError("Unexpected EDHREC top-cards format (EDHREC may have changed).") from exc
        views += [{"name": v["name"], "num_decks": v.get("num_decks") or 0,
                   "potential_decks": v.get("potential_decks") or 0, "trend_zscore": v.get("trend_zscore")}
                  for v in found if v.get("name")]
        if not more:
            break
        path = more.removesuffix(".json")
    if not views:
        raise edhrec_client.EdhrecError(f"EDHREC's top-cards list for the past {window} was empty.")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(views))
    return views


def _inclusion(view):
    return view["num_decks"] / view["potential_decks"] if view and view["potential_decks"] else None


def rising_cards(db, week=None, year=None):
    """Cards in this week's EDHREC top list, most-rising first.

    Each: name, trend (EDHREC z-score), week / 2-year inclusion, change in
    percentage points (None for a new arrival), week rank, decks this week,
    plus price, colors and type from the card database (cards it doesn't know,
    e.g. brand-new spoilers, keep None there)."""
    week = fetch_top("week") if week is None else week
    year = fetch_top("year") if year is None else year
    year_by_name = {v["name"]: v for v in year}
    info = db.get_many([v["name"] for v in week])
    rows = []
    for rank, v in enumerate(week, 1):
        w_inc, y_inc = _inclusion(v), _inclusion(year_by_name.get(v["name"]))
        card = info.get(v["name"])
        rows.append({
            "name": card["name"] if card else v["name"],
            "trend": round(v["trend_zscore"], 2) if v["trend_zscore"] is not None else None,
            "week_inclusion": w_inc,
            "year_inclusion": y_inc,
            "change_pts": round((w_inc - y_inc) * 100, 1) if w_inc is not None and y_inc is not None else None,
            "new": y_inc is None,
            "week_rank": rank,
            "week_decks": v["num_decks"],
            "usd": card["usd"] if card else None,
            "color_identity": card["color_identity"] if card else None,
            "type_line": card["type_line"] if card else None,
            "legal_commander": bool(card["legal_commander"]) if card else None,
        })
    rows.sort(key=lambda r: (r["trend"] is None, -(r["trend"] or 0), r["week_rank"]))
    return rows


# ---------------------------------------------------------------------------
# Spec signals: popular, still cheap, short supply
# ---------------------------------------------------------------------------


# Weights tuned 2026-11-19 from 89 days of backfilled prices (backtest.price_patterns,
# ~50k card-weeks, cards $1+). 30 days after a start day: still in print -9.7% mean,
# Reserved List +1.0%, 1 printing -0.1%, 8+ printings +1.0%, reprint coming -1.1%
# (n=131); cards up 30%+ in the prior week -11.6% median, up 10-30% -3.4%, down 10%+
# -7.9% mean. First guesses were: Reserved 1.5, 1 printing 1.3/1.15, 2-3 1.15,
# 8+ 0.85, in print 0.9, reprint 0.5; price up 10-30% 0.7, up 30%+ 0.4, falling 1.0.
SUPPLY_WEIGHTS = {"reprint": 0.7, "reserved": 1.1, "in_print": 0.75, "one": 1.0, "few": 1.0, "some": 1.0,
                  "many": 1.0}
PRICE_WEIGHTS = {"up_big": 0.5, "up": 0.8, "down": 0.8, "flat": 1.0}


def supply_factor(sup, today=None):
    """(multiplier, label) for how scarce a card is (weights from the price backtest above)."""
    w = SUPPLY_WEIGHTS
    if sup is None:
        return 1.0, "unknown"
    if sup["upcoming"]:
        return w["reprint"], "reprint coming: " + ", ".join(sup["upcoming"][:2])
    if sup["reserved"]:
        return w["reserved"], "Reserved List"
    n = sup["printings"]
    years = None
    if sup["last"]:
        today = dt.date.fromisoformat(today) if today else dt.date.today()
        years = (today - dt.date.fromisoformat(sup["last"])).days / 365
    since = f", last {sup['last'][:4]}" if sup["last"] else ""
    plural = "printing" if n == 1 else "printings"
    if years is not None and years < 1:
        # Printed within the year: that set is still being opened, so supply is still growing
        # (the clearest pattern in the backtest: these fell ~10% over the next 30 days).
        return w["in_print"], f"in print ({n} {plural}, last {sup['last']})"
    if n <= 1:
        return w["one"], f"1 printing{since}"
    if n <= 3:
        return w["few"], f"{n} printings{since}"
    if n <= 7:
        return w["some"], f"{n} printings{since}"
    return w["many"], f"{n} printings (plentiful){since}"


def price_factor(change_pct):
    """(multiplier, label): cards that already jumped tend to fall back, and falling
    cards tend to keep falling (backtest above)."""
    w = PRICE_WEIGHTS
    if change_pct is None:
        return 1.0, "price history building"
    if change_pct > 30:
        return w["up_big"], f"price already up {change_pct:+.0f}%"
    if change_pct > 10:
        return w["up"], f"price up {change_pct:+.0f}%"
    if change_pct < -10:
        return w["down"], f"price falling ({change_pct:+.0f}%)"
    return w["flat"], f"price flat ({change_pct:+.0f}%)"


def market_factor(us_pct, eu_pct):
    """(multiplier, label) for US (TCGplayer) vs EU (Cardmarket) moves over the same days.
    Cardmarket often moves first on European demand; a US-only jump is flagged too."""
    if us_pct is None or eu_pct is None:
        return 1.0, None
    if eu_pct >= 10 and us_pct <= 3:
        return 1.15, f"Cardmarket up first (EU {eu_pct:+.0f}%, US {us_pct:+.0f}%)"
    if us_pct >= 10 and eu_pct <= 3:
        return 1.0, f"US up, EU flat (US {us_pct:+.0f}%, EU {eu_pct:+.0f}%)"
    return 1.0, None


TOURNAMENT_SHARE = 0.25  # in this share of a recent event's top decks -> small boost


def tournament_factor(play):
    """(multiplier, label) from ``tournaments.card_play`` for one card: ``(top_decks, top_size, event)``."""
    if not play or not play[1] or play[0] < 2:
        return 1.0, None  # one deck is noise
    top, size, event = play
    label = f"in {top} of {size} top decks at {event}"
    return (1.1, label) if top / size >= TOURNAMENT_SHARE else (1.0, label)


CASUAL_MIN_DECKS = 50  # new Archidekt decks needed before their trend is shown
CASUAL_MIN_PTS = 2.0


def casual_label(trend):
    """Reason line from ``archidekt.card_trend`` for one card (no score weight until it's backtested)."""
    if not trend:
        return None
    share, change, n = trend
    if n < CASUAL_MIN_DECKS or change is None or change < CASUAL_MIN_PTS:
        return None
    return f"in {share:.0%} of new Archidekt decks ({change:+.1f} pts vs the 4 weeks before)"


def spec_signals(db, wl, rising=None, min_usd=0.5, max_usd=None, include_new=False, today=None, days=7,
                 out_of_print_only=False, tournament_play=None, casual_trend=None):
    """Cards gaining players while their price hasn't caught up, scarcest first.

    score = EDHREC trend (+ popularity gain over ``days`` from our own daily
    snapshots, once there are two) x supply factor x price factor. Every row
    carries its reasons, so the score is never a black box."""
    """``out_of_print_only`` keeps cards last printed over a year ago (no set still being opened)."""
    rising = rising_cards(db) if rising is None else rising
    today = today or dt.date.today().isoformat()
    if tournament_play is None:
        import tournaments
        tournament_play = tournaments.card_play(today=today)
    if casual_trend is None:
        import archidekt
        casual_trend = archidekt.card_trend(today=today)
    year_ago = (dt.date.fromisoformat(today) - dt.timedelta(days=365)).isoformat()
    _, _, pop_change = wl.popularity_change(days)
    price_change = wl.price_changes(days)
    eur_change = wl.price_changes(days, currency="eur")
    supply = db.supply([r["name"] for r in rising if r["usd"] is not None], today)
    new_cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=NEW_CARD_DAYS)).isoformat()
    rows = []
    for r in rising:
        if r["usd"] is None or r["trend"] is None or r["trend"] <= 0 or r["usd"] < min_usd:
            continue
        if max_usd is not None and r["usd"] > max_usd:
            continue
        sup = supply.get(r["name"])
        is_new = bool(sup and sup["first"] and sup["first"] >= new_cutoff)
        if is_new and not include_new:
            continue
        if out_of_print_only and not (sup and sup["last"] and sup["last"] < year_ago and not sup["upcoming"]):
            continue
        card = db.get(r["name"])
        accel = pop_change.get(r["name"])
        s_mult, s_label = supply_factor(sup, today)
        us = price_change.get(card["oracle_id"]) if card else None
        eu = eur_change.get(card["oracle_id"]) if card else None
        p_mult, p_label = price_factor(us)
        e_mult, e_label = market_factor(us, eu)
        t_mult, t_label = tournament_factor(tournament_play.get(r["name"]))
        base = r["trend"] + (max(accel, 0) * 5 if accel is not None else 0)
        reasons = [f"EDHREC trend {r['trend']:.1f}",
                   "new on the weekly list" if r["new"] else f"{r['change_pts']:+.1f} pts vs 2 years"]
        if accel is not None:
            reasons.append(f"{accel:+.2f} pts in {days} days")
        c_label = casual_label(casual_trend.get(r["name"]))
        reasons += [s_label, p_label] + ([e_label] if e_label else []) + ([t_label] if t_label else []) \
            + ([c_label] if c_label else [])
        if card and card["usd_max"] and card["usd"] and card["usd_max"] >= card["usd"] * 1.5:
            reasons.append(f"printings ${card['usd']:,.2f}-${card['usd_max']:,.2f}")
        reasons += ["new card (first printed in the last 30 days)"] if is_new else []
        rows.append({**r, "score": round(base * s_mult * p_mult * e_mult * t_mult, 1), "supply": s_label,
                     "tournament": t_label,
                     "eur": card["eur"] if card else None, "usd_max": card["usd_max"] if card else None,
                     "eur_change_pct": eu,
                     "printings": sup["printings"] if sup else None, "last_printed": sup["last"] if sup else None,
                     "reserved": bool(sup and sup["reserved"]), "price_change_pct": price_change.get(card["oracle_id"]) if card else None,
                     "pop_change_pts": accel, "new_card": is_new, "reasons": reasons})
    rows.sort(key=lambda r: -r["score"])
    return rows


def rising_commanders(limit=RADAR_COMMANDERS, week=None):
    """Commanders gaining fastest on EDHREC this week (trend score), most first."""
    week = fetch_top("commanders_week", pages=3) if week is None else week
    risers = [v for v in week if (v.get("trend_zscore") or 0) > 0]
    risers.sort(key=lambda v: -v["trend_zscore"])
    return risers[:limit]


def commander_radar(db, limit=RADAR_COMMANDERS, per_commander=8, max_usd=10.0, min_synergy=0.2,
                    commanders=None, cards_for=None, today=None):
    """For each rising commander: its cheap, high-synergy cards (the ones new
    decks for it will want), with supply facts. ``cards_for(name)`` returns
    EDHREC's cards for a commander (defaults to the cached commander page)."""
    commanders = rising_commanders(limit) if commanders is None else commanders
    cards_for = cards_for or (lambda name: edhrec_client.commander_cards([name])["cards"])
    out = []
    for c in commanders:
        try:
            cards = cards_for(c["name"])
        except edhrec_client.EdhrecError:
            continue
        picks = [x for x in cards if (x.get("synergy") or 0) >= min_synergy or x.get("high_synergy")]
        info = db.get_many([x["name"] for x in picks])
        supply = db.supply(list(info), today)
        rows = []
        for x in picks:
            card = info.get(x["name"])
            if card is None or card["usd"] is None or card["usd"] > max_usd or "Basic" in card["type_line"]:
                continue
            _, s_label = supply_factor(supply.get(x["name"]), today)
            rows.append({"name": card["name"], "synergy": x.get("synergy") or 0.0, "inclusion": x["inclusion"],
                         "usd": card["usd"], "supply": s_label,
                         "printings": supply[x["name"]]["printings"] if x["name"] in supply else None})
        rows.sort(key=lambda r: (-r["synergy"], -r["inclusion"]))
        out.append({"commander": c["name"], "trend": round(c["trend_zscore"], 1), "week_decks": c["num_decks"],
                    "cards": rows[:per_commander]})
    return out


# ---------------------------------------------------------------------------
# Price history + watch list (local SQLite)
# ---------------------------------------------------------------------------


def _day(date):
    return int(date.replace("-", ""))


def _date(day):
    s = str(day)
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


class WatchList:
    """Price snapshots and your watched cards, in ``data/watchlist.sqlite``."""

    def __init__(self, path=None):
        self.path = Path(path) if path else DATA_DIR / DB_NAME
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self):
        """Add columns that older watchlist.sqlite files don't have yet."""
        def columns(table):
            return {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
        with self.conn:
            if "eur_cents" not in columns("snapshots"):
                self.conn.execute("ALTER TABLE snapshots ADD COLUMN eur_cents INTEGER")
            if "buy_cents" not in columns("snapshots"):
                self.conn.execute("ALTER TABLE snapshots ADD COLUMN buy_cents INTEGER")
            for col in ("target_above", "target_below"):
                if col not in columns("watched"):
                    self.conn.execute(f"ALTER TABLE watched ADD COLUMN {col} REAL")

    def get_meta(self, key):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key, value):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    def set_tracked(self, oracle_ids, why):
        """Mark cards to snapshot every day whatever their price (e.g. owned cards)."""
        with self.conn:
            self.conn.executemany("INSERT OR REPLACE INTO tracked VALUES (?, ?)",
                                  [(oid, why) for oid in oracle_ids])

    def close(self):
        self.conn.close()

    # -- snapshots ---------------------------------------------------------

    def _card_id(self, oracle_id, create=True):
        row = self.conn.execute("SELECT id FROM card_ids WHERE oracle_id = ?", (oracle_id,)).fetchone()
        if row or not create:
            return row[0] if row else None
        return self.conn.execute("INSERT INTO card_ids (oracle_id) VALUES (?)", (oracle_id,)).lastrowid

    def snapshot(self, db, keep_days=KEEP_DAYS):
        """Save today's prices (dated by the Scryfall bulk file) once per date.
        Returns the date and whether a new snapshot was written."""
        date = (db.meta().get("updated_at") or dt.date.today().isoformat())[:10]
        day = _day(date)
        if self.conn.execute("SELECT 1 FROM snapshots WHERE day = ? LIMIT 1", (day,)).fetchone():
            return date, False
        always = {r[0] for r in self.conn.execute("SELECT oracle_id FROM watched UNION SELECT oracle_id FROM tracked")}
        ids = dict(self.conn.execute("SELECT oracle_id, id FROM card_ids"))
        rows = []
        with self.conn:
            for r in db.conn.execute("SELECT oracle_id, usd, eur FROM cards WHERE usd IS NOT NULL"):
                if r["usd"] < MIN_TRACK_USD and r["oracle_id"] not in always:
                    continue
                if r["oracle_id"] not in ids:
                    ids[r["oracle_id"]] = self._card_id(r["oracle_id"])
                eur = round(r["eur"] * 100) if r["eur"] is not None else None
                rows.append((day, ids[r["oracle_id"]], round(r["usd"] * 100), eur))
            self.conn.executemany("INSERT OR IGNORE INTO snapshots (day, card, cents, eur_cents) VALUES (?, ?, ?, ?)",
                                  rows)
            cutoff = _day((dt.date.fromisoformat(date) - dt.timedelta(days=keep_days)).isoformat())
            self.conn.execute(
                "DELETE FROM snapshots WHERE day < ? AND card NOT IN (SELECT c.id FROM card_ids c "
                "WHERE c.oracle_id IN (SELECT oracle_id FROM watched UNION SELECT oracle_id FROM tracked))",
                (cutoff,))
        return date, True

    def dates(self):
        return [_date(r[0]) for r in self.conn.execute("SELECT DISTINCT day FROM snapshots ORDER BY day")]

    def _compare_dates(self, days):
        """(old, new) snapshot dates about ``days`` apart, or None if history is too short."""
        dates = self.dates()
        if len(dates) < 2:
            return None
        new = dates[-1]
        target = (dt.date.fromisoformat(new) - dt.timedelta(days=days)).isoformat()
        older = [d for d in dates[:-1] if d <= target]
        return (older[-1] if older else dates[0]), new

    def price_risers(self, db, days=7, min_usd=1.0, limit=50):
        """Cards whose price rose most over ``days`` (or the longest history so far).

        Returns ``{"from", "to", "rows": [{name, old, new, change_pct, change_usd, ...}]}``;
        ``from``/``to`` are None while there is only one snapshot."""
        span = self._compare_dates(days)
        if span is None:
            return {"from": None, "to": None, "rows": []}
        old_date, new_date = span
        pairs = self.conn.execute(
            "SELECT c.oracle_id, o.cents AS old, n.cents AS new FROM snapshots n "
            "JOIN snapshots o ON o.card = n.card AND o.day = ? "
            "JOIN card_ids c ON c.id = n.card "
            "WHERE n.day = ? AND n.cents >= ? AND n.cents > o.cents",
            (_day(old_date), _day(new_date), round(min_usd * 100)),
        ).fetchall()
        rows = []
        for p in pairs:
            card = db.conn.execute("SELECT name, color_identity, type_line FROM cards WHERE oracle_id = ?",
                                   (p["oracle_id"],)).fetchone()
            if card is None:
                continue
            old, new = p["old"] / 100, p["new"] / 100
            rows.append({"name": card["name"], "old": old, "new": new, "change_usd": round(new - old, 2),
                         "change_pct": round((new - old) / old * 100, 1),
                         "color_identity": card["color_identity"], "type_line": card["type_line"]})
        rows.sort(key=lambda r: (-r["change_pct"], -r["change_usd"]))
        return {"from": old_date, "to": new_date, "rows": rows[:limit]}

    def buylist(self, oracle_ids):
        """``{oracle_id: (usd, date)}``: each card's latest Card Kingdom buylist offer."""
        out = {}
        for oid in dict.fromkeys(oracle_ids):
            row = self.conn.execute(
                "SELECT s.day, s.buy_cents FROM snapshots s JOIN card_ids c ON c.id = s.card "
                "WHERE c.oracle_id = ? AND s.buy_cents IS NOT NULL ORDER BY s.day DESC LIMIT 1", (oid,)).fetchone()
            if row:
                out[oid] = (row[1] / 100, _date(row[0]))
        return out

    def history(self, oracle_id):
        """[(date, usd)] for one card, oldest first."""
        return [(_date(r[0]), r[1] / 100) for r in self.conn.execute(
            "SELECT s.day, s.cents FROM snapshots s JOIN card_ids c ON c.id = s.card "
            "WHERE c.oracle_id = ? ORDER BY s.day", (oracle_id,))]

    # -- EDHREC popularity history -------------------------------------------

    def snapshot_edhrec(self, week, date=None, keep_days=KEEP_DAYS):
        """Save this week's EDHREC top list once per (local) date. Returns True if saved."""
        date = date or dt.date.today().isoformat()
        day = _day(date)
        if self.conn.execute("SELECT 1 FROM edhrec_days WHERE day = ? LIMIT 1", (day,)).fetchone():
            return False
        ids = dict(self.conn.execute("SELECT name, id FROM edhrec_names"))
        with self.conn:
            rows = []
            for v in week:
                if v["name"] not in ids:
                    ids[v["name"]] = self.conn.execute("INSERT INTO edhrec_names (name) VALUES (?)",
                                                       (v["name"],)).lastrowid
                trend = None if v.get("trend_zscore") is None else round(v["trend_zscore"] * 1000)
                rows.append((day, ids[v["name"]], v["num_decks"], v["potential_decks"], trend))
            self.conn.executemany("INSERT OR IGNORE INTO edhrec_days VALUES (?, ?, ?, ?, ?)", rows)
            cutoff = _day((dt.date.fromisoformat(date) - dt.timedelta(days=keep_days)).isoformat())
            self.conn.execute("DELETE FROM edhrec_days WHERE day < ?", (cutoff,))
        return True

    def edhrec_dates(self):
        return [_date(r[0]) for r in self.conn.execute("SELECT DISTINCT day FROM edhrec_days ORDER BY day")]

    def popularity_change(self, days=7):
        """``(from_date, to_date, {name: change in inclusion points})`` between the latest
        EDHREC snapshot and the one about ``days`` earlier; (None, None, {}) until two exist."""
        dates = self.edhrec_dates()
        if len(dates) < 2:
            return None, None, {}
        new = dates[-1]
        target = (dt.date.fromisoformat(new) - dt.timedelta(days=days)).isoformat()
        old = ([d for d in dates[:-1] if d <= target] or [dates[0]])[-1]
        rows = self.conn.execute(
            "SELECT n.name, a.decks AS od, a.potential AS op, b.decks AS nd, b.potential AS np "
            "FROM edhrec_days b JOIN edhrec_days a ON a.name = b.name AND a.day = ? "
            "JOIN edhrec_names n ON n.id = b.name WHERE b.day = ?", (_day(old), _day(new))).fetchall()
        change = {r["name"]: round((r["nd"] / r["np"] - r["od"] / r["op"]) * 100, 2)
                  for r in rows if r["np"] and r["op"]}
        return old, new, change

    def price_changes(self, days=7, currency="usd"):
        """``{oracle_id: % change}`` over about ``days`` (or the history so far); {} with one
        snapshot. ``currency`` "eur" compares Cardmarket prices instead."""
        span = self._compare_dates(days)
        if span is None:
            return {}
        col = "eur_cents" if currency == "eur" else "cents"
        rows = self.conn.execute(
            f"SELECT c.oracle_id, o.{col} AS old, n.{col} AS new FROM snapshots n "
            "JOIN snapshots o ON o.card = n.card AND o.day = ? JOIN card_ids c ON c.id = n.card "
            f"WHERE n.day = ? AND o.{col} > 0 AND n.{col} IS NOT NULL", (_day(span[0]), _day(span[1]))).fetchall()
        return {r["oracle_id"]: round((r["new"] - r["old"]) / r["old"] * 100, 1) for r in rows}

    # -- watched cards -----------------------------------------------------

    def add(self, db, name, note=""):
        """Watch a card (exact or fuzzy name). Returns the exact name."""
        card = db.get(name) or (db.get(db.find_name(name)) if db.find_name(name) else None)
        if card is None:
            raise LookupError(f"No card matched {name!r}.")
        with self.conn:
            self.conn.execute(
                "INSERT INTO watched (name, oracle_id, added_at, usd_when_added, note) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET note = excluded.note",
                (card["name"], card["oracle_id"], dt.date.today().isoformat(), card["usd"], note),
            )
            if card["usd"] is not None:  # start its history now, even if it's under MIN_TRACK_USD
                for date in self.dates()[-1:]:
                    self.conn.execute("INSERT OR IGNORE INTO snapshots (day, card, cents, eur_cents) VALUES (?, ?, ?, ?)",
                                      (_day(date), self._card_id(card["oracle_id"]), round(card["usd"] * 100),
                                       round(card["eur"] * 100) if card["eur"] is not None else None))
        return card["name"]

    def set_target(self, name, above=None, below=None):
        """Price alerts for a watched card (None clears one). Returns False if not watched."""
        with self.conn:
            return self.conn.execute("UPDATE watched SET target_above = ?, target_below = ? WHERE name = ?",
                                     (above, below, name)).rowcount > 0

    def target_hits(self, db):
        """Watched cards whose price reached a target: ``[{name, usd, target, direction}]``."""
        hits = []
        for w in self.conn.execute("SELECT * FROM watched WHERE target_above IS NOT NULL OR target_below IS NOT NULL"):
            card = db.get(w["name"])
            if card is None or card["usd"] is None:
                continue
            if w["target_above"] is not None and card["usd"] >= w["target_above"]:
                hits.append({"name": w["name"], "usd": card["usd"], "target": w["target_above"], "direction": "above"})
            if w["target_below"] is not None and card["usd"] <= w["target_below"]:
                hits.append({"name": w["name"], "usd": card["usd"], "target": w["target_below"], "direction": "below"})
        return hits

    def remove(self, name):
        with self.conn:
            return self.conn.execute("DELETE FROM watched WHERE name = ?", (name,)).rowcount > 0

    def is_watched(self, name):
        return self.conn.execute("SELECT 1 FROM watched WHERE name = ?", (name,)).fetchone() is not None

    def watched(self, db, rising=None):
        """Watched cards with price now, change since added / 7 / 30 days, and
        this week's EDHREC trend when the card is in the week's top list."""
        by_name = {r["name"]: r for r in rising or []}
        out = []
        for w in self.conn.execute("SELECT * FROM watched ORDER BY added_at DESC, name"):
            card = db.get(w["name"])
            hist = self.history(w["oracle_id"])
            now = card["usd"] if card else None

            def change(days):
                if not hist or now is None:
                    return None
                target = (dt.date.fromisoformat(hist[-1][0]) - dt.timedelta(days=days)).isoformat()
                past = [usd for date, usd in hist if date <= target]
                return round((now - past[-1]) / past[-1] * 100, 1) if past and past[-1] else None

            trend = by_name.get(w["name"])
            out.append({
                "name": w["name"], "note": w["note"], "added_at": w["added_at"], "usd": now,
                "target_above": w["target_above"], "target_below": w["target_below"],
                "usd_when_added": w["usd_when_added"],
                "since_added_pct": round((now - w["usd_when_added"]) / w["usd_when_added"] * 100, 1)
                if now is not None and w["usd_when_added"] else None,
                "change_7d_pct": change(7), "change_30d_pct": change(30),
                "trend": trend["trend"] if trend else None,
                "week_inclusion": trend["week_inclusion"] if trend else None,
                "history": hist,
            })
        return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _pct(value):
    return "n/a" if value is None else f"{value:+.1f}%"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rising cards (EDHREC), price risers and your watch list.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshot", help="save today's prices and EDHREC popularity (run daily, e.g. from cron)")
    p_spec = sub.add_parser("spec", help="popular, still cheap, short supply")
    p_spec.add_argument("--min-usd", type=float, default=0.5)
    p_spec.add_argument("--max-usd", type=float)
    p_spec.add_argument("--limit", type=int, default=25)
    p_spec.add_argument("--out-of-print", action="store_true", help="only cards last printed over a year ago")
    p_radar = sub.add_parser("radar", help="rising commanders and their cheap high-synergy cards")
    p_radar.add_argument("--commanders", type=int, default=5)
    p_rising = sub.add_parser("rising", help="cards rising on EDHREC this week")
    p_rising.add_argument("--limit", type=int, default=25)
    p_prices = sub.add_parser("prices", help="cards whose price rose")
    p_prices.add_argument("--days", type=int, default=7)
    p_prices.add_argument("--min-usd", type=float, default=1.0)
    p_prices.add_argument("--limit", type=int, default=25)
    p_add = sub.add_parser("add", help="watch a card")
    p_add.add_argument("name")
    p_add.add_argument("--note", default="")
    p_remove = sub.add_parser("remove", help="stop watching a card")
    p_remove.add_argument("name")
    sub.add_parser("list", help="your watched cards")
    args = parser.parse_args(argv)

    # Check Scryfall every few hours (not the app's 24 h), so a new day's prices are
    # snapshotted soon after Scryfall publishes them instead of up to a day late.
    db = card_db.open_db(max_age_hours=SCRYFALL_CHECK_HOURS, log=lambda m: print(m, file=sys.stderr))
    wl = WatchList()
    try:
        date, new = wl.snapshot(db)  # every command keeps history going
        if args.command == "snapshot":
            import alerts
            import portfolio
            portfolio.track_owned(db, wl)  # owned cards are snapshotted from now on, however cheap
            print(f"Price snapshot for {date}: {'saved' if new else 'already saved'} "
                  f"({len(wl.dates())} days of history).")
            try:
                saved = wl.snapshot_edhrec(fetch_top("week"))
                print(f"EDHREC popularity snapshot: {'saved' if saved else 'already saved'} "
                      f"({len(wl.edhrec_dates())} days of history).")
            except edhrec_client.EdhrecError as exc:
                print(f"EDHREC popularity snapshot skipped: {exc}")
            if wl.get_meta("digest_date") != date:  # one digest per new price date
                from dotenv import load_dotenv
                from scan_binder import ENV_PATH
                load_dotenv(ENV_PATH)
                try:
                    import price_history
                    print(f"MTGJSON prices + buylist stored for {price_history.update_buylist(db, wl, log=print):,} cards.")
                except price_history.HistoryError as exc:
                    print(f"Buylist update skipped: {exc}")
                try:
                    import archidekt
                    a = archidekt.Archidekt()
                    try:
                        if a.get_meta("sampled_on") != dt.date.today().isoformat():
                            a.sample(max_new=150, log=print)
                            a.set_meta("sampled_on", dt.date.today().isoformat())
                    finally:
                        a.close()
                except Exception as exc:  # network trouble shouldn't stop the digest
                    print(f"Archidekt sample skipped: {exc}")
                try:
                    import tournaments
                    names = tournaments.auto_import(log=print)
                    if names:
                        print("Tournaments imported: " + "; ".join(names))
                except Exception as exc:
                    print(f"Tournament auto-import skipped: {exc}")
                try:
                    import scryfall_tags
                    if scryfall_tags.is_stale():
                        scryfall_tags.refresh(log=print)
                        card_db.ensure_db(log=print, rebuild=True)
                except Exception as exc:
                    print(f"Scryfall tag refresh skipped: {exc}")
                path, _ = alerts.daily_digest(db, wl, date, log=print)
                print(f"Digest written to {path}.")
        elif args.command == "spec":
            for r in spec_signals(db, wl, min_usd=args.min_usd, max_usd=args.max_usd,
                                  out_of_print_only=args.out_of_print)[: args.limit]:
                print(f"{r['score']:>6} {r['name']} ${r['usd']:.2f} - " + "; ".join(r["reasons"]))
        elif args.command == "radar":
            for c in commander_radar(db, limit=args.commanders):
                print(f"\n{c['commander']} (trend {c['trend']}, {c['week_decks']} decks this week)")
                for x in c["cards"]:
                    print(f"  {x['synergy']:+.0%} synergy  ${x['usd']:.2f}  {x['name']} ({x['supply']})")
        elif args.command == "rising":
            for r in rising_cards(db)[: args.limit]:
                change = "new this week" if r["new"] else f"{r['change_pts']:+.1f} pts vs 2 years"
                price = f"${r['usd']:.2f}" if r["usd"] is not None else "n/a"
                print(f"{r['trend']:>6} {r['name']} - {r['week_inclusion']:.1%} of decks this week ({change}), {price}")
        elif args.command == "prices":
            found = wl.price_risers(db, args.days, args.min_usd, args.limit)
            if found["from"] is None:
                print("Only one day of price history so far; run `watchlist.py snapshot` daily.")
            for r in found["rows"]:
                print(f"{r['change_pct']:+6.1f}% {r['name']}: ${r['old']:.2f} -> ${r['new']:.2f}")
            if found["from"]:
                print(f"({found['from']} -> {found['to']})")
        elif args.command == "add":
            print(f"Watching {wl.add(db, args.name, args.note)}.")
        elif args.command == "remove":
            print("Removed." if wl.remove(args.name) else f"{args.name} wasn't on your list.")
        elif args.command == "list":
            for w in wl.watched(db):
                price = f"${w['usd']:.2f}" if w["usd"] is not None else "n/a"
                print(f"{w['name']}: {price} (7d {_pct(w['change_7d_pct'])}, 30d {_pct(w['change_30d_pct'])}, "
                      f"since added {_pct(w['since_added_pct'])})")
    except (LookupError, edhrec_client.EdhrecError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        wl.close()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
