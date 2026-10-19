"""Slice 5: Claude picks the deck, code keeps it honest.

Claude sees the same checked candidate pool the baseline builder uses (legal,
inside the color identity, priced or owned), as a table of IDs with role,
EDHREC inclusion, price and rules text. It can only answer with IDs from that
table, so it can't invent or misspell a card. Code then adds basic lands,
prices the deck and runs the full validator. Any errors are sent back to
Claude to fix (at most ``MAX_ATTEMPTS`` tries); an invalid deck is never
shown as done.

The report compares Claude's deck with the no-LLM baseline for the same
commander and budget, plus the estimated API cost of the run.

Usage:
    python llm_deck.py "Kestia, the Cultivator" --budget 100
    python llm_deck.py kestia --budget 100 --owned --out kestia_llm.txt
    python llm_deck.py kestia --budget 50 --model claude-sonnet-5-5
"""

import argparse
import json
import sys
from pathlib import Path

import anthropic
from pydantic import BaseModel, ValidationError

import build_deck
import card_db
import commander_lookup
import edhrec_client
from collection import Collection
from scan_binder import ScanError, make_client
from validate_deck import validate_text

MODEL = "claude-opus-5-5"
MAX_ATTEMPTS = 3
MAX_TOKENS = 32000
ORACLE_CHARS = 220
# USD per million tokens (input, output) for the cost estimate.
PRICES = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00), "claude-haiku-5-5": (0.10, 0.50)}

