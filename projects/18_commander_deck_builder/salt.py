"""Salt scores: how much players dislike playing against a card (EDHREC's yearly
community survey, 0-4), for card pages, deck totals and a "friendly table" filter.

EDHREC publishes its salt ranking as paged JSON (``top/salt``); the saltiest
``PAGES`` x 100 cards are cached for a week. Cards not on it fall back to the
salt Archidekt stores with each deck (``archidekt.py``), else 0.

CLI:
    python salt.py "Rhystic Study" "Sol Ring"
"""

import json
import sys
import time
from pathlib import Path

import edhrec_client

CACHE = Path(__file__).parent / "data" / "cache" / "edhrec_salt.json"
PAGES = 20
MAX_AGE_S = 7 * 86400
# Builder presets: leave out cards at or above this salt (None = keep everything).
FRIENDLY = {"Any": None, "Skip the saltiest (under 2.0)": 2.0, "Friendly table (under 1.75)": 1.75}
# (Sol Ring itself scores ~1.6, so a lower cut would drop staples.)


def fetch(pages=PAGES, get=None, cache=CACHE):
    """``{card name: salt}`` from EDHREC's salt ranking (cached for a week)."""
    cache = Path(cache)
    if cache.exists() and time.time() - cache.stat().st_mtime < MAX_AGE_S:
        return json.loads(cache.read_text())
    get = get or (lambda path: edhrec_client._get_json(f"{edhrec_client.PAGES_URL}/{path}.json", path))
    out, path = {}, "top/salt"
    for _ in range(pages):
        page = get(path)
        if "container" in page:
            lists = page["container"]["json_dict"]["cardlists"]
            views = [v for cl in lists for v in cl.get("cardviews", [])]
            more = lists[0].get("more") if lists else None
        else:
            views, more = page.get("cardviews", []), page.get("more")
        for v in views:
            if v.get("name") and v.get("salt") is not None:
                out.setdefault(v["name"], round(v["salt"], 2))
        if not more:
            break
        path = more.removesuffix(".json")
    if not out:
        raise edhrec_client.EdhrecError("EDHREC's salt list was empty.")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out))
    return out


def salt_map(names, db=None, edhrec=None):
    """``{name: salt}`` for the names given (EDHREC first, Archidekt second, else 0.0)."""
    if edhrec is None:
        try:
            edhrec = fetch()
        except edhrec_client.EdhrecError:
            edhrec = {}
    out, missing = {}, []
    for n in names:
        front = n.split(" // ")[0]
        if n in edhrec or front in edhrec:
            out[n] = edhrec.get(n, edhrec.get(front))
        else:
            missing.append(n)
    if missing and db is not None:
        import archidekt
        a = archidekt.Archidekt()
        try:
            for n in missing:
                card = db.get(n)
                s = a.salt(card["oracle_id"]) if card else None
                out[n] = round(s, 2) if s is not None else 0.0
        finally:
            a.close()
    for n in missing:
        out.setdefault(n, 0.0)
    return out


def deck_salt(names, db=None, edhrec=None, top=5):
    """``{"total", "average", "saltiest": [(name, salt)], "per_card": {...}}`` for a deck's cards."""
    per = salt_map(names, db, edhrec)
    total = round(sum(per.values()), 1)
    return {"total": total, "average": round(total / len(per), 2) if per else 0.0,
            "saltiest": sorted(((n, s) for n, s in per.items() if s > 0), key=lambda x: -x[1])[:top],
            "per_card": per}


def main(argv=None):
    names = (argv if argv is not None else sys.argv[1:]) or ["Rhystic Study", "Sol Ring"]
    for n, s in salt_map(names).items():
        print(f"{s:4.2f}  {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
