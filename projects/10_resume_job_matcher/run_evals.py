"""Eval harness — a regression signal for Project 10's prompts and schemas.

`python -m unittest discover` is offline and mocked; it proves the plumbing.
This is the other half: it runs the real chain against a real model and checks
that the *judgement* still lands where it should. Run it after touching any
prompt, schema, or the scoring rubric.

    python run_evals.py              # every case
    python run_evals.py --case ml    # cases whose name contains "ml"
    python run_evals.py --list       # just list the cases
    python run_evals.py -v           # also print each full report / résumé

Exit code is non-zero if any case fails. Checks are tolerant on purpose (see
`eval_cases.py`) — a failure is "go look", not "the build is red".

Needs ANTHROPIC_API_KEY, same as every other live entry point.
"""

import argparse
import sys

from eval_cases import FIT_CASES, TAILOR_CASES
from parse_resume import parse_resume
from pipeline import evaluate_fit, tailor_fit
from report import format_report


class Result:
    def __init__(self, name):
        self.name = name
        self.checks = []  # (label, ok, detail)
        self.error = None

    def check(self, label, ok, detail=""):
        self.checks.append((label, bool(ok), detail))

    @property
    def passed(self):
        return self.error is None and all(ok for _, ok, _ in self.checks)


def run_fit_case(case, verbose):
    result = Result(f"[fit] {case.name}")
    try:
        report = evaluate_fit(case.resume, case.job)
    except Exception as exc:  # noqa: BLE001 — a live failure is a case failure
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    result.check(
        f"band in {case.band_in}", report["band"] in case.band_in, f"got {report['band']}"
    )
    lo, hi = case.score_range
    result.check(
        f"score in [{lo}, {hi}]",
        lo <= report["score"] <= hi,
        f"got {report['score']}",
    )
    if case.max_unmet_required is not None:
        unmet = report["gaps"]["unmet_required_skills"]
        result.check(
            f"<= {case.max_unmet_required} unmet required skill(s)",
            len(unmet) <= case.max_unmet_required,
            f"got {len(unmet)}: {unmet}",
        )
    if case.expect_genuine_gap:
        kinds = {s["assessment"] for s in report["suggestions"]}
        result.check(
            "a suggestion assessed genuine_gap",
            "genuine_gap" in kinds,
            f"got {sorted(kinds) or 'no suggestions'}",
        )

    if verbose:
        print(format_report(report))
        print()
    return result


def run_tailor_case(case, verbose):
    result = Result(f"[tailor] {case.name}")
    try:
        resume = parse_resume(case.resume)
        out = tailor_fit(case.resume, case.job)
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    tailored = out["resume"]
    src_orgs = sorted(e["organization"] for e in resume["experience"])
    out_orgs = sorted(e["organization"] for e in tailored["experience"])
    result.check("every role kept", src_orgs == out_orgs, f"{src_orgs} -> {out_orgs}")

    result.check(
        "contact preserved verbatim",
        tailored["email"] == resume["email"]
        and tailored["phone"] == resume["phone"]
        and tailored["links"] == resume["links"],
    )
    result.check(
        "no invented skills",
        set(tailored["skills"]) <= set(resume["skills"]),
        f"extra: {sorted(set(tailored['skills']) - set(resume['skills']))}",
    )
    result.check(
        f"<= {case.max_flags} bullet(s) flagged by verification",
        len(out["flags"]) <= case.max_flags,
        f"flagged: {[f['bullet'] for f in out['flags']]}",
    )
    leaked = [f["bullet"] for f in out["flags"] if f["bullet"] in out["markdown"]]
    result.check(
        "flagged bullets never survive into the résumé",
        not leaked,
        f"leaked: {leaked}",
    )

    if verbose:
        print(out["markdown"])
        print()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="only run cases whose name contains this")
    parser.add_argument("--list", action="store_true", help="list cases and exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    jobs = [(run_fit_case, c) for c in FIT_CASES] + [
        (run_tailor_case, c) for c in TAILOR_CASES
    ]
    if args.case:
        jobs = [(fn, c) for fn, c in jobs if args.case.lower() in c.name.lower()]

    if args.list:
        for fn, case in jobs:
            kind = "fit" if fn is run_fit_case else "tailor"
            print(f"  [{kind}] {case.name}")
        return 0
    if not jobs:
        print("no cases matched")
        return 1

    print(f"=== Project 10 evals — {len(jobs)} case(s) ===\n")
    results = []
    for fn, case in jobs:
        result = fn(case, args.verbose)
        results.append(result)
        mark = "PASS" if result.passed else "FAIL"
        print(f"{mark}  {result.name}")
        if result.error:
            print(f"      ERROR  {result.error}")
        for label, ok, detail in result.checks:
            tick = "ok  " if ok else "XX  "
            suffix = f"  ({detail})" if detail and not ok else ""
            print(f"      {tick}{label}{suffix}")
        print()

    passed = sum(r.passed for r in results)
    total_checks = sum(len(r.checks) for r in results)
    ok_checks = sum(ok for r in results for _, ok, _ in r.checks)
    print(f"{passed}/{len(results)} cases passed, {ok_checks}/{total_checks} checks")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
