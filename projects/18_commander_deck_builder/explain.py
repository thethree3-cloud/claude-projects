"""Claude explains why a card is flagged: one grounded line per spec signal.

Claude gets only facts the code already found for each card (EDHREC trend and
play-rate change, supply, price moves, which rising commanders play it with
high synergy, combos with new cards) and writes one plain sentence per card.
It may not add facts: the prompt forbids it, the answer must name exactly the
cards it was given (others are dropped), and each line is stored next to the
facts it came from. Results are cached per day.

CLI:
    python explain.py            # explain today's top 15 out-of-print signals
    python explain.py --top 10 --model claude-sonnet-5-5
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import anthropic
from pydantic import BaseModel, ValidationError

import card_db
import combos
import edhrec_client
import llm_deck
import watchlist
from scan_binder import ScanError, make_client

MODEL = "claude-opus-5-5"
CACHE_DIR = Path(__file__).parent / "data" / "explain"
MAX_TOKENS = 8000

SCHEMA = {
    "type": "object",
    "properties": {"explanations": {"type": "array", "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "why": {"type": "string"}},
        "required": ["name", "why"], "additionalProperties": False}}},
    "required": ["explanations"],
    "additionalProperties": False,
}

PROMPT = """You explain to a Magic: The Gathering Commander player why each card below was flagged as a possible rising card.

For each card, write ONE plain sentence (at most 30 words) saying why it is getting attention, using ONLY the facts listed for that card. Lead with the strongest reason (a rising commander that plays it, a new combo, scarcity, a price that hasn't moved yet). Do not add facts, prices, card interactions or predictions that are not listed. Do not tell the reader to buy or sell. Use the card names exactly as given.

Cards:
{cards}"""


class Line(BaseModel):
    name: str
    why: str


class Answer(BaseModel):
    explanations: list[Line]


def card_facts(spec, radar=None, spikes=None):
    """``{name: [fact, ...]}`` for each spec row, adding radar and combo links."""
    commanders_for = {}
    for c in radar or []:
        for x in c["cards"]:
            commanders_for.setdefault(x["name"], []).append(
                f"high-synergy card ({x['synergy']:+.0%}) for {c['commander']}, a commander rising on EDHREC "
                f"this week (trend {c['trend']})")
    combo_for = {}
    for e in spikes or []:
        for c in e["combos"][:2]:
            combo_for.setdefault(e["name"], []).append(
                f"completes a combo with new card {c['new_card']}" + (f" ({', '.join(c['produces'][:2])})"
                                                                      if c["produces"] else ""))
    facts = {}
    for r in spec:
        facts[r["name"]] = [f"price ${r['usd']:.2f}", *r["reasons"], *commanders_for.get(r["name"], []),
                            *combo_for.get(r["name"], [])]
    return facts


def explain(facts, client, model=MODEL, effort="low"):
    """``({name: why}, usage, cost_usd)``. Only names that were asked about are kept."""
    if not facts:
        return {}, {}, 0.0
    cards = "\n".join(f"- {name}: " + "; ".join(f) for name, f in facts.items())
    try:
        with client.beta.messages.stream(
            model=model, max_tokens=MAX_TOKENS,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": PROMPT.format(cards=cards)}],
        ) as stream:
            message = stream.get_final_message()
    except anthropic.APIConnectionError as exc:
        raise ScanError(f"Could not reach the Claude API: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise ScanError(f"Claude API error {exc.status_code}: {exc.message}") from exc
    if message.stop_reason == "refusal":
        raise ScanError("Claude declined.")
    if message.stop_reason == "max_tokens":
        raise ScanError("Claude's answer was cut off (max_tokens).")
    text = "".join(b.text for b in message.content if b.type == "text")
    try:
        answer = Answer.model_validate_json(text)
    except ValidationError as exc:
        raise ScanError(f"Unreadable answer: {exc}") from exc
    usage = {}
    llm_deck._add_usage(usage, message.usage)
    lines = {x.name: x.why.strip() for x in answer.explanations if x.name in facts}
    return lines, usage, llm_deck.estimated_cost(usage, model)


def explain_today(db, wl, client, top=15, model=MODEL, date=None, cache_dir=CACHE_DIR, rising=None,
                  radar=None, spikes=None, log=lambda *_: None):
    """Explain today's top out-of-print spec signals (cached per date and model).
    Returns ``{"date", "model", "rows": [{name, why, facts}], "cost_usd", "cached"}``."""
    date = date or dt.date.today().isoformat()
    cache_file = Path(cache_dir) / f"{date}_{model}_{top}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text()) | {"cached": True}
    if rising is None:
        try:
            rising = watchlist.rising_cards(db)
        except edhrec_client.EdhrecError:
            rising = []
    spec = watchlist.spec_signals(db, wl, rising, out_of_print_only=True)[:top]
    if radar is None:
        try:
            radar = watchlist.commander_radar(db)
        except edhrec_client.EdhrecError:
            radar = []
    if spikes is None:
        try:
            spikes = combos.combo_spikes(db, combos.new_cards(db, rising=rising), log=log)
        except combos.ComboError:
            spikes = []
    facts = card_facts(spec, radar, spikes)
    lines, usage, cost = explain(facts, client, model)
    result = {"date": date, "model": model, "cost_usd": cost, "usage": usage,
              "rows": [{"name": n, "why": lines.get(n), "facts": f} for n, f in facts.items()]}
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(result, indent=1))
    return result | {"cached": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Claude explains why each top spec signal is flagged.")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args(argv)
    db = card_db.open_db(log=lambda m: print(m, file=sys.stderr))
    wl = watchlist.WatchList()
    try:
        res = explain_today(db, wl, make_client(), args.top, args.model, log=lambda m: print(m, file=sys.stderr))
    except ScanError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        wl.close()
        db.close()
    for r in res["rows"]:
        print(f"- {r['name']}: {r['why'] or '(no line returned)'}")
    print(f"\n{res['model']}, " + ("cached" if res["cached"] else f"estimated cost ${res['cost_usd'] or 0:.3f}"),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
