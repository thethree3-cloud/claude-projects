"""Read-only security scan of this Windows machine (run from WSL).

    python scan.py                         # scan, compare with the previous scan, report
    python scan.py --baseline FILE         # compare with a specific (trusted) snapshot
    python scan.py --no-baseline           # skip the comparison
    python scan.py --from-snapshot FILE    # re-check a saved snapshot
    python scan.py --explain               # also ask Claude for a plain-English summary
    python scan.py --explain-dry-run       # save what --explain would send, send nothing

Snapshots and reports go under data/ (gitignored): they hold real machine details.
--explain is the only option that sends anything off this computer: the
findings (not the snapshot), with username, computer name and account IDs
replaced. A copy of exactly what was sent is saved under data/llm_input/.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import baseline
import checks
import explain
import redact
import report
import report_html
import snapshot
import validate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from-snapshot", metavar="FILE", help="check a saved snapshot instead of scanning")
    parser.add_argument("--baseline", metavar="FILE", help="snapshot to compare with (default: the previous one)")
    parser.add_argument("--no-baseline", action="store_true", help="don't compare with an earlier scan")
    parser.add_argument("--explain", action="store_true", help="ask Claude to group and explain the findings")
    parser.add_argument("--explain-dry-run", action="store_true",
                        help="save the redacted data --explain would send, without sending it")
    parser.add_argument("--out", default=None, help="folder for the snapshot and report (default: data/)")
    args = parser.parse_args(argv)
    if args.baseline and args.no_baseline:
        parser.error("--baseline and --no-baseline can't be used together")
    if args.explain and args.explain_dry_run:
        parser.error("--explain and --explain-dry-run can't be used together")

    data_dir = Path(args.out) if args.out else snapshot.DEFAULT_DIR.parent
    snap_dir = data_dir / "snapshots"
    report_dir = data_dir / "reports"

    if args.from_snapshot:
        snap_path = Path(args.from_snapshot)
        snap = snapshot.load_snapshot(snap_path)
        snap_dir = snap_path.parent
        print(f"Checking saved snapshot {snap_path}")
    else:
        print("Collecting (read-only)...")
        snap = snapshot.build_snapshot()
        snap_path = snapshot.save_snapshot(snap, snap_dir)
        print(f"Snapshot: {snap_path}")
    print(snapshot.summarize(snap))

    findings = checks.run_checks(snap)
    changes = None
    if not args.no_baseline:
        base_path = args.baseline or baseline.previous_snapshot_path(snap_dir, snap_path)
        if base_path:
            d, change_findings, label = baseline.compare(snap, base_path)
            findings = checks.sort_findings(findings + change_findings)
            changes = {"diff": d, "label": label}
            print(f"\nCompared with {label}: {len(change_findings)} change finding(s)")
        else:
            changes = {"diff": None}
            print("\nNo earlier scan to compare with yet; the next scan will show what changed.")

    ai = None
    if args.explain or args.explain_dry_run:
        ai = run_explain(snap, findings, changes, data_dir, dry_run=args.explain_dry_run)

    path = report.save_report(report.render(snap, findings, changes, ai), snap, report_dir)
    html_path = report_html.save(report_html.render(snap, findings, changes, ai), snap, report_dir)

    counts = Counter(f["severity"] for f in findings)
    print("\nFindings: " + ", ".join(f"{counts[s]} {s}" for s in checks.SEVERITY_ORDER))
    for f in findings:
        if f["severity"] in ("high", "medium"):
            print(f"  [{f['severity'].upper()}] {report.clean(f['title'], 100)}")
    print(f"\nReport: {html_path}  (open in a browser)")
    print(f"        {path}")
    print("Snapshot and report hold real machine details. They stay local; don't commit or share them.")

    failed = [n for n, s in snap["sections"].items() if not s["ok"]]
    return 1 if len(failed) == len(snap["sections"]) else 0


def prepare_explain(snap, findings, changes_label=None):
    """(redactor, payload, request) for the explain step: what scan.py and the eval send."""
    red = redact.Redactor(snap)
    payload = explain.build_payload(findings, red, changes_label)
    return red, payload, explain.build_request(payload)


def explain_and_validate(snap, findings, changes_label=None, client=None):
    """The whole explain step: redact, call Claude, validate. Shared by scan.py
    and evals/run_eval.py so the eval measures exactly what users run.
    Returns (request, raw, info, validated); raises explain.ExplainError."""
    red, payload, request = prepare_explain(snap, findings, changes_label)
    raw, info = explain.explain(payload, client=client)
    return request, raw, info, validate.validate(raw, findings, red)


def run_explain(snap, findings, changes, data_dir, dry_run=False, client=None):
    """Save the exact payload locally, call Claude, validate.
    Returns the report's `ai` dict; never raises, so the scan always finishes."""
    label = (changes or {}).get("label")
    _, _, request = prepare_explain(snap, findings, label)
    sent_dir = data_dir / "llm_input"
    sent_dir.mkdir(parents=True, exist_ok=True)
    stamp = snap["collected_at"].replace(":", "").replace("-", "").replace("+0000", "Z")
    sent_path = sent_dir / f"llm_input_{stamp}.json"
    sent_path.write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")

    if dry_run:
        print(f"\nDry run: nothing sent. What --explain would send: {sent_path}")
        return {"error": f"dry run, nothing sent (payload saved to {sent_path.name})"}
    if not findings:
        return {"error": "no findings to explain"}

    print(f"\nAsking Claude ({explain.MODEL}) to explain {len(findings)} findings "
          f"(redacted copy of what's sent: {sent_path})...")
    try:
        _, raw, info, v = explain_and_validate(snap, findings, label, client=client)
    except explain.ExplainError as e:
        print(f"  Explanation skipped: {e}")
        return {"error": str(e)}
    # Keep Claude's raw answer next to what was sent: for re-validating and for evals.
    (sent_dir / f"llm_response_{stamp}.json").write_text(
        json.dumps({"answer": raw, "info": info}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Validator: {len(v['groups'])} group(s), {len(v['rejected'])} item(s) removed")
    if not v["accepted"]:
        return {"error": "Claude's answer didn't pass the checks: " + "; ".join(v["rejected"][:3])}
    return {"validated": v, "info": info}


if __name__ == "__main__":
    sys.exit(main())
