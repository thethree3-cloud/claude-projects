"""Fetch and parse EDHREC's per-commander card data.

EDHREC has no official API. This uses the JSON its own site loads:
``https://json.edhrec.com/pages/commanders/<slug>.json``. The format can change
without notice, so parsing is defensive and pages are cached on disk.

Inclusion % is ``num_decks / potential_decks`` per card (the raw JSON has no
percentage field).
"""

import json
import re
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


def fetch_commander_page(slug, cache_dir=CACHE_DIR, max_age_days=CACHE_MAX_AGE_DAYS, refresh=False):
    """Return the raw EDHREC JSON for a commander slug, using a disk cache."""
    cache_file = Path(cache_dir) / f"edhrec_{slug}.json"
    max_age_seconds = max_age_days * 86400
    if not refresh and cache_file.exists():
        if time.time() - cache_file.stat().st_mtime < max_age_seconds:
            return json.loads(cache_file.read_text())

    url = f"{BASE_URL}/{slug}.json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS)) as resp:
            page = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            raise EdhrecError(
                f"No EDHREC page for '{slug}' (not a commander, or too new to have data)."
            ) from exc
        raise EdhrecError(f"EDHREC returned HTTP {exc.code} for '{slug}'.") from exc

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(page))
    return page


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
