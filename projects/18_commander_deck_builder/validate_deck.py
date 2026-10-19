"""Check a Commander decklist against the format rules (Slice 4 validator).

Reads plain decklist text, the format Moxfield / Archidekt import and export
("1 Sol Ring", "1x Sol Ring (CMM) 1", or just "Sol Ring"), so it can check
any deck: the baseline builder's, a future LLM-built one, or your own.
The first card is the commander unless ``--commander`` is given.

Errors (the deck is not legal / not what was asked for):
  - a card name that doesn't exist (catches made-up or misspelled cards)
  - the commander can't be a commander (needs a legendary creature, or
    "can be your commander"); single commanders only for now (no partners
    or backgrounds yet)
  - not exactly 100 cards, commander included
  - more than one copy of a card (except basic lands and cards that say
    "any number" / "up to N")
  - a card outside the commander's color identity
  - a card banned in Commander
  - over ``--budget`` (cards in your collection are free with ``--owned``)
  - Game Changers above what ``--bracket`` allows (0 for 1-2, 3 for 3)
Warnings (legal, but likely to play badly):
  - lands outside 34-38
  - fewer than 8 ramp, 8 draw, or 5 removal cards
  - average mana value of nonland cards above 4
  - cards with no known price when a budget is set

Usage:
    python validate_deck.py deck.txt
    python validate_deck.py deck.txt --budget 100 --owned --bracket 2
    python validate_deck.py deck.txt --json
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import card_db
from build_deck import card_role
from collection import Collection

DECK_SIZE = 100
LAND_RANGE = (34, 38)
MIN_ROLES = {"ramp": 8, "draw": 8, "removal": 5}
MAX_AVG_MANA_VALUE = 4.0
BRACKET_GAME_CHANGER_LIMIT = {1: 0, 2: 0, 3: 3}

_LINE = re.compile(r"^(?:(\d+)\s*x?\s+)?(.+?)(?:\s+\([A-Za-z0-9]+\)(?:\s+\S+)?)?(?:\s+\*[A-Z]+\*)*\s*$")
_SECTION_HEADERS = {"commander", "deck", "mainboard", "main", "companion"}
_STOP_HEADERS = {"sideboard", "maybeboard", "considering", "tokens"}
_COPY_LIMIT = re.compile(r"deck can have (any number of|up to (\w+)) cards named", re.I)
_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def parse_decklist(text):
    """Decklist text -> ``[(count, name)]`` in order. Raises ValueError on a bad line."""
    entries = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("//", "#")):
            continue
        header = line.rstrip(":").strip().lower()
        if header in _STOP_HEADERS:
            break
        if header in _SECTION_HEADERS:
            continue
        match = _LINE.match(line)
        count = int(match.group(1)) if match and match.group(1) else 1
        name = match.group(2).strip() if match else line
        if count < 1 or not name:
            raise ValueError(f"line {number}: can't read {raw!r}")
        entries.append((count, name))
    return entries


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def copy_limit(card):
    """How many copies the deck may have: 1, a number, or None for any number."""
    if card["type_line"].startswith("Basic "):
        return None
    match = _COPY_LIMIT.search(card["oracle_text"])
    if not match:
        return 1
    if match.group(1).lower().startswith("any"):
        return None
    word = match.group(2).lower()
    return int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 1)


def can_be_commander(card):
    """Legendary creature, a legendary card that is a creature off the battlefield
    (Grist, the Hunger Tide), or one whose text says it can be your commander."""
    front = card["type_line"].split(" // ")[0]
    text = card["oracle_text"]
    if "can be your commander" in text:
        return True
    return "Legendary" in front and ("Creature" in front or "creature in addition to its other types" in text)


def validate(entries, db, commander_name=None, budget=None, owned=frozenset(), bracket=None):
    """Check parsed entries. Returns ``{"ok", "errors", "warnings", "stats", ...}``."""
    errors, warnings = [], []

    # Resolve every name exactly; suggest a fix for unknown ones.
    resolved = []  # (count, card)
    for count, name in entries:
        card = db.get(name)
        if card is None:
            guess = db.find_name(name)
            errors.append(f"Unknown card: {name!r}" + (f" (did you mean {guess!r}?)" if guess else ""))
            continue
        resolved.append((count, card))

    # Commander: --commander, else the first card listed.
    commander = None
    if commander_name:
        commander = db.get(commander_name)
        if commander is None:
            errors.append(f"Unknown commander: {commander_name!r}")
        elif not any(card["name"] == commander["name"] for _, card in resolved):
            resolved.insert(0, (1, commander))  # list given without the commander line
    elif resolved:
        commander = resolved[0][1]
    if commander is None:
        return _result(False, errors or ["Decklist is empty."], warnings, {}, None)
    if not can_be_commander(commander):
        errors.append(f"{commander['name']} can't be a commander (not a legendary creature).")
    identity = commander["color_identity"]

    copies = Counter()
    by_name = {}
    for count, card in resolved:
        copies[card["name"]] += count
        by_name[card["name"]] = card

    total = sum(copies.values())
    if total != DECK_SIZE:
        errors.append(f"Deck has {total} cards; Commander needs exactly {DECK_SIZE} (commander included).")

    for name, n in sorted(copies.items()):
        card = by_name[name]
        limit = copy_limit(card)
        if limit is not None and n > limit:
            errors.append(f"{n} copies of {name}; only {limit} allowed.")
        if not card_db.identity_fits(card["color_identity"], identity):
            off = "".join(c for c in card["color_identity"] if c not in identity)
            errors.append(f"{name} is outside {commander['name']}'s colors (has {off}).")
        if not card["legal_commander"]:
            errors.append(f"{name} is banned in Commander.")

    # Budget: cards you own are free; unknown prices can't be counted.
    cost, unpriced = 0.0, []
    for name, n in copies.items():
        card = by_name[name]
        if name in owned or card["type_line"].startswith("Basic "):
            continue
        if card["usd"] is None:
            unpriced.append(name)
        else:
            cost += card["usd"] * n
    if budget is not None:
        if cost > budget + 1e-9:
            errors.append(f"Costs ${cost:.2f} to buy; budget is ${budget:.2f}.")
        if unpriced:
            warnings.append(f"No price known for {len(unpriced)} cards, not counted in the cost: {', '.join(sorted(unpriced))}.")

    game_changers = sorted(name for name in copies if by_name[name]["game_changer"])
    if bracket in BRACKET_GAME_CHANGER_LIMIT and len(game_changers) > BRACKET_GAME_CHANGER_LIMIT[bracket]:
        errors.append(
            f"{len(game_changers)} Game Changers ({', '.join(game_changers)}); bracket {bracket} allows "
            f"{BRACKET_GAME_CHANGER_LIMIT[bracket]}."
        )

    # Playability (warnings only). The commander isn't part of the 99.
    nine_nine = [(by_name[name], n - (name == commander["name"])) for name, n in copies.items()]
    nine_nine = [(card, n) for card, n in nine_nine if n > 0]
    roles = Counter()
    for card, n in nine_nine:
        roles[card_role(card)] += n
    lands = roles["land"]
    if not LAND_RANGE[0] <= lands <= LAND_RANGE[1]:
        warnings.append(f"{lands} lands; most decks run {LAND_RANGE[0]}-{LAND_RANGE[1]}.")
    for role, minimum in MIN_ROLES.items():
        if roles[role] < minimum:
            warnings.append(f"Only {roles[role]} {role} cards; aim for at least {minimum}.")
    spells = [(card, n) for card, n in nine_nine if card_role(card) != "land"]
    spell_count = sum(n for _, n in spells)
    avg_mv = sum(card["cmc"] * n for card, n in spells) / spell_count if spell_count else 0.0
    if avg_mv > MAX_AVG_MANA_VALUE:
        warnings.append(f"Average mana value {avg_mv:.2f} is high (over {MAX_AVG_MANA_VALUE}); the deck may be slow.")

    stats = {
        "cards": total,
        "lands": lands,
        "roles": dict(roles),
        "average_mana_value": round(avg_mv, 2),
        "cost_to_buy": round(cost, 2),
        "game_changers": game_changers,
        "lowest_bracket": "1-2" if not game_changers else "3" if len(game_changers) <= 3 else "4-5",
    }
    return _result(not errors, errors, warnings, stats, commander["name"])


def _result(ok, errors, warnings, stats, commander):
    return {"ok": ok, "commander": commander, "errors": errors, "warnings": warnings, "stats": stats}


def validate_text(text, db, **kwargs):
    """Parse + validate. A line that can't be read is reported as an error."""
    try:
        entries = parse_decklist(text)
    except ValueError as exc:
        return _result(False, [str(exc)], [], {}, None)
    return validate(entries, db, **kwargs)


