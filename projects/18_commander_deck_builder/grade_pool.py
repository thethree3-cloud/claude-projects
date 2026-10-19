"""Grade the cards you own against a commander.

The grade comes from data, not from the model:
  - legality: Commander-legal and inside the commander's color identity
  - EDHREC: share of this commander's real decks that run the card (inclusion)
  - Game Changers: Scryfall's flag, checked against the bracket you play
Claude only writes a one-line reason per legal card, from facts it is given.
It never sets a tier or a number. ``--no-llm`` skips it (free, repeatable).

Tiers (inclusion = share of this commander's EDHREC decks running the card):
  Core       >= 40%     the deck almost always plays it
  Strong     >= 15%
  Playable   on EDHREC's lists for this commander, under 15%
  Filler     legal, but not on EDHREC's lists for this commander
  Not legal  outside the color identity, or not legal in Commander

Usage:
    python grade_pool.py "Kestia, the Cultivator"
    python grade_pool.py kestia --binder "Born of the Gods" --bracket 2
    python grade_pool.py kestia --no-llm --json
"""

import argparse
import json
import sys

import anthropic
from pydantic import BaseModel, ValidationError

import card_db
import commander_lookup
import edhrec_client
from collection import Collection
from scan_binder import ScanError, make_client

MODEL = "claude-opus-5-5"
CORE_INCLUSION = 0.40
STRONG_INCLUSION = 0.15
TIERS = ("Core", "Strong", "Playable", "Filler", "Not legal")
COLOR_NAMES = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}


# ---------------------------------------------------------------------------
# Deterministic grading
# ---------------------------------------------------------------------------


def grade_card(card, commander_identity, edhrec=None, bracket=None):
    """Grade one owned card. ``card`` is a ``CardDB`` row, ``edhrec`` its EDHREC entry or None."""
    notes = []
    off_colors = [c for c in card["color_identity"] if c not in commander_identity]
    if off_colors:
        notes.append("outside the commander's colors (needs " + ", ".join(COLOR_NAMES[c] for c in off_colors) + ")")
    if not card["legal_commander"]:
        notes.append("not legal in Commander")

    if notes:
        tier = "Not legal"
    elif edhrec is None:
        tier = "Filler"
    elif edhrec["inclusion"] >= CORE_INCLUSION:
        tier = "Core"
    elif edhrec["inclusion"] >= STRONG_INCLUSION:
        tier = "Strong"
    else:
        tier = "Playable"

    if card["game_changer"]:
        notes.append("Game Changer" + (f" - not allowed in bracket {bracket}" if bracket and bracket <= 2 else ""))

    return {
        "name": card["name"],
        "tier": tier,
        "inclusion": edhrec["inclusion"] if edhrec else None,
        "synergy": edhrec["synergy"] if edhrec else None,
        "high_synergy": bool(edhrec and edhrec["high_synergy"]),
        "game_changer": bool(card["game_changer"]),
        "usd": card["usd"],
        "type_line": card["type_line"],
        "oracle_text": card["oracle_text"],
        "notes": notes,
        "reason": None,
    }


def bracket_fit(graded):
    """Lowest bracket the legal Game Changers allow: 0 -> 1-2, up to 3 -> 3, more -> 4-5."""
    gcs = [g["name"] for g in graded if g["game_changer"] and g["tier"] != "Not legal"]
    fits = "1-2" if not gcs else "3" if len(gcs) <= 3 else "4-5"
    return {"game_changers": gcs, "lowest_bracket": fits}


def grade_pool(commander, names, db, edhrec_cards, bracket=None):
    """Grade every owned card name. ``commander`` is the commander's ``CardDB`` row."""
    identity = commander["color_identity"]
    by_name = {c["name"]: c for c in edhrec_cards}
    graded, missing = [], []
    for name in sorted(set(names)):
        card = db.get(name)
        if card is None:
            missing.append(name)
            continue
        if card["name"] == commander["name"]:
            continue  # the commander itself isn't one of the 99
        graded.append(grade_card(card, identity, by_name.get(card["name"]), bracket))
    graded.sort(key=lambda g: (TIERS.index(g["tier"]), -(g["inclusion"] or 0), g["name"]))

    legal = [g for g in graded if g["tier"] != "Not legal"]
    return {
        "commander": {
            "name": commander["name"],
            "color_identity": identity,
            "oracle_text": commander["oracle_text"],
        },
        "bracket": bracket,
        "cards": graded,
        "missing": missing,
        "summary": {
            "owned": len(graded),
            "legal": len(legal),
            "by_tier": {t: sum(g["tier"] == t for g in graded) for t in TIERS},
            "legal_value_usd": round(sum(g["usd"] or 0 for g in legal), 2),
            **bracket_fit(graded),
        },
    }


# ---------------------------------------------------------------------------
# Reasons (Claude)
# ---------------------------------------------------------------------------


class CardReason(BaseModel):
    name: str
    reason: str


class Reasons(BaseModel):
    reasons: list[CardReason]


