"""Casual meta from Archidekt: what people are building right now, by bracket.

EDHREC averages years of decks; Archidekt's public API lists the newest
Commander decks as they are made, many tagged with a bracket (1-5). Once a
day this samples the newest complete decks (99+ cards; brand-new empty decks
are skipped), stores each deck's cards and commander in
``data/archidekt.sqlite``, and compares the last 7 days with the 28 before:
which cards and commanders are showing up in more new decks.

Polite: 1 request per second, a capped number of decks per day, each deck
fetched once. Archidekt's card records carry the Scryfall oracle id, so cards
match ours exactly (and its salt score is kept too).

CLI:
    python archidekt.py sample --max 150      # fetch new decks (the daily job runs this)
    python archidekt.py trends --bracket 2
"""

import argparse
import datetime as dt
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://archidekt.com/api/decks"
HEADERS = {"User-Agent": "commander-deck-builder/0.1 (personal research)", "Accept": "application/json"}
DB_PATH = Path(__file__).parent / "data" / "archidekt.sqlite"
MIN_INTERVAL_S = 1.0
RETRIES = 2
PAGE_SIZE = 50
MIN_DECK_SIZE = 99
BASICS = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS decks (
    id INTEGER PRIMARY KEY,
    created TEXT NOT NULL,        -- YYYY-MM-DD
    bracket INTEGER,              -- 1-5 when the owner set one
    commanders TEXT NOT NULL,     -- " / "-joined names
    name TEXT,
    sampled_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deck_cards (
    deck_id INTEGER NOT NULL,
    oracle_id TEXT NOT NULL,
    name TEXT NOT NULL,
    qty INTEGER NOT NULL,
    PRIMARY KEY (deck_id, oracle_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_deck_cards_oracle ON deck_cards(oracle_id);
CREATE TABLE IF NOT EXISTS salt (oracle_id TEXT PRIMARY KEY, name TEXT, salt REAL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

_last = [0.0]


class ArchidektError(Exception):
    """Archidekt unreachable or answered in an unexpected format."""


def _get(url):
    for attempt in range(RETRIES + 1):
        wait = _last[0] + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if (exc.code != 429 and exc.code < 500) or attempt == RETRIES:
                raise ArchidektError(f"Archidekt returned HTTP {exc.code}.") from exc
            time.sleep(10 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == RETRIES:
                raise ArchidektError(f"Could not reach Archidekt: {exc}") from exc
            time.sleep(5 * (attempt + 1))


def parse_deck(data):
    """Archidekt deck JSON -> ``{id, created, bracket, name, commanders, cards: {oracle_id: (name, qty)},
    salt: {oracle_id: (name, salt)}}``. Maybeboard / sideboard categories are left out."""
    excluded = {c["name"] for c in data.get("categories") or [] if not c.get("includedInDeck", True)}
    cards, salt, commanders = {}, {}, []
    for entry in data.get("cards") or []:
        cats = entry.get("categories") or []
        if any(c in excluded for c in cats):
            continue
        oracle = (entry.get("card") or {}).get("oracleCard") or {}
        oid, name = oracle.get("uid"), oracle.get("name")
        if not oid or not name:
            continue
        if "Commander" in cats:
            commanders.append(name)
        qty = entry.get("quantity") or 1
        prev = cards.get(oid, (name, 0))[1]
        cards[oid] = (name, prev + qty)
        if oracle.get("salt") is not None:
            salt[oid] = (name, oracle["salt"])
    return {"id": data.get("id"), "created": (data.get("createdAt") or "")[:10], "bracket": data.get("edhBracket"),
            "name": data.get("name"), "commanders": commanders, "cards": cards, "salt": salt}


class Archidekt:
    def __init__(self, path=None):
        self.path = Path(path) if path else DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    def get_meta(self, key):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key, value):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    def known(self, deck_id):
        return self.conn.execute("SELECT 1 FROM decks WHERE id = ?", (deck_id,)).fetchone() is not None

    def save(self, deck, sampled_on=None):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO decks VALUES (?, ?, ?, ?, ?, ?)",
                              (deck["id"], deck["created"], deck["bracket"], " / ".join(deck["commanders"]),
                               deck["name"], sampled_on or dt.date.today().isoformat()))
            self.conn.execute("DELETE FROM deck_cards WHERE deck_id = ?", (deck["id"],))
            self.conn.executemany("INSERT INTO deck_cards VALUES (?, ?, ?, ?)",
                                  [(deck["id"], oid, n, q) for oid, (n, q) in deck["cards"].items()])
            self.conn.executemany("INSERT OR REPLACE INTO salt VALUES (?, ?, ?)",
                                  [(oid, n, s) for oid, (n, s) in deck["salt"].items()])

    def sample(self, max_new=150, max_pages=12, get=None, log=print):
        """Fetch up to ``max_new`` new complete decks from the newest public Commander decks."""
        get = get or _get
        added = 0
        for page in range(1, max_pages + 1):
            query = urllib.parse.urlencode({"deckFormat": 3, "orderBy": "-createdAt", "pageSize": PAGE_SIZE,
                                            "page": page})
            listing = get(f"{API}/v3/?{query}")
            if not listing or not listing.get("results"):
                break
            for d in listing["results"]:
                if added >= max_new:
                    log(f"Archidekt: {added} new decks saved ({self.count()} total).")
                    return added
                if (d.get("size") or 0) < MIN_DECK_SIZE or d.get("private") or self.known(d["id"]):
                    continue
                data = get(f"{API}/{d['id']}/")
                if not data:
                    continue
                deck = parse_deck(data)
                if not deck["commanders"] or sum(q for _, q in deck["cards"].values()) < MIN_DECK_SIZE:
                    continue
                self.save(deck)
                added += 1
            if not listing.get("next"):
                break
        log(f"Archidekt: {added} new decks saved ({self.count()} total).")
        return added

    def count(self, bracket=None):
        sql, args = "SELECT COUNT(*) FROM decks", ()
        if bracket:
            sql, args = sql + " WHERE bracket = ?", (bracket,)
        return self.conn.execute(sql, args).fetchone()[0]

    def salt(self, oracle_id):
        row = self.conn.execute("SELECT salt FROM salt WHERE oracle_id = ?", (oracle_id,)).fetchone()
        return row[0] if row else None

    # -- trends ----------------------------------------------------------------

    def _window(self, start, end, bracket):
        sql = "SELECT id FROM decks WHERE created >= ? AND created < ?"
        args = [start, end]
        if bracket:
            sql += " AND bracket = ?"
            args.append(bracket)
        return [r[0] for r in self.conn.execute(sql, args)]

    def trends(self, days=7, base_days=28, bracket=None, min_decks=3, today=None):
        """Cards in more new decks lately: share of decks in the last ``days`` vs the
        ``base_days`` before. ``{"recent_decks", "base_decks", "cards": [...], "commanders": [...]}``."""
        today = dt.date.fromisoformat(today) if today else dt.date.today()
        cut = (today - dt.timedelta(days=days - 1)).isoformat()
        start = (today - dt.timedelta(days=days - 1 + base_days)).isoformat()
        end = (today + dt.timedelta(days=1)).isoformat()
        recent, base = self._window(cut, end, bracket), self._window(start, cut, bracket)

        def shares(ids):
            if not ids:
                return {}, {}
            marks = ",".join("?" * len(ids))
            rows = self.conn.execute(
                f"SELECT oracle_id, name, COUNT(*) FROM deck_cards WHERE deck_id IN ({marks}) GROUP BY oracle_id",
                ids).fetchall()
            return {r[0]: r[2] for r in rows}, {r[0]: r[1] for r in rows}

        r_counts, names = shares(recent)
        b_counts, b_names = shares(base)
        names = {**b_names, **names}
        cards = []
        for oid, n in r_counts.items():
            if n < min_decks or names[oid] in BASICS:
                continue
            share = n / len(recent)
            before = b_counts.get(oid, 0) / len(base) if base else None
            cards.append({"oracle_id": oid, "name": names[oid], "decks": n, "share": share, "base_share": before,
                          "change_pts": round((share - before) * 100, 1) if before is not None else None})
        cards.sort(key=lambda c: (c["change_pts"] is None, -(c["change_pts"] or 0), -c["share"]))

        def commanders(ids):
            if not ids:
                return {}
            marks = ",".join("?" * len(ids))
            return {r[0]: r[1] for r in self.conn.execute(
                f"SELECT commanders, COUNT(*) FROM decks WHERE id IN ({marks}) GROUP BY commanders", ids)}
        rc, bc = commanders(recent), commanders(base)
        cmd = sorted(({"commander": c, "decks": n, "base_decks": bc.get(c, 0)} for c, n in rc.items()),
                     key=lambda c: (-c["decks"], c["commander"]))
        return {"recent_decks": len(recent), "base_decks": len(base), "cards": cards, "commanders": cmd,
                "bracket": bracket, "from": cut, "base_from": start}

    def brackets(self):
        return {r[0]: r[1] for r in self.conn.execute("SELECT bracket, COUNT(*) FROM decks GROUP BY bracket")}


def card_trend(today=None, path=None):
    """``{card name: (share now, change pts or None, recent decks)}`` for the watch list."""
    a = Archidekt(path)
    try:
        t = a.trends(today=today)
    finally:
        a.close()
    return {c["name"]: (c["share"], c["change_pts"], t["recent_decks"]) for c in t["cards"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Casual Commander meta from Archidekt's newest decks.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_s = sub.add_parser("sample", help="fetch new decks (1 request/second)")
    p_s.add_argument("--max", type=int, default=150)
    p_t = sub.add_parser("trends", help="cards and commanders rising in new decks")
    p_t.add_argument("--bracket", type=int, choices=range(1, 6))
    p_t.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    a = Archidekt()
    try:
        if args.command == "sample":
            a.sample(max_new=args.max, log=lambda m: print(m))
        else:
            t = a.trends(bracket=args.bracket)
            print(f"{t['recent_decks']} decks since {t['from']} vs {t['base_decks']} in the 28 days before"
                  + (f" (bracket {args.bracket})" if args.bracket else "") + ":")
            for c in t["cards"][: args.limit]:
                change = "n/a" if c["change_pts"] is None else f"{c['change_pts']:+.1f} pts"
                print(f"  {c['share']:6.1%} of new decks ({change})  {c['name']}")
            print("Commanders:", ", ".join(f"{c['commander']} ({c['decks']})" for c in t["commanders"][:8]))
    except ArchidektError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        a.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