# ---------------------------------------------------------------------------
# Report / CLI
# ---------------------------------------------------------------------------


def format_report(result):
    lines = [f"{'PASS' if result['ok'] else 'FAIL'}: {result['commander'] or 'deck'}"]
    s = result["stats"]
    if s:
        roles = s["roles"]
        lines.append(
            f"{s['cards']} cards, {s['lands']} lands, {roles.get('ramp', 0)} ramp, {roles.get('draw', 0)} draw, "
            f"{roles.get('removal', 0)} removal, {roles.get('wipe', 0)} wipes; average mana value "
            f"{s['average_mana_value']:.2f}; ${s['cost_to_buy']:.2f} to buy; lowest bracket {s['lowest_bracket']}."
        )
    for e in result["errors"]:
        lines.append(f"  ERROR: {e}")
    for w in result["warnings"]:
        lines.append(f"  warning: {w}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check a Commander decklist against the format rules.")
    parser.add_argument("decklist", type=Path, help="decklist text file (Moxfield / Archidekt format)")
    parser.add_argument("--commander", help="commander name, if it isn't the first card in the list")
    parser.add_argument("--budget", type=float, help="max USD to buy the cards you don't own")
    parser.add_argument("--owned", action="store_true", help="cards in your collection cost $0")
    parser.add_argument("--bracket", type=int, choices=range(1, 6), help="bracket the deck must fit")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        text = args.decklist.read_text()
        db = card_db.open_db()
    except (OSError, card_db.BulkDataError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    owned = set()
    if args.owned:
        col = Collection()
        try:
            owned = col.names()
        finally:
            col.close()

    result = validate_text(text, db, commander_name=args.commander, budget=args.budget, owned=owned, bracket=args.bracket)
    print(json.dumps(result, indent=2) if args.json else format_report(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
