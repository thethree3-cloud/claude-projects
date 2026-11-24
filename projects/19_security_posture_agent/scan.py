"""Read-only security scan of this Windows machine (run from WSL).

    python scan.py                         # scan, compare with the previous scan, report
    python scan.py --baseline FILE         # compare with a specific (trusted) snapshot
    python scan.py --no-baseline           # skip the comparison
    python scan.py --from-snapshot FILE    # re-check a saved snapshot

Snapshots and reports go under data/ (gitignored): they hold real machine details.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

import baseline
import checks
import report
import snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from-snapshot", metavar="FILE", help="check a saved snapshot instead of scanning")
    parser.add_argument("--baseline", metavar="FILE", help="snapshot to compare with (default: the previous one)")
    parser.add_argument("--no-baseline", action="store_true", help="don't compare with an earlier scan")
    parser.add_argument("--out", default=None, help="folder for the snapshot and report (default: data/)")
    args = parser.parse_args(argv)
    if args.baseline and args.no_baseline:
        parser.error("--baseline and --no-baseline can't be used together")

    snap_dir = Path(args.out) / "snapshots" if args.out else snapshot.DEFAULT_DIR
    report_dir = Path(args.out) / "reports" if args.out else report.DEFAULT_DIR

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

    path = report.save_report(report.render(snap, findings, changes), snap, report_dir)

    counts = Counter(f["severity"] for f in findings)
    print("\nFindings: " + ", ".join(f"{counts[s]} {s}" for s in checks.SEVERITY_ORDER))
    for f in findings:
        if f["severity"] in ("high", "medium"):
            print(f"  [{f['severity'].upper()}] {report.clean(f['title'], 100)}")
    print(f"\nReport: {path}")
    print("Snapshot and report hold real machine details. They stay local; don't commit or share them.")

    failed = [n for n, s in snap["sections"].items() if not s["ok"]]
    return 1 if len(failed) == len(snap["sections"]) else 0


if __name__ == "__main__":
    sys.exit(main())
