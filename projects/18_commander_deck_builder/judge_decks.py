"""Blind pairwise judge: does Claude's deck play better than the baseline's?

Slice 6 measured validity and popularity overlap, which can't say whether a
deck *plays* well. Here a different model (Sonnet 5.5 by default; Opus 5.5
built the decks) reads two unlabeled decklists for the same commander and
budget, scores each, and picks the one it would rather play.

Same decks as Slice 6: each saved Opus trace holds the exact candidate table
Claude saw (names, roles, inclusion, prices from that day) and its final
picks. From the table we rebuild Claude's deck card for card and re-run the
no-LLM baseline on the same table, so both decks share one pool and one set
of prices.

Blind: decks are "Deck A" / "Deck B" with no builder name, strategy text or
per-card reasons, and the builder's role labels are left out. Each case is
judged twice with the order swapped; a deck wins the case only if it wins
both orders, otherwise the case is a split. The split rate shows how much
the verdicts depend on position.

Output (resumable, like eval_decks.py):
    evals/judge/<judge-model>/results.jsonl   one row per case + order
    evals/JUDGE.md                            summary table (--summary)

Usage:
    python judge_decks.py --cases kestia-150,krenko-50     # pilot
    python judge_decks.py                                  # all 30 cases, both orders
    python judge_decks.py --summary
"""

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace

import anthropic
from pydantic import BaseModel, Field, ValidationError

import build_deck
import card_db
import llm_deck
from eval_decks import EVAL_DIR, RUNS_DIR, wilson
from scan_binder import ScanError, make_client

JUDGE_MODEL = "claude-sonnet-5-5"
BUILDER_VARIANT = "claude-opus-5-5"
JUDGE_DIR = EVAL_DIR / "judge"
MAX_TOKENS = 32000
ORACLE_CHARS = 160
CRITERIA = ("synergy", "mana", "interaction", "card_flow", "win_path")
TYPE_ORDER = ("Creature", "Planeswalker", "Instant", "Sorcery", "Artifact", "Enchantment", "Battle", "Land")

_ROW = re.compile(r"^(c\d+) \| (.+?) \| (\w+) \| (\d+%|not listed) \| (\$[\d.]+|owned) \| ?(.*)$")
_BUDGET = re.compile(r"Budget: \$([\d.]+) in total\. The commanders? costs? \$([\d.]+)")


class DeckScore(BaseModel):
    synergy: int = Field(ge=1, le=10)
    mana: int = Field(ge=1, le=10)
    interaction: int = Field(ge=1, le=10)
    card_flow: int = Field(ge=1, le=10)
    win_path: int = Field(ge=1, le=10)


class Verdict(BaseModel):
    deck_a: DeckScore
    deck_b: DeckScore
    winner: str  # "A", "B" or "tie"
    confidence: str  # "low", "medium", "high"
    reason: str


_SCORE_SCHEMA = {
    "type": "object",
    "properties": {c: {"type": "integer"} for c in CRITERIA},
    "required": list(CRITERIA),
    "additionalProperties": False,
}
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "deck_a": _SCORE_SCHEMA,
        "deck_b": _SCORE_SCHEMA,
        "winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "reason": {"type": "string"},
    },
    "required": ["deck_a", "deck_b", "winner", "confidence", "reason"],
    "additionalProperties": False,
}

PROMPT = """You are an experienced Commander (EDH) player judging two decks for the same commander, built with the same card pool and the same budget (${budget:.0f}, commander included). Both are legal 100-card decks. Judge only the cards; nothing else is known about who built them.

Commander: {commander}
{oracle}

Score each deck from 1 to 10 on:
- synergy: how well the cards serve this commander's plan
- mana: land count, color fixing, ramp and mana curve
- interaction: removal, answers and protection
- card_flow: card draw, card advantage, recursion
- win_path: a clear, reachable way to win

Then pick the deck you would rather play at a casual-to-focused table ("tie" only if you truly can't separate them), give your confidence, and explain the deciding differences in at most 80 words, naming specific cards.

Deck A ({count_a} cards besides the commander):
{deck_a}

Deck B ({count_b} cards besides the commander):
{deck_b}"""


# ---------------------------------------------------------------------------
# Rebuild both decks from a saved trace
# ---------------------------------------------------------------------------


