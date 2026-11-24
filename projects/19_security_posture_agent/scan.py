"""Read-only security scan of this Windows machine (run from WSL).

    python scan.py                         # scan, save snapshot + report
    python scan.py --from-snapshot FILE    # re-run checks on a saved snapshot

Snapshots and reports go under data/ (gitignored): they hold real machine details.
"""

import argparse
import sys
from collections import Counter

import checks
import report
import snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from-snapshot", metavar="FILE", help="check a saved snapshot instead of scanning")
    parser.add_argument("--out", default=None, help="folder for the snapshot and report (default: data/)")
    args = parser.parse_args(argv)

    snap_dir = f"{args.out}/snapshots" if args.out else snapshot.DEFAULT_DIR
    report_dir = f"{args.out}/reports" if args.out else report.DEFAULT_DIR

    if args.from_snapshot:
        snap = snapshot.load_snapshot(args.from_snapshot)
        print(f"Checking saved snapshot {args.from_snapshot}")
    else:
        print("Collecting (read-only)...")
        snap = snapshot.build_snapshot()
        print(f"Snapshot: {snapshot.save_snapshot(snap, snap_dir)}")
    print(snapshot.summarize(snap))

    findings = checks.run_checks(snap)
    path = report.save_report(report.render(snap, findings), snap, report_dir)

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
