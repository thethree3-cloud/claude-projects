"""Sets: look up a set (Star Trek, Marvel's Spider-Man...) and its cards by value.

Set facts and symbols come from Scryfall's set list (one request, cached for
a week): name, code, release date, type, symbol (SVG), and the parent set, so
a release's main set, Commander decks and promos group together. Card prices
come from the card database's printings table (every printing, from the
daily Scryfall file), so each row is that set's printing, priced as that
printing.

There is no sales-volume data in any free source, so "top" means most
valuable; the other sort is most played in Commander (EDHREC rank). Sealed
product (booster box) prices aren't in the data either.

CLI:
    python sets.py "star trek"           # find sets
    python sets.py trk --limit 15        # most valuable cards in a set
"""

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import card_db

API = "https://api.scryfall.com/sets"
HEADERS = {"User-Agent": "commander-deck-builder/0.1", "Accept": "application/json"}
CACHE = Path(__file__).parent / "data" / "cache" / "scryfall_sets.json"
MAX_AGE_S = 7 * 86400
HIDDEN_TYPES = {"token", "memorabilia", "minigame", "vanguard", "treasure_chest"}  # not playable cards


class SetError(Exception):
    """Scryfall's set list unreachable or unexpected."""


def fetch_sets(cache=CACHE, get=None):
    """``{code: {...}}`` for every set (Scryfall), cached for a week."""
    cache = Path(cache)
    if cache.exists() and time.time() - cache.stat().st_mtime < MAX_AGE_S:
        return json.loads(cache.read_text())
    if get:
        data = get(API)
    else:
        try:
            with urllib.request.urlopen(urllib.request.Request(API, headers=HEADERS), timeout=60) as resp:
                data = json.load(resp)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if cache.exists():
                return json.loads(cache.read_text())  # stale beats nothing
            raise SetError(f"Could not reach Scryfall: {exc}") from exc
    try:
        out = {s["code"]: {"code": s["code"], "name": s["name"], "released": s.get("released_at"),
                           "type": s.get("set_type"), "card_count": s.get("card_count"),
                           "icon": s.get("icon_svg_uri"), "parent": s.get("parent_set_code"),
                           "digital": bool(s.get("digital"))} for s in data["data"]}
    except (KeyError, TypeError) as exc:
        raise SetError("Unexpected Scryfall set list (the API may have changed).") from exc
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out))
    return out


def listed_sets(db, meta=None):
    """Sets that have priced paper printings in the card database, newest first:
    ``[{code, name, released, type, icon, parent, printings, value}]``."""
    meta = meta if meta is not None else fetch_sets()
    rows = db.conn.execute(
        "SELECT set_code, set_name, COUNT(*) AS n, ROUND(SUM(COALESCE(usd, 0)), 2) AS v, MIN(released_at) AS d "
        "FROM printings GROUP BY set_code").fetchall()
    out = []
    for r in rows:
        m = meta.get(r["set_code"], {})
        if m.get("type") in HIDDEN_TYPES or m.get("digital"):
            continue
        out.append({"code": r["set_code"], "name": m.get("name") or r["set_name"] or r["set_code"].upper(),
                    "released": m.get("released") or r["d"], "type": m.get("type"), "icon": m.get("icon"),
                    "parent": m.get("parent"), "printings": r["n"], "value": r["v"] or 0.0})
    return sorted(out, key=lambda s: (s["released"] or "", s["code"]), reverse=True)


def family(code, sets):
    """The set, its parent and its siblings/children (one release), main set first."""
    by = {s["code"]: s for s in sets}
    root = code
    while by.get(root, {}).get("parent") in by:
        root = by[root]["parent"]
    members = [s for s in sets if s["code"] == root or s["parent"] == root
               or by.get(s["parent"] or "", {}).get("parent") == root]
    return sorted(members, key=lambda s: (s["code"] != root, s["type"] != "commander", s["name"]))


def search(query, sets, limit=20):
    """Sets whose name or code matches ``query`` (all words), newest first."""
    words = query.lower().split()
    return [s for s in sets if all(w in f"{s['name']} {s['code']}".lower() for w in words)][:limit]


def set_cards(db, codes):
    """Every printing in ``codes`` with its card facts: ``[{name, set_code, collector_number, rarity,
    treatment, usd, usd_foil, eur, top_price, image_url, edhrec_rank, game_changer, ...}]``."""
    codes = list(codes)
    marks = ",".join("?" * len(codes))
    rows = db.conn.execute(
        f"SELECT p.*, c.name, c.type_line, c.edhrec_rank, c.game_changer, c.color_identity, c.reserved "
        f"FROM printings p JOIN cards c ON c.oracle_id = p.oracle_id WHERE p.set_code IN ({marks})", codes).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        prices = [p for p in (r["usd"], r["usd_foil"], r["usd_etched"]) if p is not None]
        r["top_price"] = max(prices) if prices else None
        out.append(r)
    return out


SORTS = {
    "Most valuable": lambda c: (c["top_price"] is None, -(c["top_price"] or 0)),
    "Normal price": lambda c: (c["usd"] is None, -(c["usd"] or 0)),
    "Foil price": lambda c: (c["usd_foil"] is None, -(c["usd_foil"] or 0)),
    "Most played in Commander": lambda c: (c["edhrec_rank"] is None, c["edhrec_rank"] or 0),
    "Set number": lambda c: (len(c["collector_number"] or ""), c["collector_number"] or ""),
}


def summary(cards):
    """Set value at a glance (normal prices; one copy of each printing)."""
    normal = [c["usd"] for c in cards if c["usd"] is not None]
    top = max(cards, key=lambda c: c["top_price"] or 0) if cards else None
    return {"printings": len(cards), "priced": len(normal), "total": round(sum(normal), 2),
            "median": round(statistics.median(normal), 2) if normal else None,
            "over_1": sum(p >= 1 for p in normal), "over_10": sum(p >= 10 for p in normal),
            "top": top, "unique_cards": len({c["name"] for c in cards})}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Find a set and list its most valuable cards.")
    parser.add_argument("query", help='set code (e.g. "trk") or words of its name ("star trek")')
    parser.add_argument("--sort", choices=list(SORTS), default="Most valuable")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    db = card_db.open_db(log=lambda m: print(m, file=sys.stderr))
    try:
        sets = listed_sets(db)
        by = {s["code"]: s for s in sets}
        if args.query.lower() not in by:
            for s in search(args.query, sets):
                print(f"{s['code']:6} {s['released']}  {s['name']} ({s['printings']} printings, ${s['value']:,.0f})")
            return 0
        s = by[args.query.lower()]
        cards = sorted(set_cards(db, [s["code"]]), key=SORTS[args.sort])
        sm = summary(cards)
        print(f"# {s['name']} ({s['code'].upper()}, {s['released']}): {sm['printings']} printings, "
              f"${sm['total']:,.2f} for one of each, median ${sm['median'] or 0:.2f}")
        for c in cards[: args.limit]:
            price = f"${c['usd']:,.2f}" if c["usd"] is not None else "   n/a"
            foil = f" foil ${c['usd_foil']:,.2f}" if c["usd_foil"] is not None else ""
            print(f"  {price:>9}{foil}  #{c['collector_number']} {c['name']} ({c['rarity']}"
                  + (f", {c['treatment']}" if c["treatment"] else "") + ")")
    except SetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
