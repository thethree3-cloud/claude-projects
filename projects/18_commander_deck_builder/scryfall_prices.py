"""Look up card prices and types from Scryfall for a list of card names.

Uses the batch ``/cards/collection`` endpoint (75 names per request) rather than
one request per card. If a card's default printing has no USD price (common for
very popular cards like Sol Ring), falls back to the cheapest USD printing.

This is the prototype price path. Slice 1 (Scryfall bulk data loaded once)
replaces it and removes the live calls entirely.
"""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.scryfall.com"
HEADERS = {
    "User-Agent": "commander-deck-builder/0.1",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
CACHE_DIR = Path(__file__).parent / "data" / "cache"
CACHE_MAX_AGE_HOURS = 24
BATCH_SIZE = 75
DELAY = 0.2  # Scryfall asks for well under 10 requests/second


def _request(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def _default_usd(card):
    prices = card.get("prices", {})
    usd = prices.get("usd") or prices.get("usd_foil") or prices.get("usd_etched")
    return float(usd) if usd else None


def _cheapest_printing_usd(name):
    query = urllib.parse.urlencode({"q": f'!"{name}"', "unique": "prints"})
    prints = _request(f"{API}/cards/search?{query}").get("data", [])
    usds = [float(p["prices"]["usd"]) for p in prints if p.get("prices", {}).get("usd")]
    return min(usds) if usds else None


def _load_cache(cache_file):
    if not cache_file.exists():
        return {}
    try:
        return json.loads(cache_file.read_text())
    except json.JSONDecodeError:
        return {}


def lookup_cards(names, cache_dir=CACHE_DIR, refresh=False):
    """Return ``{name: {"usd": float|None, "type_line": str, "price_source": str|None}}``.

    price_source is "default" (the default printing's USD) or "cheapest_printing".
    Names Scryfall can't find are omitted from the result.
    """
    cache_file = Path(cache_dir) / "scryfall_prices.json"
    cache = {} if refresh else _load_cache(cache_file)
    max_age = CACHE_MAX_AGE_HOURS * 3600
    now = time.time()

    result = {}
    missing = []
    for name in dict.fromkeys(names):
        entry = cache.get(name)
        if entry and now - entry["fetched_at"] < max_age:
            result[name] = {k: entry[k] for k in ("usd", "type_line", "price_source")}
        else:
            missing.append(name)

    fetched = {}
    for start in range(0, len(missing), BATCH_SIZE):
        batch = missing[start : start + BATCH_SIZE]
        payload = {"identifiers": [{"name": n} for n in batch]}
        for card in _request(f"{API}/cards/collection", payload).get("data", []):
            usd = _default_usd(card)
            fetched[card["name"]] = {
                "usd": usd,
                "type_line": card.get("type_line", ""),
                "price_source": "default" if usd is not None else None,
            }
        time.sleep(DELAY)

    # Fill in prices for cards whose default printing has no USD.
    for name, info in fetched.items():
        if info["usd"] is None:
            info["usd"] = _cheapest_printing_usd(name)
            if info["usd"] is not None:
                info["price_source"] = "cheapest_printing"
            time.sleep(DELAY)

    # EDHREC names may be a DFC front face; Scryfall returns the full "A // B" name.
    for requested in missing:
        info = fetched.get(requested) or next(
            (v for k, v in fetched.items() if k.split(" // ")[0] == requested), None
        )
        if info is not None:
            result[requested] = info
            cache[requested] = {**info, "fetched_at": now}

    if fetched:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache))
    return result
