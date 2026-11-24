"""Run the Slice 5 evals.

    python evals/run_eval.py --detector                    # free: rules vs. expectations
    python evals/run_eval.py --approve-harness             # YOU run this once to approve the eval code
    python evals/run_eval.py --reps 3                      # paid: Claude explanations, all scenarios
    python evals/run_eval.py --only clean backdoor-multi   # paid: a few scenarios (pilot)

Claude mode writes evals/runs/explain/<variant>/:
    results.jsonl   one graded row per (scenario, rep), written as each finishes
    traces/         the exact request and Claude's raw answer per (scenario, rep)
    errors.jsonl    attempts that never produced a gradable answer (API errors,
                    timeouts, served-model mismatch). Never scored as zeros.
Re-running resumes: (scenario, rep) pairs already in results.jsonl are skipped.

The runner calls scan.explain_and_validate, the same function `scan.py --explain`
uses, so the eval measures what users actually run.
"""

import argparse
import concurrent.futures as cf
import hashlib
import json
import math
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(HERE))

import explain  # noqa: E402
import grade  # noqa: E402
import scan  # noqa: E402
import scenarios as S  # noqa: E402

FLOW = HERE / "runs" / "explain"
APPROVAL = FLOW / "harness_approved.txt"
HARNESS_FILES = ["evals/run_eval.py", "evals/grade.py", "evals/scenarios.py", "explain.py", "validate.py",
                 "redact.py", "scan.py", "checks.py", "baseline.py", "report.py"]
# $ per million tokens (input, output), first-party API, from the Claude API skill's model table.
PRICES = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00), "claude-haiku-5-5": (0.10, 0.50)}
CLAUDE_METRICS = ["pass", "answered", "covered", "no_invented", "clean", "first_ok", "injection_ok", "calm_ok"]


# --- Harness approval ---------------------------------------------------------------------

def harness_sha():
    h = hashlib.sha256()
    for rel in sorted(HARNESS_FILES):
        h.update(rel.encode())
        h.update(hashlib.sha256((PROJECT / rel).read_bytes()).hexdigest().encode())
    return h.hexdigest()


def check_harness(approve):
    sha = harness_sha()
    if approve:
        FLOW.mkdir(parents=True, exist_ok=True)
        APPROVAL.write_text(sha + "\n")
        print(f"Approved eval code {sha[:12]} ({len(HARNESS_FILES)} files).")
        return True
    approved = APPROVAL.read_text().strip() if APPROVAL.exists() else None
    if approved != sha:
        print("The eval code changed since it was last approved (or was never approved).\n"
              "Review the changes, then run:  python evals/run_eval.py --approve-harness", file=sys.stderr)
        return False
    return True


# --- Detector mode (free) -----------------------------------------------------------------

def run_detector():
    rows = []
    for s in S.SCENARIOS:
        _, findings, _ = S.build(s)
        d = grade.grade_detector(s, findings)
        rows.append({"id": s["id"], "tags": s["tags"], "findings": len(findings), **d["grade"],
                     "missed": d["missed"], "wrong_severity": d["wrong_severity"], "alarms": d["alarms"]})
    expected = sum(len(s["expect"]) for s in S.SCENARIOS)
    found = sum(r["recall"] * len(S.get(r["id"])["expect"]) for r in rows)
    summary = {"scenarios": len(rows), "passed": int(sum(r["pass"] for r in rows)),
               "expected_findings": expected, "found": int(round(found)),
               "false_alarms": int(sum(r["false_alarms"] for r in rows))}
    out = HERE / "runs" / "detector.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    for r in rows:
        print(f"  {'pass' if r['pass'] else 'FAIL'}  {r['id']:26} recall {r['recall']:.0%}  "
              f"false alarms {int(r['false_alarms'])}")
    print(f"\nDetector: {summary['passed']}/{summary['scenarios']} scenarios pass; "
          f"{summary['found']}/{expected} expected findings at the right severity; "
          f"{summary['false_alarms']} false alarms.  ({out})")
    return summary


# --- Claude mode (paid) -------------------------------------------------------------------

def _usage(info):
    return {k: info.get(k) or 0 for k in ("input_tokens", "output_tokens",
                                           "cache_read_input_tokens", "cache_creation_input_tokens")}