def parse_trace(trace):
    """Saved Opus transcript -> ``{"budget", "commander_cost", "rows", "picks"}``.

    ``rows`` is the candidate table as Claude saw it; ``picks`` the final
    (validated) pick list."""
    prompt = trace[0]["content"]
    match = _BUDGET.search(prompt)
    if not match:
        raise ValueError("budget line not found in the trace prompt")
    rows = []
    for line in prompt.split("Candidate cards", 1)[1].splitlines():
        if m := _ROW.match(line.strip()):
            cid, name, role, inc, price, text = m.groups()
            rows.append({
                "id": cid, "name": name, "role": role, "oracle_text": text,
                "inclusion": 0.0 if inc == "not listed" else int(inc[:-1]) / 100,
                "usd": None if price == "owned" else float(price[1:]),
                "owned": price == "owned", "listed": inc != "not listed",
            })
    final = [m for m in trace if m["role"] == "assistant"][-1]["content"]
    picks = [SimpleNamespace(**p) for p in json.loads(final)["picks"]]
    return {"budget": float(match.group(1)), "commander_cost": float(match.group(2)), "rows": rows, "picks": picks}


def rebuild_decks(case, trace, db):
    """Both decks for one case from the same pool: ``(commander, claude_deck, baseline_deck)``."""
    parsed = parse_trace(trace)
    commander = db.get(case["commander"])
    info = db.get_many([r["name"] for r in parsed["rows"]])
    pool, by_id = [], {}
    for r in parsed["rows"]:
        card = {**r, "cost": 0.0 if r["owned"] else r["usd"],
                "color_identity": info[r["name"]]["color_identity"] if r["name"] in info else ""}
        pool.append(card)
        by_id[r["id"]] = card
    claude, problems = llm_deck.assemble(commander, by_id, parsed["picks"], parsed["commander_cost"])
    if problems:
        raise ValueError(f"saved picks no longer assemble: {problems[0]}")
    baseline = build_deck.build_deck(commander, pool, parsed["budget"], commander_cost=parsed["commander_cost"])
    return commander, claude, baseline


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def _main_type(type_line):
    front = type_line.split(" // ")[0]
    return next((t for t in TYPE_ORDER if t in front), "Other")


def deck_text(deck, db):
    """Neutral decklist: grouped by card type, sorted by mana value, short rules
    text. No builder role labels, reasons, inclusion or prices."""
    rows = []
    for c in deck["cards"]:
        card = db.get(c["name"])
        text = " ".join(card["oracle_text"].split())
        if len(text) > ORACLE_CHARS:
            text = text[: ORACLE_CHARS - 3] + "..."
        rows.append((_main_type(card["type_line"]), card["cmc"], card["name"], card["type_line"], text))
    # Counted facts first, so the judge doesn't have to count (it miscounted lands in the pilot).
    basics_n = sum(deck["basics"].values())
    nonbasic_lands = sum(r[0] == "Land" for r in rows)
    spells = [r for r in rows if r[0] != "Land"]
    avg_mv = sum(r[1] for r in spells) / len(spells) if spells else 0.0
    lines = [f"Facts: {nonbasic_lands + basics_n} lands ({nonbasic_lands} nonbasic, {basics_n} basic), "
             f"{len(spells)} nonland cards, average mana value of nonland cards {avg_mv:.2f}."]
    for kind in (*TYPE_ORDER, "Other"):
        group = sorted(r for r in rows if r[0] == kind)
        if group:
            lines.append(f"{kind} ({len(group)}):")
            lines += [f"- {name} [MV {cmc:g}, {tl}]: {text}" for _, cmc, name, tl, text in group]
    basics = ", ".join(f"{n} {b}" for b, n in sorted(deck["basics"].items()))
    lines.append(f"Basic lands: {basics or 'none'}")
    return "\n".join(lines)


def judge_prompt(commander, budget, first, second, db):
    return PROMPT.format(
        budget=budget, commander=commander["name"], oracle=commander["oracle_text"],
        count_a=len(first["cards"]) + sum(first["basics"].values()), deck_a=deck_text(first, db),
        count_b=len(second["cards"]) + sum(second["basics"].values()), deck_b=deck_text(second, db),
    )


# ---------------------------------------------------------------------------
# Judge call
# ---------------------------------------------------------------------------


