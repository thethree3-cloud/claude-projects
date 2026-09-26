"""Run the known-answer test questions against the live agent.

    python run_eval.py                 # all cases
    python run_eval.py --only injury_form smoking_distance
    python run_eval.py -v              # print every answer, not just failures

Uses the real API (2-3 Haiku calls per question). Each run is saved to
data/eval_runs/ (gitignored) so runs can be compared after a prompt or
routing change. Exits 1 if anything fails.
"""

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from eval_cases import CASES

RUNS_DIR = Path(__file__).resolve().parent / "data" / "eval_runs"
WORKERS = 4
# The PDF prints phone numbers and form names with U+2010 hyphens ("C‐1").
_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—"})
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def normalize(text):
    """Lowercase, drop markdown bold, fold dash/quote/space variants, so
    "**C‐1**" matches "C-1"."""
    text = text.replace("**", "").translate(_DASHES).translate(_QUOTES)
    return re.sub(r"\s+", " ", text).lower()


def check_case(case, result):
    """Pure scoring: case + agent result -> list of failure messages."""
    failures = []
    answer = normalize(result["answer"])
    subjects = [s["subject"] for s in result["sources"]]

    for item in case.get("must_include", []):
        options = item if isinstance(item, list) else [item]
        if not any(normalize(o) in answer for o in options):
            failures.append(f"missing {' or '.join(repr(o) for o in options)}")

    for item in case.get("must_not", []):
        if normalize(item) in answer:
            failures.append(f"should not say {item!r}")

    for wanted in case.get("sources", []):
        if not any(normalize(wanted) in normalize(s) for s in subjects):
            failures.append(f"no source matching {wanted!r} (got {subjects or 'none'})")

    if case.get("no_sources") and subjects:
        failures.append(f"should have no sources, got {subjects}")

    return failures


def run_case(case):
    from ask import answer_question_full  # imported here so scoring tests need no API client

    started = time.monotonic()
    history = []
    for earlier in case.get("history", []):
        prior = answer_question_full(earlier, history)
        history += [{"role": "user", "content": earlier},
                    {"role": "assistant", "content": prior["answer"]}]
    result = answer_question_full(case["question"], history)
    return {
        "id": case["id"],
        "question": case["question"],
        "searched_as": result["searched_as"],
        "answer": result["answer"],
        "sources": [f"{s['subject']} (pages {s['start']}-{s['end']})" for s in result["sources"]],
        "failures": check_case(case, result),
        "seconds": round(time.monotonic() - started, 1),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="+", metavar="ID", help="run just these case ids")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every answer")
    args = parser.parse_args()

    cases = CASES
    if args.only:
        unknown = set(args.only) - {c["id"] for c in CASES}
        if unknown:
            sys.exit(f"Unknown case id(s): {', '.join(sorted(unknown))}")
        cases = [c for c in CASES if c["id"] in args.only]

    print(f"Running {len(cases)} questions...\n")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(run_case, cases))

    for r in results:
        mark = "PASS" if not r["failures"] else "FAIL"
        print(f"{mark}  {r['id']:<24} {r['seconds']:>5}s")
        for failure in r["failures"]:
            print(f"        - {failure}")
        if r["failures"] or args.verbose:
            if r["searched_as"] != r["question"]:
                print(f"        searched as: {r['searched_as']}")
            print("        answer: " + r["answer"].replace("\n", "\n                "))
            print()

    passed = sum(not r["failures"] for r in results)
    print(f"\n{passed}/{len(results)} passed")

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / f"{datetime.now():%Y-%m-%d_%H%M%S}.json"
    out.write_text(json.dumps({"passed": passed, "total": len(results), "results": results}, indent=2))
    print(f"Saved to {out.relative_to(Path(__file__).resolve().parent)}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
