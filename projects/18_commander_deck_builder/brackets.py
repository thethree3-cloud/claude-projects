"""Bracket estimate for a deck, from Commander Spellbook's deck classifier.

Spellbook's ``estimate-bracket`` endpoint reads a decklist and flags Game
Changers, mass land denial, extra-turn cards and combos (two-card or not, and
whether they chain extra turns). It also gives its own tag on its own scale
(Exhibition, Core, Powerful, Oddball, Spicy, Ruthless, Banned), shown as is.

The **official bracket** (Wizards of the Coast's 1-5 system) is worked out
here from those flags, by the published rules:
  - Brackets 1-2: no Game Changers, no mass land denial, no chained extra
    turns, no two-card combos (1 vs 2 is about intent, so "2" is reported
    with a note).
  - Bracket 3: up to three Game Changers; no mass land denial, no chained
    extra turns; two-card combos only late in the game.
  - Bracket 4: anything legal. (5 = cEDH, a table agreement, not a deck check.)
So this gives the *lowest* bracket the deck fits, with every reason listed.

Results are cached per decklist.
"""

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import card_db

API = "https://backend.commanderspellbook.com/estimate-bracket"
HEADERS = {"User-Agent": "commander-deck-builder/0.1", "Content-Type": "application/json", "Accept": "application/json"}
CACHE_DIR = Path(__file__).parent / "data" / "cache"
SPELLBOOK_TAGS = {"E": "Exhibition", "C": "Core", "P": "Powerful", "O": "Oddball", "S": "Spicy", "R": "Ruthless",
                  "B": "Banned"}
BRACKET_NAMES = {1: "Exhibition", 2: "Core", 3: "Upgraded", 4: "Optimized", 5: "cEDH"}


class BracketError(Exception):
    """Spellbook unreachable or answered unexpectedly."""


def _post(body):
    data = json.dumps(body).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(API, data=data, headers=HEADERS, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if (exc.code != 429 and exc.code < 500) or attempt == 2:
                raise BracketError(f"Commander Spellbook returned HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == 2:
                raise BracketError(f"Could not reach Commander Spellbook: {exc}") from exc
        time.sleep(2 ** attempt)


def classify(commanders, main, cache_dir=CACHE_DIR, post=None):
    """Spellbook's classification of a deck (``main``: [(name, qty)]), cached per decklist."""
    body = {"commanders": [{"card": n} for n in commanders],
            "main": [{"card": n, "quantity": q} for n, q in sorted(main)]}
    key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
    path = Path(cache_dir) / f"bracket_{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    raw = (post or _post)(body)
    if not isinstance(raw, dict) or "bracketTag" not in raw or "cards" not in raw:
        raise BracketError("Unexpected Commander Spellbook answer (the API may have changed).")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw))
    return raw


def official_bracket(raw):
    """``{"lowest", "name", "reasons", "game_changers", "land_denial", "extra_turns",
    "two_card_combos", "turn_chains", "spellbook_tag"}`` from a Spellbook classification."""
    cards = raw.get("cards") or []

    def names(flag):
        return sorted({c["card"]["name"] for c in cards if c.get(flag)})
    banned, gcs, mld, extra = names("banned"), names("gameChanger"), names("massLandDenial"), names("extraTurn")
    two_card, chains = [], []
    for v in raw.get("combos") or []:
        if not v.get("relevant", True):
            continue
        uses = [u["card"]["name"] for u in v["combo"].get("uses", [])]
        if v.get("definitelyTwoCard"):
            two_card.append(" + ".join(uses))
        if v.get("extraTurn"):
            chains.append(" + ".join(uses))
        if v.get("massLandDenial"):
            mld.append(" + ".join(uses))
    reasons = []
    if banned:
        reasons.append("banned in Commander: " + ", ".join(banned))
        lowest = None
    else:
        lowest = 2
        if gcs:
            lowest = 3 if len(gcs) <= 3 else 4
            reasons.append(f"{len(gcs)} Game Changer{'s' if len(gcs) > 1 else ''}: {', '.join(gcs)}"
                           + (" (bracket 3 allows up to 3)" if len(gcs) > 3 else ""))
        if two_card:
            lowest = max(lowest, 3)
            reasons.append(f"two-card combo{'s' if len(two_card) > 1 else ''}: {'; '.join(two_card[:3])}"
                           " (bracket 3 only if it can't come together early)")
        if mld:
            lowest = 4
            reasons.append("mass land denial: " + ", ".join(sorted(set(mld))[:4]))
        if chains:
            lowest = 4
            reasons.append("chains extra turns: " + "; ".join(chains[:3]))
        if lowest == 2:
            reasons.append("no Game Changers, land denial, extra-turn chains or two-card combos "
                           "(bracket 1 if it's built as a gentle theme deck)")
        if extra and not chains:
            reasons.append("extra-turn cards (fine below bracket 4 if not chained): " + ", ".join(extra[:4]))
    tag = raw.get("bracketTag")
    return {"lowest": lowest, "name": BRACKET_NAMES.get(lowest, "not legal") if lowest else "not legal",
            "reasons": reasons, "game_changers": gcs, "land_denial": sorted(set(mld)), "extra_turns": extra,
            "two_card_combos": two_card, "turn_chains": chains,
            "spellbook_tag": SPELLBOOK_TAGS.get(tag, tag)}


def for_builder_deck(commander, deck, **kwargs):
    """Bracket estimate for a deck dict from ``build_deck`` / the app."""
    members = [c["name"] for c in card_db.commander_members(commander)]
    main = [(c["name"], 1) for c in deck["cards"]] + list((deck.get("basics") or {}).items())
    return official_bracket(classify(members, main, **kwargs))


def for_entry(entry, **kwargs):
    """Bracket estimate for an imported tournament decklist."""
    skip = set(entry["commanders"])
    main = [(c["name"], c["count"]) for c in entry["cards"] if c["name"] not in skip]
    return official_bracket(classify(entry["commanders"], main, **kwargs))
