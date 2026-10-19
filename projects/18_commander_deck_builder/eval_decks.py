"""Slice 6: evaluate Claude's decks against the no-LLM baseline.

Cases: 10 commanders x 3 budgets (approved 2026-10-18). Every metric is a
free code check, no AI judge:

  valid_first   deck passes the validator on the first try (headline)
  valid         passes within 3 tries (baseline: always tried once)
  budget_use    cost to buy / budget (never over: an over-budget deck is invalid)
  avg_overlap   Jaccard overlap of nonbasic cards with EDHREC's average deck
  inclusion     mean EDHREC inclusion of the deck's listed cards
  roles_ok      lands 34-38, ramp >= 8, draw >= 8, removal >= 5 (no validator warning)

Caveat: avg_overlap and inclusion reward copying popularity, which is what
the baseline does by design, so they favor it. Quality means are over valid
decks only; the count is reported next to them.

Output (one directory per variant, rows written as each case finishes, so a
re-run resumes where it stopped):
    evals/runs/<variant>/results.jsonl   one row per case
    evals/runs/<variant>/errors.jsonl    attempts that failed before a deck existed
    evals/runs/<variant>/traces/<id>.json  full conversation (gitignored)

Usage:
    python eval_decks.py --variant baseline
    python eval_decks.py --variant claude-opus-5-5 --cases kestia-50,krenko-150   # pilot
    python eval_decks.py --variant claude-haiku-5-5
    python eval_decks.py --summary          # table of every variant -> evals/RESULTS.md
"""

import argparse
import json
import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

import build_deck
import card_db
import edhrec_client
import llm_deck
from scan_binder import ScanError, make_client
from validate_deck import validate_text

COMMANDERS = [
    "Kestia, the Cultivator", "Muldrotha, the Gravetide", "Atraxa, Praetors' Voice", "Krenko, Mob Boss",
    "Talrand, Sky Summoner", "Lathril, Blade of the Elves", "Edgar Markov", "Grist, the Hunger Tide",
    "Esika, God of the Tree", "Karn, Legacy Reforged",
]
BUDGETS = (50, 150, 500)
EVAL_DIR = Path(__file__).parent / "evals"
RUNS_DIR = EVAL_DIR / "runs"
ROLE_WARNINGS = ("lands;", "ramp cards", "draw cards", "removal cards")
METRICS = ("valid_first", "valid", "budget_use", "avg_overlap", "inclusion", "roles_ok")
CASE_TIMEOUT_S = 600


def case_id(commander, budget):
    return f"{edhrec_client.slugify(commander).split('-')[0]}-{budget}"


def all_cases():
    return [{"id": case_id(c, b), "commander": c, "budget": b} for c in COMMANDERS for b in BUDGETS]


# ---------------------------------------------------------------------------
# Grading (pure functions)
# ---------------------------------------------------------------------------


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0


def grade_deck(deck, budget, avg_deck, check, valid_first):
    """Metrics for one valid deck."""
    names = [c["name"] for c in deck["cards"]]
    listed = [c for c in deck["cards"] if c["listed"]]
    role_warnings = [w for w in check["warnings"] if any(k in w for k in ROLE_WARNINGS)]
    return {
        "valid_first": float(valid_first),
        "valid": 1.0,
        "budget_use": round(deck["spent"] / budget, 4) if budget else 1.0,
        "avg_overlap": round(jaccard(names, avg_deck), 4),
        "inclusion": round(sum(c["inclusion"] for c in listed) / len(listed), 4) if listed else 0.0,
        "roles_ok": float(not role_warnings),
    }


def wilson(successes, n, z=1.96):
    """95% Wilson interval for a pass rate."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


class Context:
    """Per-commander data shared by every case (pool, average deck), built once."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.local = threading.local()
        self.by_commander = {}

    def db(self):
        if not hasattr(self.local, "db"):
            self.local.db = card_db.CardDB(self.db_path)  # sqlite connections are per thread
        return self.local.db

    def prepare(self, commander_name):
        if commander_name in self.by_commander:
            return self.by_commander[commander_name]
        db = self.db()
        commander = db.get(commander_name)
        slug = edhrec_client.slugify(commander["name"])
        page = edhrec_client.parse_commander_page(edhrec_client.fetch_commander_page(slug))
        pool = build_deck.candidate_pool(commander, page["cards"], db)
        oracle = db.get_many([c["name"] for c in pool])
        for c in pool:
            c["oracle_text"] = oracle[c["name"]]["oracle_text"]
        data = {"commander": commander, "pool": pool, "avg_deck": edhrec_client.fetch_average_deck(slug)}
        self.by_commander[commander_name] = data
        return data