REASONS_SCHEMA = {
    "type": "object",
    "properties": {
        "reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["name", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["reasons"],
    "additionalProperties": False,
}

REASONS_PROMPT = """You are helping a Magic: The Gathering player see how cards they already own fit a Commander deck.

Commander: {name}
Commander rules text:
{oracle}

Each card below already has a tier decided from data: "inclusion" is the share of this commander's decks on EDHREC that play it, "synergy" is how much more often it appears with this commander than in other decks of these colors, and null means EDHREC doesn't list it for this commander.

For every card, write one plain sentence (at most 25 words) explaining why it lands in its tier, based on its rules text and the commander's.
- Do not change a tier or state numbers that aren't given.
- Say plainly when a card is weak for this commander; don't oversell.
- Mention only the cards listed.

Cards:
{cards}"""


def _facts(card):
    return {
        "name": card["name"],
        "tier": card["tier"],
        "inclusion": None if card["inclusion"] is None else f"{card['inclusion']:.0%}",
        "synergy": None if card["synergy"] is None else f"{card['synergy']:+.0%}",
        "type": card["type_line"],
        "rules_text": card["oracle_text"],
    }


def add_reasons(result, client, model=MODEL):
    """Fill ``reason`` for each legal card with one Claude call. Returns how many got one."""
    legal = [c for c in result["cards"] if c["tier"] != "Not legal"]
    if not legal:
        return 0
    prompt = REASONS_PROMPT.format(
        name=result["commander"]["name"],
        oracle=result["commander"]["oracle_text"],
        cards=json.dumps([_facts(c) for c in legal], indent=1),
    )
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": REASONS_SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIConnectionError as exc:
        raise ScanError(f"Could not reach the Claude API: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise ScanError(f"Claude API error {exc.status_code}: {exc.message}") from exc

    if response.stop_reason == "refusal":
        raise ScanError("Claude declined to write the reasons.")
    text = "".join(b.text for b in response.content if b.type == "text")
    try:
        if response.stop_reason == "max_tokens":
            raise ValueError("answer cut off")
        reasons = Reasons.model_validate_json(text).reasons
    except (ValueError, ValidationError) as exc:
        raise ScanError(f"Claude's reasons were cut off or unreadable: {exc}") from exc

    # Only accept reasons for cards we sent; anything else is ignored.
    by_name = {c["name"]: c for c in legal}
    filled = 0
    for r in reasons:
        card = by_name.get(r.name)
        if card and card["reason"] is None:
            card["reason"] = r.reason.strip()
            filled += 1
    return filled


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_report(result):
    cmd, s = result["commander"], result["summary"]
    lines = [
        f"# Your cards for {cmd['name']} ({''.join(cmd['color_identity'])})",
        "",
        f"{s['legal']} of {s['owned']} owned cards are legal in this deck "
        f"(${s['legal_value_usd']:.2f} total). "
        + ", ".join(f"{s['by_tier'][t]} {t}" for t in TIERS if s["by_tier"][t]) + ".",
    ]
    if s["game_changers"]:
        lines.append(f"Game Changers: {', '.join(s['game_changers'])} -> bracket {s['lowest_bracket']} or higher.")
    else:
        lines.append("No Game Changers, so these cards fit any bracket (1-5).")
    if result["missing"]:
        lines.append(f"Not in the card database (skipped): {', '.join(result['missing'])}")

    for tier in TIERS:
        cards = [c for c in result["cards"] if c["tier"] == tier]
        if not cards:
            continue
        lines += ["", f"## {tier} ({len(cards)})", ""]
        if tier == "Not legal":
            lines.append(", ".join(f"{c['name']} ({'; '.join(c['notes'])})" for c in cards))
            continue
        lines += ["| Card | Inclusion | Synergy | Price | Why |", "|---|--:|--:|--:|---|"]
        for c in cards:
            inc = "-" if c["inclusion"] is None else f"{c['inclusion']:.0%}"
            syn = "-" if c["synergy"] is None else f"{c['synergy']:+.0%}"
            price = "n/a" if c["usd"] is None else f"${c['usd']:.2f}"
            why = c["reason"] or ""
            if c["notes"]:
                why = (why + " " if why else "") + f"({'; '.join(c['notes'])})"
            lines.append(f"| {c['name']} | {inc} | {syn} | {price} | {why} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description="Grade your owned cards against a commander.")
    parser.add_argument("commander", help="commander name (fuzzy match is fine)")
    parser.add_argument("--binder", help="only cards from this binder (default: whole collection)")
    parser.add_argument("--bracket", type=int, choices=range(1, 6), help="bracket you play (flags Game Changers)")
    parser.add_argument("--no-llm", action="store_true", help="skip Claude's one-line reasons")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--json", action="store_true", help="output JSON instead of a report")
    args = parser.parse_args(argv)

    col = Collection()
    try:
        names = col.names(binder=args.binder)
    finally:
        col.close()
    if not names:
        where = f"binder '{args.binder}'" if args.binder else "your collection"
        print(f"Error: {where} is empty. Scan pages with scan_binder.py --binder first.", file=sys.stderr)
        return 1

    try:
        db = card_db.open_db()
        commander = db.get(commander_lookup.resolve_commander(args.commander, db))
        page = edhrec_client.parse_commander_page(
            edhrec_client.fetch_commander_page(edhrec_client.slugify(commander["name"]))
        )
        if not page["commander"]["legal_commander"]:
            raise LookupError(f"{commander['name']} is not legal as a commander.")
        result = grade_pool(commander, names, db, page["cards"], args.bracket)
        if not args.no_llm:
            add_reasons(result, make_client(), args.model)
    except (LookupError, edhrec_client.EdhrecError, card_db.BulkDataError, ScanError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2) if args.json else format_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