def ask_judge(client, prompt, model=JUDGE_MODEL, effort="high"):
    """One judge call -> ``(Verdict, usage_dict, served_model)``."""
    try:
        with client.beta.messages.stream(
            model=model,
            max_tokens=MAX_TOKENS,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            message = stream.get_final_message()
    except anthropic.APIConnectionError as exc:
        raise ScanError(f"Could not reach the Claude API: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise ScanError(f"Claude API error {exc.status_code}: {exc.message}") from exc
    if message.stop_reason == "refusal":
        raise ScanError("The judge declined.")
    if message.stop_reason == "max_tokens":
        raise ScanError("The judge's answer was cut off (max_tokens).")
    text = "".join(b.text for b in message.content if b.type == "text")
    try:
        verdict = Verdict.model_validate_json(text)
    except ValidationError as exc:
        raise ScanError(f"Unreadable verdict: {exc}") from exc
    usage = {}
    llm_deck._add_usage(usage, message.usage)
    return verdict, usage, getattr(message, "model", model)


def prepare_call(case, trace, db, order):
    """Rebuild both decks and write the prompt for one order ("claude_first" or
    "baseline_first"). Uses the database, so it runs on the main thread."""
    commander, claude, baseline = rebuild_decks(case, trace, db)
    budget = parse_trace(trace)["budget"]
    first, second = (claude, baseline) if order == "claude_first" else (baseline, claude)
    shared = len({c["name"] for c in claude["cards"]} & {c["name"] for c in baseline["cards"]})
    return {"case": case["id"], "order": order, "prompt": judge_prompt(commander, budget, first, second, db),
            "shared_cards": shared}


def finish_call(call, verdict, usage, served, model=JUDGE_MODEL):
    """Turn "A"/"B" back into "claude"/"baseline" -> result row."""
    claude_first = call["order"] == "claude_first"
    label = {"A": "claude" if claude_first else "baseline", "B": "baseline" if claude_first else "claude",
             "tie": "tie"}
    return {
        "prompt_id": call["case"], "order": call["order"], "judge": served, "winner": label[verdict.winner],
        "confidence": verdict.confidence, "reason": verdict.reason,
        "scores": {label["A"]: verdict.deck_a.model_dump(), label["B"]: verdict.deck_b.model_dump()},
        "shared_cards": call["shared_cards"], "usage": usage, "cost_usd": llm_deck.estimated_cost(usage, model),
    }


def judge_case(case, trace, db, client, order, model=JUDGE_MODEL, effort="high"):
    """Judge one case in one order -> result row."""
    call = prepare_call(case, trace, db, order)
    return finish_call(call, *ask_judge(client, call["prompt"], model, effort), model=model)


# ---------------------------------------------------------------------------
# Runs + summary
# ---------------------------------------------------------------------------


def eval_cases():
    """Slice 6 cases that have a saved, valid Opus trace."""
    traces = RUNS_DIR / BUILDER_VARIANT / "traces"
    rows = [json.loads(line) for line in (RUNS_DIR / BUILDER_VARIANT / "results.jsonl").read_text().splitlines()
            if line.strip()]
    cases = []
    for row in rows:
        path = traces / f"{row['prompt_id']}.json"
        if row["status"] == "ok" and path.exists():
            cases.append({"id": row["prompt_id"], "commander": row["tags"][0], "trace": path})
    return sorted(cases, key=lambda c: c["id"])


def run(cases, client, db, model=JUDGE_MODEL, effort="high", workers=4, out_dir=None, log=print):
    out = Path(out_dir or JUDGE_DIR / model)
    out.mkdir(parents=True, exist_ok=True)
    results = out / "results.jsonl"
    done = set()
    if results.exists():
        done = {(r["prompt_id"], r["order"]) for r in map(json.loads, results.read_text().splitlines()) if r}
    todo = [(c, o) for c in cases for o in ("claude_first", "baseline_first") if (c["id"], o) not in done]
    log(f"{len(todo)} judge calls to make ({len(done)} already done).")
    calls = []
    for case, order in todo:  # database work stays on this thread
        try:
            calls.append(prepare_call(case, json.loads(case["trace"].read_text()), db, order))
        except ValueError as exc:
            log(f"  {case['id']} {order}: SKIPPED {exc}")

    failures = len(todo) - len(calls)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(ask_judge, client, call["prompt"], model, effort): call for call in calls}
        for future in as_completed(futures):
            call = futures[future]
            try:
                row = finish_call(call, *future.result(), model=model)
            except ScanError as exc:
                failures += 1
                log(f"  {call['case']} {call['order']}: FAILED {exc}")
                continue
            with results.open("a") as f:  # only this thread writes
                f.write(json.dumps(row) + "\n")
            log(f"  {call['case']} {call['order']}: {row['winner']} ({row['confidence']}), ${row['cost_usd'] or 0:.3f}")
    return failures


def summarize(rows):
    """Per-case verdicts (both orders must agree) + score means."""
    by_case = {}
    for r in rows:
        by_case.setdefault(r["prompt_id"], {})[r["order"]] = r
    complete = {cid: o for cid, o in by_case.items() if len(o) == 2}
    outcome = {"claude": 0, "baseline": 0, "split": 0}
    for orders in complete.values():
        winners = {o["winner"] for o in orders.values()}
        outcome[winners.pop() if len(winners) == 1 and "tie" not in winners else "split"] += 1
    n = len(complete)
    calls = [r for orders in complete.values() for r in orders.values()]
    first_wins = sum((r["order"] == "claude_first") == (r["winner"] == "claude") for r in calls if r["winner"] != "tie")
    decided = sum(r["winner"] != "tie" for r in calls)
    means = {}
    for side in ("claude", "baseline"):
        means[side] = {c: round(sum(r["scores"][side][c] for r in calls) / len(calls), 2) if calls else 0.0
                       for c in CRITERIA}
    return {
        "cases": n, **outcome,
        "claude_rate": outcome["claude"] / n if n else 0.0, "claude_ci": wilson(outcome["claude"], n),
        "baseline_rate": outcome["baseline"] / n if n else 0.0, "baseline_ci": wilson(outcome["baseline"], n),
        "first_position_win_rate": first_wins / decided if decided else 0.0,
        "means": means, "cost_usd": round(sum(r["cost_usd"] or 0 for r in calls), 2),
    }


def summary_markdown(s, model):
    ci = lambda lo_hi: f"{lo_hi[0]:.0%}-{lo_hi[1]:.0%}"  # noqa: E731
    lines = [
        f"# Blind pairwise judge ({model})",
        "",
        f"{s['cases']} cases (10 commanders x 3 budgets), each judged twice with the deck order swapped. "
        "A deck wins a case only if it wins both orders.",
        "",
        "| Outcome | Cases | Share (95% CI) |",
        "|---|--:|--:|",
        f"| Claude (Opus 5.5) deck wins | {s['claude']} | {s['claude_rate']:.0%} ({ci(s['claude_ci'])}) |",
        f"| Baseline (no LLM) deck wins | {s['baseline']} | {s['baseline_rate']:.0%} ({ci(s['baseline_ci'])}) |",
        f"| Split (orders disagree, or a tie) | {s['split']} | {s['split'] / s['cases'] if s['cases'] else 0:.0%} |",
        "",
        f"Position check: the deck shown first won {s['first_position_win_rate']:.0%} of decided calls "
        "(50% = no position bias).",
        "",
        "| Mean score (1-10) | " + " | ".join(CRITERIA) + " |",
        "|---|" + "--:|" * len(CRITERIA),
    ]
    for side, title in (("claude", "Claude deck"), ("baseline", "Baseline deck")):
        lines.append(f"| {title} | " + " | ".join(f"{s['means'][side][c]:.1f}" for c in CRITERIA) + " |")
    lines += ["", f"Judge cost: ${s['cost_usd']:.2f}."]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Blind pairwise judge: Claude deck vs baseline deck.")
    parser.add_argument("--cases", help="comma-separated case ids (default: every saved Opus case)")
    parser.add_argument("--model", default=JUDGE_MODEL, help="judge model (use one that didn't build the decks)")
    parser.add_argument("--effort", default="high", choices=("low", "medium", "high", "xhigh", "max"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--summary", action="store_true", help="print the summary and write evals/JUDGE.md")
    args = parser.parse_args(argv)

    out = JUDGE_DIR / args.model
    if args.summary:
        path = out / "results.jsonl"
        if not path.exists():
            print(f"Error: no results in {path}.", file=sys.stderr)
            return 1
        text = summary_markdown(summarize([json.loads(l) for l in path.read_text().splitlines() if l.strip()]),
                                args.model)
        (EVAL_DIR / "JUDGE.md").write_text(text + "\n")
        print(text)
        return 0

    cases = eval_cases()
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
        missing = wanted - {c["id"] for c in cases}
        if missing:
            print(f"Error: no saved trace for {', '.join(sorted(missing))}.", file=sys.stderr)
            return 1
    try:
        client = make_client().with_options(timeout=600, max_retries=4)
        db = card_db.CardDB(card_db.ensure_db(log=lambda *_: None))
    except (ScanError, card_db.BulkDataError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    failures = run(cases, client, db, args.model, args.effort, args.workers, out, log=lambda m: print(m, file=sys.stderr))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