def run_baseline_case(case, ctx):
    data = ctx.prepare(case["commander"])
    commander, budget = data["commander"], case["budget"]
    cost = commander["usd"] or 0.0
    start = time.time()
    deck = build_deck.build_deck(commander, data["pool"], budget, commander_cost=cost)
    check = validate_text(build_deck.import_text(commander, deck), ctx.db(), budget=budget)
    row = {"status": "ok" if check["ok"] else "invalid", "model": "baseline (no LLM)", "attempts": 1,
           "latency_s": round(time.time() - start, 2), "usage": {}, "cost_usd": 0.0}
    if check["ok"]:
        row["grade"] = grade_deck(deck, budget, data["avg_deck"], check, valid_first=True)
    else:
        row["grade"] = {"valid_first": 0.0, "valid": 0.0}
        row["errors"] = check["errors"]
    return row, None


def run_claude_case(case, ctx, client, model):
    data = ctx.prepare(case["commander"])
    commander, budget = data["commander"], case["budget"]
    cost = commander["usd"] or 0.0
    start = time.time()
    result = llm_deck.build_with_claude(commander, data["pool"], budget, ctx.db(), client,
                                        commander_cost=cost, model=model, log=lambda *_: None)
    served = {a["served_model"] for a in result["attempts"] if a.get("served_model")}
    row = {"status": "ok" if result["ok"] else "invalid", "model": ",".join(sorted(served)) or model,
           "attempts": len(result["attempts"]), "latency_s": round(time.time() - start, 2),
           "usage": result["usage"], "cost_usd": result["cost_usd"],
           "meta": {"served_other_model": bool(served - {model}), "attempt_errors": [a["errors"] for a in result["attempts"]]}}
    valid_first = not result["attempts"][0]["errors"]
    if result["ok"]:
        check = {"warnings": result["deck"]["warnings"]}
        row["grade"] = grade_deck(result["deck"], budget, data["avg_deck"], check, valid_first)
        row["meta"]["strategy"] = result["strategy"]
    else:
        row["grade"] = {"valid_first": 0.0, "valid": 0.0}
    return row, result["transcript"]


def done_ids(path):
    if not path.exists():
        return set()
    return {json.loads(line)["prompt_id"] for line in path.read_text().splitlines() if line.strip()}