PICKS_SCHEMA = {
    "type": "object",
    "properties": {
        "strategy": {"type": "string"},
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["id", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["strategy", "picks"],
    "additionalProperties": False,
}


class Pick(BaseModel):
    id: str
    reason: str


class Picks(BaseModel):
    strategy: str
    picks: list[Pick]


PROMPT = """Build a Commander (EDH) deck for {name}.

Commander rules text:
{oracle}

Budget: ${budget:.2f} in total. The commander costs ${commander_cost:.2f}, so the cards you pick may cost at most ${money:.2f} together.
Cards marked "owned" cost $0. Basic lands are free and are added automatically after your picks to bring the deck to 99 cards plus the commander.

Rules for your answer:
- Pick ONLY by id from the table below. Each id at most once.
- Pick between {min_picks} and {max_picks} cards. Nonbasic lands you pick count toward the land total; aim for {land_lo}-{land_hi} lands overall including the automatic basics.
- Aim for about 10 ramp, 10 card draw, 8 removal and 2-3 board wipes, then the cards that best fit the commander's plan.
- "inclusion" is the share of this commander's real decks (EDHREC) that play the card. It is a strong signal, not a rule: favor cards that work with the commander's text.
- Keep a running total so the picks stay within ${money:.2f}.
- Give a one-line reason per pick (at most 12 words) and a two-sentence strategy.

Candidate cards (id | name | role | inclusion | price | rules text):
{table}"""

FEEDBACK = """Your deck failed the checks. Fix every problem below and answer with the complete corrected pick list (same format).

Problems:
{errors}

Current picks cost ${cost:.2f}; the limit for picks is ${money:.2f}."""


# ---------------------------------------------------------------------------
# Prompt pieces
# ---------------------------------------------------------------------------


def card_table(pool):
    """``(table_text, {id: card})`` with stable ids c1..cN (pool order)."""
    by_id, lines = {}, []
    for i, c in enumerate(pool, 1):
        cid = f"c{i}"
        by_id[cid] = c
        price = "owned" if c["owned"] else f"${c['usd']:.2f}"
        inc = f"{c['inclusion']:.0%}" if c["listed"] else "not listed"
        text = " ".join(c.get("oracle_text", "").split())
        if len(text) > ORACLE_CHARS:
            text = text[: ORACLE_CHARS - 3] + "..."
        lines.append(f"{cid} | {c['name']} | {c['role']} | {inc} | {price} | {text}")
    return "\n".join(lines), by_id


def min_picks(pool, money):
    """Fewest picks to demand: the 62 spell slots, or as many cards as the money can buy at all."""
    spell_slots = build_deck.DECK_SIZE - 1 - build_deck.LAND_TARGET
    affordable, total = 0, 0.0
    for cost in sorted(c["cost"] for c in pool if c["role"] != "land"):
        if total + cost > money + 1e-9:
            break
        total += cost
        affordable += 1
    return min(spell_slots, affordable)


def first_prompt(commander, budget, commander_cost, table, minimum=None):
    spell_slots = build_deck.DECK_SIZE - 1 - build_deck.LAND_TARGET
    return PROMPT.format(
        name=commander["name"],
        oracle=commander["oracle_text"],
        budget=budget,
        commander_cost=commander_cost,
        money=budget - commander_cost,
        min_picks=spell_slots if minimum is None else minimum,
        max_picks=build_deck.DECK_SIZE - 1,
        land_lo=34,
        land_hi=38,
        table=table,
    )


# ---------------------------------------------------------------------------
# Picks -> deck
# ---------------------------------------------------------------------------


def assemble(commander, by_id, picks, commander_cost=0.0, minimum=0):
    """Turn picks into a deck dict (same shape as ``build_deck``). Returns ``(deck, problems)``.

    Problems here are things the validator can't see: unknown ids, repeated
    ids, too many or too few picks (an empty pick list would otherwise be a
    "legal" deck of 99 basic lands). Basics fill the deck to 99 cards.
    """
    problems, cards, seen = [], [], set()
    for p in picks:
        card = by_id.get(p.id)
        if card is None:
            problems.append(f"Unknown id {p.id!r}: pick only ids from the table.")
            continue
        if p.id in seen:
            problems.append(f"{p.id} ({card['name']}) picked more than once.")
            continue
        seen.add(p.id)
        cards.append({**card, "reason": p.reason.strip()})
    if len(cards) < minimum:
        problems.append(f"Only {len(cards)} cards picked; pick at least {minimum} (the budget allows that many).")
    if len(cards) > build_deck.DECK_SIZE - 1:
        problems.append(f"{len(cards)} cards picked; at most {build_deck.DECK_SIZE - 1} fit next to the commander.")
        cards = cards[: build_deck.DECK_SIZE - 1]
    spells = [c for c in cards if c["role"] != "land"]
    basics = build_deck._basics_split(commander["color_identity"], spells, build_deck.DECK_SIZE - 1 - len(cards))
    spent = commander_cost + sum(c["cost"] for c in cards)
    return {"cards": cards, "basics": basics, "spent": round(spent, 2), "warnings": [], "upgrades": []}, problems


# ---------------------------------------------------------------------------
# Claude loop
# ---------------------------------------------------------------------------


def _call(client, model, messages, effort):
    try:
        with client.beta.messages.stream(
            model=model,
            max_tokens=MAX_TOKENS,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": PICKS_SCHEMA}},
            messages=messages,
        ) as stream:
            return stream.get_final_message()
    except anthropic.APIConnectionError as exc:
        raise ScanError(f"Could not reach the Claude API: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise ScanError(f"Claude API error {exc.status_code}: {exc.message}") from exc


def _parse(message):
    if message.stop_reason == "refusal":
        raise ScanError("Claude declined to build this deck.")
    text = "".join(b.text for b in message.content if b.type == "text")
    try:
        if message.stop_reason == "max_tokens":
            raise ValueError("answer cut off (max_tokens)")
        return Picks.model_validate_json(text)
    except (ValueError, ValidationError) as exc:
        raise ScanError(f"Claude's pick list was cut off or unreadable: {exc}") from exc


def _add_usage(total, usage):
    for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        total[key] = total.get(key, 0) + (getattr(usage, key, 0) or 0)


def estimated_cost(usage, model):
    """USD estimate: cache writes at 1.25x input, cache reads at 0.1x input."""
    if model not in PRICES:
        return None
    p_in, p_out = (p / 1_000_000 for p in PRICES[model])
    return round(
        usage.get("input_tokens", 0) * p_in
        + usage.get("cache_creation_input_tokens", 0) * p_in * 1.25
        + usage.get("cache_read_input_tokens", 0) * p_in * 0.1
        + usage.get("output_tokens", 0) * p_out,
        4,
    )


def build_with_claude(commander, pool, budget, db, client, owned=frozenset(), commander_cost=0.0,
                      model=MODEL, effort="medium", max_attempts=MAX_ATTEMPTS, log=print):
    """Ask Claude for a deck, validate, feed errors back. Returns a result dict with ``ok``."""
    table, by_id = card_table(pool)
    money = budget - commander_cost
    minimum = min_picks(pool, money)
    messages = [{
        "role": "user",
        "content": [{
            "type": "text",
            "text": first_prompt(commander, budget, commander_cost, table, minimum),
            "cache_control": {"type": "ephemeral"},  # retries re-send this; cache it
        }],
    }]
    usage, attempts = {}, []
    transcript = [{"role": "user", "content": messages[0]["content"][0]["text"]}]
    for attempt in range(1, max_attempts + 1):
        log(f"Attempt {attempt}: asking {model} for a deck...")
        message = _call(client, model, messages, effort)
        _add_usage(usage, message.usage)
        transcript.append({"role": "assistant", "content": "".join(
            b.text for b in message.content if b.type == "text"), "model": getattr(message, "model", None)})
        picks = _parse(message)
        deck, problems = assemble(commander, by_id, picks.picks, commander_cost, minimum)
        text = build_deck.import_text(commander, deck)
        check = validate_text(text, db, budget=budget, owned=owned)
        errors = problems + check["errors"]
        attempts.append({"attempt": attempt, "errors": errors, "picks": len(picks.picks),
                         "served_model": getattr(message, "model", None)})
        if not errors:
            deck["warnings"] = check["warnings"]
            return {"ok": True, "deck": deck, "strategy": picks.strategy, "text": text, "stats": check["stats"],
                    "attempts": attempts, "usage": usage, "cost_usd": estimated_cost(usage, model), "model": model,
                    "transcript": transcript}
        log(f"  {len(errors)} problem(s): {errors[0]}" + (" ..." if len(errors) > 1 else ""))
        picks_cost = deck["spent"] - commander_cost
        messages.append({"role": "assistant", "content": message.content})  # passed back unchanged
        feedback = FEEDBACK.format(errors="\n".join(f"- {e}" for e in errors), cost=picks_cost, money=money)
        messages.append({"role": "user", "content": feedback})
        transcript.append({"role": "user", "content": feedback})
    return {"ok": False, "attempts": attempts, "usage": usage, "cost_usd": estimated_cost(usage, model), "model": model,
            "transcript": transcript}


# ---------------------------------------------------------------------------
# Comparison + report
# ---------------------------------------------------------------------------


def deck_summary(deck):
    nonbasic = deck["cards"]
    listed = [c for c in nonbasic if c["listed"]]
    roles = {r: sum(c["role"] == r for c in nonbasic) for r in build_deck.ROLES}
    return {
        "cost": deck["spent"],
        "nonbasic_cards": len(nonbasic),
        "basics": sum(deck["basics"].values()),
        "avg_inclusion": round(sum(c["inclusion"] for c in listed) / len(listed), 3) if listed else 0.0,
        "owned_used": sum(c["owned"] for c in nonbasic),
        "roles": roles,
    }


def format_report(commander, budget, result, baseline):
    deck = result["deck"]
    claude, base = deck_summary(deck), deck_summary(baseline)
    overlap = len({c["name"] for c in deck["cards"]} & {c["name"] for c in baseline["cards"]})
    tries = len(result["attempts"])
    lines = [
        f"# {commander['name']} - ${budget:.0f}, picked by {result['model']}",
        "",
        f"Passed the validator on attempt {tries} of {MAX_ATTEMPTS}."
        + (f" Estimated API cost: ${result['cost_usd']:.2f}." if result["cost_usd"] is not None else ""),
        f"Strategy: {result['strategy']}",
    ]
    for w in deck["warnings"]:
        lines.append(f"Validator warning: {w}")
    lines += [
        "",
        "| | Claude | Baseline (no LLM) |",
        "|---|--:|--:|",
        f"| Cost to buy | ${claude['cost']:.2f} | ${base['cost']:.2f} |",
        f"| Nonbasic cards / basics | {claude['nonbasic_cards']} / {claude['basics']} | {base['nonbasic_cards']} / {base['basics']} |",
        f"| Avg EDHREC inclusion | {claude['avg_inclusion']:.0%} | {base['avg_inclusion']:.0%} |",
        f"| Owned cards used | {claude['owned_used']} | {base['owned_used']} |",
    ]
    for role in ("land", "ramp", "draw", "removal", "wipe", "synergy"):
        lines.append(f"| {role} | {claude['roles'][role]} | {base['roles'][role]} |")
    lines.append(f"| Cards in both decks | {overlap} | |")
    for role in build_deck.ROLES:
        group = [c for c in deck["cards"] if c["role"] == role]
        if not group:
            continue
        lines += ["", f"## {role.capitalize()} ({len(group)})", ""]
        for c in sorted(group, key=lambda c: -c["inclusion"]):
            price = "owned" if c["owned"] else f"${c['usd']:.2f}"
            lines.append(f"- {c['name']} ({price}) - {c['reason']}")
    lines += ["", "Basics: " + ", ".join(f"{n} {b}" for b, n in sorted(deck["basics"].items()))]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description="Claude picks a Commander deck from the checked candidate pool.")
    parser.add_argument("commander")
    parser.add_argument("--budget", type=float, required=True)
    parser.add_argument("--owned", action="store_true", help="cards in your collection cost $0")
    parser.add_argument("--binder", help="with --owned: only this binder")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--effort", default="medium", choices=("low", "medium", "high", "xhigh", "max"))
    parser.add_argument("--out", type=Path, help="write the import list to this file")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    owned = set()
    if args.owned:
        col = Collection()
        try:
            owned = col.names(binder=args.binder)
        finally:
            col.close()

    try:
        db = card_db.open_db()
        commander = db.get(commander_lookup.resolve_commander(args.commander, db))
        page = edhrec_client.parse_commander_page(
            edhrec_client.fetch_commander_page(edhrec_client.slugify(commander["name"]))
        )
        commander_cost = 0.0 if commander["name"] in owned else (commander["usd"] or 0.0)
        if commander_cost > args.budget:
            raise LookupError(f"{commander['name']} alone costs ${commander_cost:.2f}, over the budget.")
        pool = build_deck.candidate_pool(commander, page["cards"], db, owned)
        oracle = db.get_many([c["name"] for c in pool])
        for c in pool:
            c["oracle_text"] = oracle[c["name"]]["oracle_text"]
        log = (lambda *_: None) if args.json else (lambda m: print(m, file=sys.stderr))
        result = build_with_claude(commander, pool, args.budget, db, make_client(), owned, commander_cost,
                                   args.model, args.effort, log=log)
    except (LookupError, edhrec_client.EdhrecError, card_db.BulkDataError, ScanError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not result["ok"]:
        print(f"Error: no valid deck after {MAX_ATTEMPTS} attempts (estimated API cost ${result['cost_usd'] or 0:.2f}).",
              file=sys.stderr)
        for e in result["attempts"][-1]["errors"]:
            print(f"  - {e}", file=sys.stderr)
        return 1

    baseline = build_deck.build_deck(commander, pool, args.budget, owned_mode=args.owned, commander_cost=commander_cost)
    if args.out:
        args.out.write_text(result["text"] + "\n")
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "text"}, indent=2, default=str))
    else:
        print(format_report(commander, args.budget, result, baseline))
        if args.out:
            print(f"\nImport list written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