def cost_usd(model, usage):
    if model not in PRICES:
        return None
    pin, pout = PRICES[model]
    return (usage.get("input_tokens", 0) * pin + usage.get("output_tokens", 0) * pout
            + usage.get("cache_read_input_tokens", 0) * pin * 0.1
            + usage.get("cache_creation_input_tokens", 0) * pin * 1.25) / 1e6


def run_case(scenario, rep, model, client):
    """One (scenario, rep). Returns ('row', row, trace) or ('error', error_row, None)."""
    snap, findings, label = S.build(scenario)
    explain.MODEL = model
    started = time.monotonic()
    raw, info, validated, request, failure = None, {}, None, None, None
    try:
        request, raw, info, validated = scan.explain_and_validate(snap, findings, label, client=client)
    except explain.ExplainError as e:
        info = e.info
        if e.kind == "api":
            return "error", {"failure_class": "api_error", "message": str(e)}, None
        failure = e.kind  # refusal / truncated / bad_output: graded outcomes, not plumbing
    latency = round(time.monotonic() - started, 2)

    served = info.get("model")
    if served and served != model and not info.get("fallback_used"):
        return "error", {"failure_class": "served_model_mismatch", "message": f"asked {model}, got {served}",
                         "model": served, "usage": _usage(info)}, None

    base = {"prompt_id": scenario["id"], "rep": rep, "prompt": scenario["description"], "tags": scenario["tags"],
            "model": served or model, "usage": _usage(info), "latency_s": latency,
            "stop_reason": info.get("stop_reason")}
    if failure == "truncated":
        row = {**base, "status": "truncated", "grade": {}, "meta": {"failure": failure}}
    else:
        if validated is None:  # refusal / bad output: grade what the model did, which is nothing usable
            validated = {"rejected": [], "groups": [], "summary": None, "notes": [], "accepted": False}
        g = grade.grade_claude(scenario, findings, raw, validated)
        row = {**base, "status": "ok", "grade": g["grade"],
               "meta": {"findings": len(findings), "failure": failure, "fallback_used": info.get("fallback_used"),
                        "request_id": info.get("request_id"), **g["detail"]}}
    sent = request or scan.prepare_explain(snap, findings, label)[2]  # the exact request, when it went out
    trace = [{"role": "system", "content": sent["system"]},
             {"role": "user", "content": sent["messages"][0]["content"]},
             {"role": "assistant", "content": json.dumps(raw, indent=2, ensure_ascii=False) if raw is not None
              else f"(no answer: {failure})"}]
    return "row", row, trace


def _done_keys(results):
    if not results.exists():
        return set()
    return {(r["prompt_id"], r["rep"]) for r in map(json.loads, results.read_text().splitlines()) if r}


def run_claude(args, client=None):
    variant = FLOW / args.variant
    (variant / "traces").mkdir(parents=True, exist_ok=True)
    results, errors = variant / "results.jsonl", variant / "errors.jsonl"
    done = _done_keys(results)
    selected = [s for s in S.SCENARIOS if not args.only or s["id"] in args.only]
    if args.only and len(selected) != len(set(args.only)):
        unknown = set(args.only) - {s["id"] for s in selected}
        raise SystemExit(f"unknown scenario id(s): {', '.join(sorted(unknown))}")
    jobs = [(s, r) for s in selected for r in range(args.reps) if (s["id"], r) not in done]
    print(f"{len(jobs)} call(s) to run on {args.model} ({len(done)} already done), {args.workers} at a time")
    if not jobs:
        return summarize(results, errors)

    if client is None:
        client = explain.make_client().with_options(max_retries=4)  # SDK retries 429/5xx with jittered backoff
    lock = threading.Lock()
    started = {}

    def work(s, rep):
        started[(s["id"], rep)] = time.monotonic()
        return run_case(s, rep, args.model, client)

    def write(kind, s, rep, row, trace):
        with lock:
            if kind == "row":
                (variant / "traces" / f"{s['id']}_rep{rep}.json").write_text(
                    json.dumps(trace, indent=1, ensure_ascii=False), encoding="utf-8")
                with results.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            else:
                with errors.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"prompt_id": s["id"], "rep": rep, **row,
                                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}) + "\n")
            status = row.get("grade", {}).get("pass") if kind == "row" else row["failure_class"]
            print(f"  {s['id']:26} rep{rep}  {status}")

    pool = cf.ThreadPoolExecutor(max_workers=args.workers)
    pending = {pool.submit(work, s, rep): (s, rep) for s, rep in jobs}
    while pending:
        finished, _ = cf.wait(pending, timeout=1.0, return_when=cf.FIRST_COMPLETED)
        for fut in finished:
            s, rep = pending.pop(fut)
            try:
                kind, row, trace = fut.result()
            except Exception as e:  # harness bug: record it, keep going
                kind, row, trace = "error", {"failure_class": "harness_error", "message": repr(e)}, None
            write(kind, s, rep, row, trace)
        now = time.monotonic()
        for fut, (s, rep) in list(pending.items()):
            t0 = started.get((s["id"], rep))
            if t0 and now - t0 > args.timeout_s:
                pending.pop(fut)  # the call may still finish in the background; its result is dropped
                write("error", s, rep, {"failure_class": "timeout", "message": f"over {args.timeout_s}s"}, None)
    pool.shutdown(wait=False, cancel_futures=True)
    return summarize(results, errors)