def run_variant(variant, cases, workers=4, db_path=None, client=None, log=print, ctx=None, runs_dir=None):
    out = (runs_dir or RUNS_DIR) / variant
    (out / "traces").mkdir(parents=True, exist_ok=True)
    results, errors = out / "results.jsonl", out / "errors.jsonl"
    todo = [c for c in cases if c["id"] not in done_ids(results)]
    log(f"{variant}: {len(cases) - len(todo)} done already, {len(todo)} to run")
    if not todo:
        return
    ctx = ctx or Context(db_path or card_db.ensure_db())
    for name in dict.fromkeys(c["commander"] for c in todo):
        ctx.prepare(name)  # fetch EDHREC pages once, before the threads start
    lock = threading.Lock()
    is_baseline = variant == "baseline"
    if not is_baseline and client is None:
        client = make_client().with_options(timeout=CASE_TIMEOUT_S, max_retries=4)

    def work(case):
        try:
            if is_baseline:
                return case, *run_baseline_case(case, ctx), None
            return case, *run_claude_case(case, ctx, client, variant), None
        except (ScanError, anthropic.APIError) as exc:
            failure = "refusal" if "declined" in str(exc) else "api_or_parse_error"
            return case, None, None, {"failure": failure, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=1 if is_baseline else workers) as pool:
        futures = [pool.submit(work, c) for c in todo]
        for fut in as_completed(futures):
            case, row, transcript, failure = fut.result()
            with lock:
                if failure:
                    with errors.open("a") as f:
                        f.write(json.dumps({"prompt_id": case["id"], "time": time.time(), **failure}) + "\n")
                    log(f"  {case['id']}: ERROR {failure['failure']}")
                    continue
                row = {"prompt_id": case["id"], "prompt": f"{case['commander']} ${case['budget']}",
                       "tags": [case["commander"], f"${case['budget']}"], **row}
                with results.open("a") as f:
                    f.write(json.dumps(row) + "\n")
                if transcript:
                    (out / "traces" / f"{case['id']}.json").write_text(json.dumps(transcript, indent=1))
                g = row["grade"]
                log(f"  {case['id']}: {row['status']} first={g['valid_first']:.0f} tries={row['attempts']} "
                    f"${row['cost_usd'] or 0:.3f} {row['latency_s']}s")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def summarize(variant_dir):
    rows = [json.loads(l) for l in (variant_dir / "results.jsonl").read_text().splitlines() if l.strip()]
    errors_path = variant_dir / "errors.jsonl"
    n_err = len(errors_path.read_text().splitlines()) if errors_path.exists() else 0
    n = len(rows)
    valid = [r for r in rows if r["status"] == "ok"]
    first = sum(r["grade"]["valid_first"] for r in rows)

    def mean(key):
        vals = [r["grade"][key] for r in valid]
        return sum(vals) / len(vals) if vals else 0.0

    cost = [r["cost_usd"] or 0.0 for r in rows]
    return {
        "variant": variant_dir.name, "cases": n, "errors": n_err,
        "valid_first": first / n if n else 0.0, "valid_first_ci": wilson(first, n),
        "valid": len(valid) / n if n else 0.0, "valid_n": len(valid),
        **{k: mean(k) for k in ("budget_use", "avg_overlap", "inclusion", "roles_ok")},
        "cost_total": sum(cost), "cost_per_deck": sum(cost) / n if n else 0.0,
        "latency_s": sum(r["latency_s"] for r in rows) / n if n else 0.0,
        "over_budget": sum(r["grade"].get("budget_use", 0) > 1 for r in rows),
    }


def summary_table(summaries):
    lines = [
        "| Variant | Cases | Valid 1st try (95% CI) | Valid | Budget used | Avg-deck overlap | Inclusion | Roles OK | $/deck | s/deck |",
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for s in summaries:
        lo, hi = s["valid_first_ci"]
        lines.append(
            f"| {s['variant']} | {s['cases']}{f' (+{s['errors']} err)' if s['errors'] else ''} "
            f"| {s['valid_first']:.0%} ({lo:.0%}-{hi:.0%}) | {s['valid']:.0%} | {s['budget_use']:.0%} "
            f"| {s['avg_overlap']:.0%} | {s['inclusion']:.0%} | {s['roles_ok']:.0%} "
            f"| ${s['cost_per_deck']:.3f} | {s['latency_s']:.1f} |"
        )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate Claude-built decks against the no-LLM baseline.")
    parser.add_argument("--variant", help="'baseline' or a model id, e.g. claude-opus-5-5")
    parser.add_argument("--cases", help="comma-separated case ids (default: all 30)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--summary", action="store_true", help="print the table for every variant run so far")
    args = parser.parse_args(argv)

    if args.summary:
        dirs = sorted((d for d in RUNS_DIR.glob("*") if (d / "results.jsonl").exists()),
                      key=lambda d: (d.name != "baseline", d.name))
        if not dirs:
            print("No runs yet.", file=sys.stderr)
            return 1
        table = summary_table([summarize(d) for d in dirs])
        (EVAL_DIR / "RESULTS.md").write_text("# Deck builder eval results\n\n" + table + "\n")
        print(table)
        return 0

    if not args.variant:
        parser.error("--variant or --summary is required")
    if args.variant != "baseline" and args.variant not in llm_deck.PRICES:
        parser.error(f"unknown model {args.variant!r}; one of {sorted(llm_deck.PRICES)}")
    cases = all_cases()
    if args.cases:
        wanted = set(args.cases.split(","))
        unknown = wanted - {c["id"] for c in cases}
        if unknown:
            parser.error(f"unknown case ids: {sorted(unknown)}")
        cases = [c for c in cases if c["id"] in wanted]
    try:
        run_variant(args.variant, cases, workers=args.workers)
    except (ScanError, edhrec_client.EdhrecError, card_db.BulkDataError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
