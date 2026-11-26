"""Fetch and parse EDHREC's per-commander card data.

EDHREC has no official API. This uses the JSON its own site loads:
``https://json.edhrec.com/pages/commanders/<slug>.json``. The format can change
without notice, so parsing is defensive and pages are cached on disk.

Inclusion % is ``num_decks / potential_decks`` per card (the raw JSON has no
percentage field).
"""

import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://json.edhrec.com/pages/commanders"
HEADERS = {"User-Agent": "commander-deck-builder/0.1", "Accept": "application/json"}
CACHE_DIR = Path(__file__).parent / "data" / "cache"
CACHE_MAX_AGE_DAYS = 7

# EDHREC list header -> role. The four lists below are cross-cuts, not roles.
ROLE_BY_HEADER = {
    "Creatures": "Creature",
    "Instants": "Instant",
    "Sorceries": "Sorcery",
    "Utility Artifacts": "Utility Artifact",
    "Mana Artifacts": "Mana Artifact",
    "Enchantments": "Enchantment",
    "Battles": "Battle",
    "Planeswalkers": "Planeswalker",
    "Utility Lands": "Utility Land",
    "Lands": "Land",
}
HIGH_SYNERGY_HEADER = "High Synergy Cards"
GAME_CHANGERS_HEADER = "Game Changers"

BASIC_LANDS = {
    "Plains",
    "Island",
    "Swamp",
    "Mountain",
    "Forest",
    "Wastes",
    "Snow-Covered Plains",
    "Snow-Covered Island",
    "Snow-Covered Swamp",
    "Snow-Covered Mountain",
    "Snow-Covered Forest",
}


class EdhrecError(Exception):
    """EDHREC page missing or in an unexpected format."""


def slugify(name):
    """Card name -> EDHREC slug, e.g. "Muldrotha, the Gravetide" -> "muldrotha-the-gravetide".

    Uses the front face of double-faced cards, strips accents and apostrophes.
    """
    front = name.split(" // ")[0]
    ascii_name = unicodedata.normalize("NFKD", front).encode("ascii", "ignore").decode()
    ascii_name = ascii_name.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")


MIN_INTERVAL_S = 0.5  # polite gap between EDHREC requests
RETRIES = 3  # extra tries for 429 / 5xx / network errors
RETRY_BASE_S = 1.0  # backoff: 1 s, 2 s, 4 s (or the server's Retry-After, up to 30 s)
_last_request = [0.0]
_request_lock = threading.Lock()


def _throttle():
    with _request_lock:
        wait = _last_request[0] + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()


def _get_json(url, slug):
    """GET one EDHREC JSON page. Missing pages (403/404/empty) raise at once;
    rate limits, server errors and network errors are retried with backoff."""
    for attempt in range(RETRIES + 1):
        _throttle()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                raise EdhrecError(
                    f"No EDHREC page for '{slug}' (not a commander, or too new to have data)."
                ) from exc
            if exc.code != 429 and exc.code < 500 or attempt == RETRIES:
                raise EdhrecError(f"EDHREC returned HTTP {exc.code} for '{slug}'.") from exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            delay = float(retry_after) if retry_after and retry_after.isdigit() else RETRY_BASE_S * 2 ** attempt
            time.sleep(min(delay, 30.0))
        except json.JSONDecodeError as exc:
            raise EdhrecError(f"No EDHREC page for '{slug}' (empty answer).") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == RETRIES:
                raise EdhrecError(f"Could not reach EDHREC for '{slug}': {exc}") from exc
            time.sleep(RETRY_BASE_S * 2 ** attempt)


def pair_slug(names):
    """EDHREC slug for two commanders: both slugs joined, alphabetical
    (EDHREC redirects the other order anyway)."""
    return "-".join(sorted(slugify(n) for n in names))


def fetch_commander_page(slug, cache_dir=CACHE_DIR, max_age_days=CACHE_MAX_AGE_DAYS, refresh=False):
    """Return the raw EDHREC JSON for a commander slug, using a disk cache."""
    cache_file = Path(cache_dir) / f"edhrec_{slug}.json"
    max_age_seconds = max_age_days * 86400
    if not refresh and cache_file.exists():
        if time.time() - cache_file.stat().st_mtime < max_age_seconds:
            return json.loads(cache_file.read_text())

    page = _get_json(f"{BASE_URL}/{slug}.json", slug)
    # Pairs listed in the other order answer {"redirect": "/commanders/<slug>"}.
    redirect = page.get("redirect") if isinstance(page, dict) else None
    if redirect:
        target = redirect.rstrip("/").rsplit("/", 1)[-1]
        page = _get_json(f"{BASE_URL}/{target}.json", target)

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(page))
    return page


