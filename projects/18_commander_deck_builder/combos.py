"""Combos in a deck, from Commander Spellbook (commanderspellbook.com).

Sends the decklist (card names only) to Spellbook's public "find my combos"
endpoint and reports:
  - combos fully in the deck, with what they produce and how they work
  - combos one card away (inside the deck's colors), with that card's price
    from the local card database

Results are cached on disk by decklist, so re-checking the same deck makes
no request. The builder doesn't add combos on its own (v1 only shows them).

Usage:
    python combos.py deck.txt
    python combos.py deck.txt --almost 10 --json
"""

import argparse
import datetime
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import card_db
from validate_deck import parse_decklist

API = "https://backend.commanderspellbook.com/find-my-combos"
HEADERS = {"User-Agent": "commander-deck-builder/0.1", "Content-Type": "application/json",
           "Accept": "application/json"}
CACHE_DIR = Path(__file__).parent / "data" / "cache"
CACHE_MAX_AGE_DAYS = 7
RETRIES = 2


class ComboError(Exception):
    """Spellbook unreachable or answered in an unexpected format."""


def _post(body):
    data = json.dumps(body).encode()
    for attempt in range(RETRIES + 1):
        try:
            req = urllib.request.Request(API, data=data, headers=HEADERS, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if (exc.code != 429 and exc.code < 500) or attempt == RETRIES:
                raise ComboError(f"Commander Spellbook returned HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == RETRIES:
                raise ComboError(f"Could not reach Commander Spellbook: {exc}") from exc
        time.sleep(2 ** attempt)


def fetch(commanders, main, cache_dir=CACHE_DIR, post=None):
    """Raw Spellbook results for a deck (cached by its card list)."""
    body = {"commanders": [{"card": n} for n in commanders], "main": [{"card": n} for n in sorted(main)]}
    key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
    cache_file = Path(cache_dir) / f"spellbook_{key}.json"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < CACHE_MAX_AGE_DAYS * 86400:
        return json.loads(cache_file.read_text())
    answer = (post or _post)(body)
    try:
        results = answer["results"]
        results["included"], results["almostIncluded"]  # noqa: B018  (shape check)
    except (KeyError, TypeError) as exc:
        raise ComboError("Unexpected Commander Spellbook answer (the API may have changed).") from exc
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(results))
    return results


def _combo(variant, have):
    cards = [u["card"]["name"] for u in variant.get("uses", [])]
    return {
        "id": variant.get("id"),
        "cards": cards,
        "missing": [c for c in cards if c not in have],
        "produces": [p["feature"]["name"] for p in variant.get("produces", [])],
        "description": variant.get("description", ""),
        "prerequisites": " ".join(x for x in (variant.get("easyPrerequisites"), variant.get("notablePrerequisites")) if x),
        "popularity": variant.get("popularity") or 0,
        "url": f"https://commanderspellbook.com/combo/{variant.get('id')}/",
    }


def _deck_names(name, db):
    """Spellbook uses front-face names for some double-faced cards; match both ways."""
    card = db.get(name) if db else None
    full = card["name"] if card else name
    return {full, full.split(" // ")[0]}


def find_combos(commanders, main, db=None, almost_limit=5, fetch_fn=None):
    """``{"in_deck": [...], "one_card_away": [...]}`` for a deck.

    ``commanders`` / ``main`` are card names. One-card-away combos are limited to
    a single missing card inside the deck's colors, most popular first, each
    with that card's price (None if unknown)."""
    results = (fetch_fn or fetch)(commanders, main)
    have = set()
    for name in [*commanders, *main]:
        have |= _deck_names(name, db)
    in_deck = sorted((_combo(v, have) for v in results["included"]), key=lambda c: -c["popularity"])
    almost = []
    for v in results["almostIncluded"]:
        combo = _combo(v, have)
        if len(combo["missing"]) != 1:
            continue
        card = db.get(combo["missing"][0]) if db else None
        combo["missing_usd"] = card["usd"] if card else None
        almost.append(combo)
    almost.sort(key=lambda c: -c["popularity"])
    return {"in_deck": in_deck, "one_card_away": almost[:almost_limit]}


def deck_combos(commander, deck, db, **kwargs):
    """``find_combos`` for a builder deck dict (members + chosen nonbasic cards)."""
    members = [c["name"] for c in card_db.commander_members(commander)]
    return find_combos(members, [c["name"] for c in deck["cards"]], db, **kwargs)


# ---------------------------------------------------------------------------
# Combo spikes: old cards that a new card turns into a combo piece
# ---------------------------------------------------------------------------

VARIANTS_API = "https://backend.commanderspellbook.com/variants/"
NEW_DAYS = 60  # a card first printed this recently (or not out yet) counts as new
MAX_NEW_CARDS = 40  # Spellbook lookups per day, cached


def _get(url, params):
    query = urllib.parse.urlencode(params)
    for attempt in range(RETRIES + 1):
        try:
            req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": HEADERS["User-Agent"],
                                                                     "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if (exc.code != 429 and exc.code < 500) or attempt == RETRIES:
                raise ComboError(f"Commander Spellbook returned HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == RETRIES:
                raise ComboError(f"Could not reach Commander Spellbook: {exc}") from exc
        time.sleep(2 ** attempt)


def variants_with(name, cache_dir=CACHE_DIR, get=None, limit=25):
    """Spellbook combos that use ``name`` (most popular first), cached for a day."""
    key = hashlib.sha256(name.encode()).hexdigest()[:16]
    cache_file = Path(cache_dir) / f"spellbook_card_{key}.json"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < 86400:
        return json.loads(cache_file.read_text())
    time.sleep(0.3)  # polite spacing between lookups
    answer = (get or _get)(VARIANTS_API, {"q": f'card:"{name}"', "ordering": "-popularity", "limit": limit})
    if not isinstance(answer, dict) or "results" not in answer:
        raise ComboError("Unexpected Commander Spellbook answer (the API may have changed).")
    results = answer["results"]
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(results))
    return results


def new_cards(db, today=None, rising=None, limit=MAX_NEW_CARDS):
    """New or upcoming Commander-legal cards worth checking: upcoming ones first
    (not out yet), then new ones that are on EDHREC's rising list, most rising first."""
    today = today or time.strftime("%Y-%m-%d")
    cutoff = (datetime.date.fromisoformat(today) - datetime.timedelta(days=NEW_DAYS)).isoformat()
    rows = db.conn.execute(
        "SELECT c.name, MIN(p.released_at) AS first FROM printings p JOIN cards c ON c.oracle_id = p.oracle_id "
        "WHERE c.legal_commander = 1 AND p.promo = 0 GROUP BY c.oracle_id HAVING first >= ?", (cutoff,)).fetchall()
    upcoming = sorted(r["name"] for r in rows if r["first"] > today)
    fresh = {r["name"] for r in rows if r["first"] <= today}
    trend = {r["name"]: r["trend"] or 0 for r in rising or []}
    popular_new = sorted((n for n in fresh if n in trend), key=lambda n: -trend[n])
    return (upcoming + popular_new)[:limit]


def combo_spikes(db, new_names, today=None, variants=None, max_usd=None, log=lambda *_: None):
    """Older cards that complete a combo with a new or upcoming card.

    Returns ``[{name, usd, supply, combos: [{new_card, with, produces, url, popularity}], popularity}]``,
    best first (most popular combos). "Older" = first printed over a year ago."""
    import watchlist  # local: watchlist imports nothing from here
    today = today or time.strftime("%Y-%m-%d")
    year_ago = (datetime.date.fromisoformat(today) - datetime.timedelta(days=365)).isoformat()
    variants = variants or variants_with
    partners = {}
    for new in new_names:
        try:
            found = variants(new)
        except ComboError as exc:
            log(f"{new}: {exc}")
            continue
        for v in found:
            cards = [u["card"]["name"] for u in v.get("uses", [])]
            for other in cards:
                if other == new or other in new_names:
                    continue
                entry = partners.setdefault(other, {"name": other, "combos": []})
                entry["combos"].append({
                    "new_card": new, "with": [c for c in cards if c != other],
                    "produces": [p["feature"]["name"] for p in v.get("produces", [])][:3],
                    "url": f"https://commanderspellbook.com/combo/{v.get('id')}/",
                    "popularity": v.get("popularity") or 0})
    supply = db.supply(list(partners), today)
    out = []
    for name, entry in partners.items():
        card = db.get(name)
        sup = supply.get(name)
        if card is None or sup is None or not sup["first"] or sup["first"] >= year_ago:
            continue  # unknown, or itself new
        if card["usd"] is None or (max_usd is not None and card["usd"] > max_usd):
            continue
        _, label = watchlist.supply_factor(sup, today)
        entry["combos"].sort(key=lambda c: -c["popularity"])
        out.append({**entry, "name": card["name"], "usd": card["usd"], "supply": label,
                    "popularity": max(c["popularity"] for c in entry["combos"])})
    out.sort(key=lambda e: (-len({c["new_card"] for c in e["combos"]}), -e["popularity"]))
    return out


def format_report(found):
    lines = [f"## Combos in this deck ({len(found['in_deck'])})", ""]
    if not found["in_deck"]:
        lines.append("None found by Commander Spellbook.")
    for c in found["in_deck"]:
        lines.append(f"- **{' + '.join(c['cards'])}**: {', '.join(c['produces'][:3]) or 'see link'} ({c['url']})")
    lines += ["", f"## One card away ({len(found['one_card_away'])})", ""]
    if not found["one_card_away"]:
        lines.append("None.")
    for c in found["one_card_away"]:
        price = f"${c['missing_usd']:.2f}" if c["missing_usd"] is not None else "price unknown"
        lines.append(f"- add **{c['missing'][0]}** ({price}) for {' + '.join(c['cards'])}: "
                     f"{', '.join(c['produces'][:2]) or 'see link'} ({c['url']})")
    lines += ["", "Combo data: Commander Spellbook (commanderspellbook.com)."]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="List combos in a decklist (Commander Spellbook).")
    parser.add_argument("decklist", type=Path, help="decklist text; first line is the commander")
    parser.add_argument("--partner", action="store_true", help="the second line is a second commander")
    parser.add_argument("--almost", type=int, default=5, help="how many one-card-away combos to show")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        entries = parse_decklist(args.decklist.read_text())
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    names = [name for _, name in entries]
    n_cmd = 2 if args.partner else 1
    db = card_db.open_db(log=lambda m: print(m, file=sys.stderr))
    try:
        found = find_combos(names[:n_cmd], names[n_cmd:], db, almost_limit=args.almost)
    except ComboError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(found, indent=2) if args.json else format_report(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
