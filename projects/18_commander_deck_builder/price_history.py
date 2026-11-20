"""Backfill ~90 days of past prices (and Card Kingdom buylist prices) from MTGJSON.

MTGJSON (mtgjson.com, free) publishes ``AllPrices.json.gz``: about 90 days of
daily prices per printing from TCGplayer, Cardmarket and Card Kingdom (retail
and buylist). Its printings use MTGJSON ids, mapped to our cards through
``AllIdentifiers.json.gz`` (Scryfall oracle id, promo flag).

Both files are gigabytes once unzipped, so they are read as a stream, one
printing at a time, with the standard library (no extra package). Downloads
are cached in ``data/cache/mtgjson`` and refreshed when MTGJSON's daily build
is newer.

Per card and day it stores the cheapest regular (non-promo, non-foil)
TCGplayer price, the Card Kingdom buylist offer for that same printing (what a
store pays) and the cheapest regular Cardmarket price. **MTGJSON is the price
history's one source** (it replaces the Scryfall snapshot for any day it
covers, and the daily job adds each new day from the small "today" file):
the two sources can pick different printings as "cheapest", so mixing them
made fake jumps (Nicol Bolas, Dragon-God: $21 on MTGJSON, $13.72 on Scryfall's
alternate-art printing). Scryfall stays the fallback for cards MTGJSON lacks.

CLI:
    python price_history.py            # download if needed, then backfill
    python price_history.py --today    # just today's buylist prices (5.6 MB)
"""

import argparse
import datetime as dt
import gzip
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import card_db
import watchlist

BASE = "https://mtgjson.com/api/v5"
HEADERS = {"User-Agent": "commander-deck-builder/0.1"}
CACHE_DIR = Path(__file__).parent / "data" / "cache" / "mtgjson"
CHUNK = 1 << 20
_KEY = re.compile(r'\s*,?\s*"([^"]+)"\s*:\s*')