CARD_URL = "https://json.edhrec.com/pages/cards"
CARD_CACHE_DIR = CACHE_DIR / "edhrec_cards"
CARD_CACHE_MAX_AGE_DAYS = 30
TOP_COMMANDERS_HEADER = "Top Commanders"


def parse_card_commanders(page, top=5):
    """The commanders whose decks play a card most, from its EDHREC card page:
    ``[{"name", "decks", "potential"}]``, most decks first. ``decks`` / ``potential``
    = that commander's decks with the card / that could play it.

    Raises:
        EdhrecError: if the page doesn't have the expected structure.
    """
    try:
        cardlists = page["container"]["json_dict"]["cardlists"]
    except (KeyError, TypeError) as exc:
        raise EdhrecError("Unexpected EDHREC card page format (EDHREC may have changed).") from exc
    views = next((cl.get("cardviews") or [] for cl in cardlists if cl.get("header") == TOP_COMMANDERS_HEADER), [])
    out = [{"name": v["name"], "decks": v.get("num_decks") or 0, "potential": v.get("potential_decks") or 0}
           for v in views if v.get("name")]
    return sorted(out, key=lambda x: -x["decks"])[:top]


def card_commanders(name, cache_dir=CARD_CACHE_DIR, max_age_days=CARD_CACHE_MAX_AGE_DAYS, fetch=None, allow_fetch=True):
    """Top commanders for one card, from a disk cache (refreshed after ``max_age_days``).

    Returns ``(commanders, fetched)``; ``commanders`` is None when nothing is cached
    and fetching isn't allowed. A card EDHREC has no page for is cached as ``[]``
    so it isn't asked for again until the cache expires.
    """
    slug = slugify(name)
    path = Path(cache_dir) / f"{slug}.json"
    if path.exists() and time.time() - path.stat().st_mtime < max_age_days * 86400:
        return json.loads(path.read_text())["top"], False
    if not allow_fetch:
        return (json.loads(path.read_text())["top"] if path.exists() else None), False
    fetch = fetch or (lambda s: _get_json(f"{CARD_URL}/{s}.json", s))
    try:
        top = parse_card_commanders(fetch(slug))
    except EdhrecError:
        top = []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": name, "top": top}))
    return top, True


PAGES_URL = "https://json.edhrec.com/pages"
POPULARITY_PAGES = 20  # ~100 commanders per page -> the top ~2,000


def commander_popularity(cache_dir=CACHE_DIR, max_age_days=CACHE_MAX_AGE_DAYS, pages=POPULARITY_PAGES):
    """``{commander name: decks in the past 2 years}`` from EDHREC's commander
    ranking, cached on disk. Returns {} if EDHREC can't be reached (callers then
    fall back to card popularity), so it never blocks a lookup."""
    cache_file = Path(cache_dir) / "edhrec_commander_popularity.json"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < max_age_days * 86400:
        return json.loads(cache_file.read_text())
    ranking, path = {}, "commanders/year"
    try:
        for _ in range(pages):
            page = _get_json(f"{PAGES_URL}/{path}.json", path)
            if "container" in page:  # first page
                lists = page["container"]["json_dict"]["cardlists"]
                views = [v for cl in lists for v in cl.get("cardviews", [])]
                more = lists[0].get("more") if lists else None
            else:  # later pages are bare lists
                views, more = page.get("cardviews", []), page.get("more")
            for v in views:
                if v.get("name"):
                    ranking.setdefault(v["name"], v.get("num_decks") or 0)
            if not more:
                break
            path = more.removesuffix(".json")
    except (EdhrecError, KeyError, TypeError, AttributeError):
        if not ranking:
            return {}
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(ranking))
    return ranking


AVERAGE_DECK_URL = "https://json.edhrec.com/pages/average-decks"