def _wilson(k, n):
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def summarize(results, errors):
    rows = [json.loads(x) for x in results.read_text().splitlines() if x] if results.exists() else []
    errs = [json.loads(x) for x in errors.read_text().splitlines() if x] if errors.exists() else []
    ok = [r for r in rows if r["status"] == "ok"]
    out = {"rows": len(rows), "ok": len(ok), "truncated": len(rows) - len(ok), "errors": len(errs), "metrics": {}}
    for m in CLAUDE_METRICS:
        vals = [r["grade"][m] for r in ok if m in r["grade"]]
        if vals:
            k = sum(vals)
            out["metrics"][m] = {"mean": k / len(vals), "n": len(vals),
                                 "ci95": _wilson(k, len(vals)) if m != "covered" else None}
    costs = [cost_usd(r["model"], r["usage"]) for r in rows]
    costs = [c for c in costs if c is not None]
    lat = [r["latency_s"] for r in ok]
    out["cost_usd_total"] = round(sum(costs), 4)
    out["cost_usd_per_call"] = {"min": round(min(costs), 4), "median": round(statistics.median(costs), 4),
                                "max": round(max(costs), 4)} if costs else None
    out["latency_s"] = {"median": statistics.median(lat), "max": max(lat)} if lat else None
    out["tokens"] = {"input_median": statistics.median([r["usage"]["input_tokens"] for r in rows]),
                     "output_median": statistics.median([r["usage"]["output_tokens"] for r in rows])} if rows else None
    out["refusals"] = sum(1 for r in ok if r["meta"].get("failure") == "refusal")
    out["fallbacks"] = sum(1 for r in ok if r["meta"].get("fallback_used"))

    print(f"\n{out['ok']} graded call(s), {out['truncated']} truncated, {out['errors']} error(s), "
          f"{out['refusals']} refusal(s), {out['fallbacks']} fallback(s)")
    for m, v in out["metrics"].items():
        ci = f"  (95% CI {v['ci95'][0]:.0%}-{v['ci95'][1]:.0%})" if v["ci95"] else ""
        print(f"  {m:13} {v['mean']:.0%} of {v['n']}{ci}")
    if costs:
        print(f"  cost         ${out['cost_usd_total']:.2f} total; per call {out['cost_usd_per_call']}")
    if lat:
        print(f"  latency      median {out['latency_s']['median']:.1f}s, max {out['latency_s']['max']:.1f}s")
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--detector", action="store_true", help="free: grade the rules only")
    p.add_argument("--approve-harness", action="store_true", help="record approval of the current eval code")
    p.add_argument("--variant", default="baseline", help="output folder name: baseline, v1, v2, ...")
    p.add_argument("--model", default=explain.MODEL)
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--only", nargs="*", help="scenario ids to run (default: all)")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--timeout-s", type=float, default=180)
    p.add_argument("--summary", action="store_true", help="print the summary of existing results, run nothing")
    args = p.parse_args(argv)

    if args.detector:
        run_detector()
        return 0
    if args.approve_harness:
        check_harness(approve=True)
        return 0
    if args.variant != "baseline" and not (args.variant.startswith("v") and args.variant[1:].isdigit()):
        p.error("--variant must be 'baseline' or v1, v2, ...")
    if args.summary:
        v = FLOW / args.variant
        summarize(v / "results.jsonl", v / "errors.jsonl")
        return 0
    if not check_harness(approve=False):
        return 2
    run_claude(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