class HistoryError(Exception):
    """MTGJSON unreachable or its files in an unexpected format."""


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def mtgjson_date():
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{BASE}/Meta.json", headers=HEADERS), timeout=30) as r:
            return json.load(r)["data"]["date"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise HistoryError(f"Could not read MTGJSON's build date: {exc}") from exc


def download(name, cache_dir=CACHE_DIR, build_date=None, log=print):
    """Fetch ``name`` into the cache unless the cached copy is from this build."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path, stamp = cache_dir / name, cache_dir / f"{name}.date"
    build_date = build_date or mtgjson_date()
    if path.exists() and stamp.exists() and stamp.read_text().strip() == build_date:
        return path
    log(f"Downloading MTGJSON {name}...")
    tmp = path.with_suffix(path.suffix + ".part")
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{BASE}/{name}", headers=HEADERS), timeout=120) as r, \
                tmp.open("wb") as out:
            while block := r.read(CHUNK):
                out.write(block)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise HistoryError(f"Could not download {name}: {exc}") from exc
    tmp.replace(path)
    stamp.write_text(build_date)
    return path


# ---------------------------------------------------------------------------
# Streaming reader for {"meta": {...}, "data": {"<id>": {...}, ...}}
# ---------------------------------------------------------------------------


def stream_data(fileobj):
    """Yield ``(key, value)`` for each entry of the top-level ``"data"`` object,
    reading text in chunks so the whole file is never in memory."""
    decoder = json.JSONDecoder()
    buf, pos, eof = "", 0, False

    def more():
        nonlocal buf, pos, eof
        block = fileobj.read(CHUNK)
        if not block:
            eof = True
        buf = buf[pos:] + block
        pos = 0

    while True:  # find the start of "data": {
        i = buf.find('"data"', pos)
        if i >= 0:
            j = buf.find("{", i)
            if j >= 0:
                pos = j + 1
                break
        if eof:
            raise HistoryError('No "data" object found (MTGJSON format changed?).')
        more()
    while True:
        while True:  # next key, or the closing brace
            stripped = buf[pos:].lstrip()
            if stripped.startswith("}"):
                return
            m = _KEY.match(buf, pos)
            if m and m.end() < len(buf):
                key, start = m.group(1), m.end()
                break
            if eof:
                raise HistoryError("File ended inside the data object.")
            more()
        while True:  # its value
            try:
                value, end = decoder.raw_decode(buf, start)
                break
            except json.JSONDecodeError:
                if eof:
                    raise HistoryError(f"Could not read the entry for {key}.")
                offset = start - pos
                more()
                start = pos + offset
        pos = end
        yield key, value


def open_gz(path):
    return gzip.open(path, "rt", encoding="utf-8")


# ---------------------------------------------------------------------------
# Map MTGJSON ids -> our cards, then backfill
# ---------------------------------------------------------------------------


def id_map(identifiers_path, wanted):
    """``{mtgjson uuid: oracle_id}`` for regular paper printings of cards in ``wanted``."""
    out = {}
    with open_gz(identifiers_path) as f:
        for uuid, card in stream_data(f):
            oid = (card.get("identifiers") or {}).get("scryfallOracleId")
            if oid not in wanted or card.get("isPromo") or card.get("isOnlineOnly"):
                continue
            if "paper" not in (card.get("availability") or ["paper"]):
                continue
            out[uuid] = oid
    return out


def daily_prices(prices_path, mapping):
    """``{(oracle_id, date): (usd, buylist_usd or None, eur or None)}``: per card and day, the
    cheapest regular TCGplayer price, Card Kingdom's buylist for that printing, and the
    cheapest regular Cardmarket price."""
    best, eur = {}, {}
    with open_gz(prices_path) as f:
        for uuid, entry in stream_data(f):
            oid = mapping.get(uuid)
            if oid is None:
                continue
            paper = entry.get("paper") or {}
            retail = ((paper.get("tcgplayer") or {}).get("retail") or {}).get("normal") or {}
            buy = ((paper.get("cardkingdom") or {}).get("buylist") or {}).get("normal") or {}
            cm = ((paper.get("cardmarket") or {}).get("retail") or {}).get("normal") or {}
            for date, usd in retail.items():
                if usd is None or usd <= 0:
                    continue
                key = (oid, date)
                if key not in best or usd < best[key][0]:
                    best[key] = (usd, buy.get(date))
            for date, e in cm.items():
                if e and ((oid, date) not in eur or e < eur[(oid, date)]):
                    eur[(oid, date)] = e
    return {k: (usd, b, eur.get(k)) for k, (usd, b) in best.items()}


_UPSERT = (
    "INSERT INTO snapshots (day, card, cents, eur_cents, buy_cents) VALUES (?, ?, ?, ?, ?) "
    "ON CONFLICT(day, card) DO UPDATE SET cents = excluded.cents, "
    "eur_cents = COALESCE(excluded.eur_cents, eur_cents), buy_cents = COALESCE(excluded.buy_cents, buy_cents)")


def _store(wl, prices):
    """Write ``daily_prices`` output into the watch-list history (MTGJSON wins)."""
    ids = dict(wl.conn.execute("SELECT oracle_id, id FROM card_ids"))
    rows = []
    for (oid, date), (usd, buy, eur) in prices.items():
        if oid not in ids:
            ids[oid] = wl._card_id(oid)
        rows.append((watchlist._day(date), ids[oid], round(usd * 100),
                     round(eur * 100) if eur else None, round(buy * 100) if buy else None))
    before = wl.conn.total_changes
    wl.conn.executemany(_UPSERT, rows)
    return wl.conn.total_changes - before


def backfill(db, wl, prices_path, identifiers_path, log=print):
    """Add past days to the watch-list price history. Returns ``{"days", "rows", "from", "to"}``."""
    always = {r[0] for r in wl.conn.execute("SELECT oracle_id FROM watched UNION SELECT oracle_id FROM tracked")}
    wanted = {r["oracle_id"] for r in db.conn.execute("SELECT oracle_id, usd FROM cards WHERE usd IS NOT NULL")
              if r["usd"] >= watchlist.MIN_TRACK_USD} | always
    log(f"Mapping MTGJSON printings for {len(wanted):,} cards...")
    mapping = id_map(identifiers_path, wanted)
    log(f"Reading ~90 days of prices for {len(mapping):,} printings...")
    prices = daily_prices(prices_path, mapping)
    with wl.conn:
        added = _store(wl, prices)
    dates = sorted({d for _, d in prices})
    wl.set_meta("backfilled", f"{dates[0]}..{dates[-1]}" if dates else "")
    return {"days": len(dates), "rows": added, "from": dates[0] if dates else None,
            "to": dates[-1] if dates else None}


MAP_MAX_AGE_DAYS = 7


def cached_id_map(db, cache_dir=CACHE_DIR, build_date=None, log=print):
    """The MTGJSON id -> oracle id map for every card, kept as a small JSON file and
    rebuilt (one 237 MB download) only when it's over ``MAP_MAX_AGE_DAYS`` old, so
    the daily buylist update downloads just the 5.6 MB "today" file."""
    path = Path(cache_dir) / "id_map.json"
    if path.exists() and time.time() - path.stat().st_mtime < MAP_MAX_AGE_DAYS * 86400:
        return json.loads(path.read_text())
    ids = download("AllIdentifiers.json.gz", cache_dir, build_date, log)
    mapping = id_map(ids, {r[0] for r in db.conn.execute("SELECT oracle_id FROM cards")})
    path.write_text(json.dumps(mapping))
    return mapping


def buylist_today(db, wl, today_path, mapping, log=print):
    """Add today's MTGJSON prices (TCGplayer, Card Kingdom buylist, Cardmarket) from the
    small AllPricesToday file, for cards the history tracks. Returns rows written."""
    tracked = {r[0] for r in wl.conn.execute("SELECT oracle_id FROM card_ids")}
    prices = {k: v for k, v in daily_prices(today_path, mapping).items() if k[0] in tracked}
    with wl.conn:
        return _store(wl, prices)


def update_buylist(db, wl, log=print):
    """Daily step (called by the snapshot job): today's MTGJSON prices and buylist, small download."""
    build = mtgjson_date()
    mapping = cached_id_map(db, build_date=build, log=log)
    return buylist_today(db, wl, download("AllPricesToday.json.gz", build_date=build, log=log), mapping, log)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backfill ~90 days of prices from MTGJSON.")
    parser.add_argument("--today", action="store_true", help="only today's buylist prices (small download)")
    args = parser.parse_args(argv)
    t0 = time.time()
    db = card_db.open_db(log=lambda m: print(m, file=sys.stderr))
    wl = watchlist.WatchList()
    try:
        build = mtgjson_date()
        if args.today:
            print(f"Today's MTGJSON prices stored for {update_buylist(db, wl):,} cards.")
        else:
            ids = download("AllIdentifiers.json.gz", build_date=build)
            res = backfill(db, wl, download("AllPrices.json.gz", build_date=build), ids)
            print(f"Backfilled {res['rows']:,} card-days over {res['days']} days ({res['from']} to {res['to']}); "
                  f"price history now spans {len(wl.dates())} days. ({time.time() - t0:.0f} s)")
    except HistoryError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        wl.close()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