def fetch_average_deck(slug, cache_dir=CACHE_DIR, max_age_days=CACHE_MAX_AGE_DAYS):
    """Card names in EDHREC's average deck for a commander (commander and basics excluded)."""
    cache_file = Path(cache_dir) / f"edhrec_avg_{slug}.json"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < max_age_days * 86400:
        page = json.loads(cache_file.read_text())
    else:
        page = _get_json(f"{AVERAGE_DECK_URL}/{slug}.json", slug)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(page))
    try:
        deck = page["deck"]
        commanders = set(deck.get("commander") or [])
        groups = deck["cards"].values()
    except (KeyError, TypeError, AttributeError) as exc:
        raise EdhrecError("Unexpected EDHREC average-deck format (EDHREC may have changed).") from exc
    names = {entry[0] for group in groups for entry in group if entry}
    return sorted(names - commanders - BASIC_LANDS)


def parse_commander_page(page):
    """Turn raw EDHREC JSON into ``{"commander": {...}, "cards": [...]}``.

    Each card: name, role (None if only in cross-cut lists), inclusion (0-1),
    synergy, num_decks, potential_decks, high_synergy, game_changer.
    Cards appearing in several lists are merged by name.

    Raises:
        EdhrecError: if the page doesn't have the expected structure.
    """
    try:
        json_dict = page["container"]["json_dict"]
        card_info = json_dict["card"]
        cardlists = json_dict["cardlists"]
    except (KeyError, TypeError) as exc:
        raise EdhrecError("Unexpected EDHREC page format (EDHREC may have changed).") from exc

    commander = {
        "name": card_info.get("name"),
        "color_identity": card_info.get("color_identity", []),
        "num_decks": card_info.get("num_decks", 0),
        "legal_commander": card_info.get("legal_commander", True),
    }

    merged = {}
    for cardlist in cardlists:
        header = cardlist.get("header")
        role = ROLE_BY_HEADER.get(header)
        for view in cardlist.get("cardviews", []):
            name = view.get("name")
            if not name:
                continue
            potential = view.get("potential_decks") or 0
            num = view.get("num_decks") or 0
            card = merged.setdefault(
                name,
                {
                    "name": name,
                    "role": None,
                    "inclusion": num / potential if potential else 0.0,
                    "synergy": view.get("synergy", 0.0),
                    "num_decks": num,
                    "potential_decks": potential,
                    "high_synergy": False,
                    "game_changer": False,
                },
            )
            if role and card["role"] is None:
                card["role"] = role
            if header == HIGH_SYNERGY_HEADER:
                card["high_synergy"] = True
            if header == GAME_CHANGERS_HEADER:
                card["game_changer"] = True

    return {"commander": commander, "cards": list(merged.values())}


THIN_PAIR_DECKS = 50  # a pair page with fewer decks than this gets the single pages mixed in


def commander_cards(names, fetch=None):
    """EDHREC data for one or two commanders: ``{"commander", "cards", "sources"}``.

    One name: that commander's page. Two: the pair's page; if it is missing or
    has fewer than ``THIN_PAIR_DECKS`` decks, each commander's own page is mixed
    in (cards the pair page lacks take their best single-page inclusion).
    Backgrounds have no page of their own, which is fine.
    """
    fetch = fetch or fetch_commander_page
    if len(names) == 1:
        page = parse_commander_page(fetch(slugify(names[0])))
        return {**page, "sources": [slugify(names[0])]}

    pages, sources = [], []
    pair = None
    try:
        pair = parse_commander_page(fetch(pair_slug(names)))
        pages.append(pair)
        sources.append(pair_slug(names))
    except EdhrecError:
        pass
    if pair is None or pair["commander"]["num_decks"] < THIN_PAIR_DECKS:
        for name in names:
            try:
                pages.append(parse_commander_page(fetch(slugify(name))))
                sources.append(slugify(name))
            except EdhrecError:
                continue  # e.g. a Background
    if not pages:
        raise EdhrecError(f"No EDHREC data for {' + '.join(names)} or either commander alone.")

    merged = {}
    for i, page in enumerate(pages):
        for card in page["cards"]:
            have = merged.get(card["name"])
            # The pair page (first) wins; otherwise keep the higher inclusion.
            if have is None or (i > 0 and have["_page"] > 0 and card["inclusion"] > have["inclusion"]):
                merged[card["name"]] = {**card, "_page": i}
    cards = [{k: v for k, v in c.items() if k != "_page"} for c in merged.values()]
    commander = {
        "name": " + ".join(names),
        "num_decks": pair["commander"]["num_decks"] if pair else 0,
        "legal_commander": all(p["commander"]["legal_commander"] for p in pages),
    }
    return {"commander": commander, "cards": cards, "sources": sources}
