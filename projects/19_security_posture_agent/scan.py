"""Take a read-only security snapshot of this Windows machine (run from WSL).

    python scan.py              # save to data/snapshots/
    python scan.py --out DIR    # save somewhere else

Slice 1 only collects facts. Findings and the report come in later slices.
"""

import argparse
import sys

import snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=snapshot.DEFAULT_DIR, help="folder to save the snapshot in")
    args = parser.parse_args(argv)

    print("Collecting (read-only)...")
    snap = snapshot.build_snapshot()
    path = snapshot.save_snapshot(snap, args.out)

    print(snapshot.summarize(snap))
    host = snap["sections"]["host"]["items"]
    if host and not host[0]["is_admin"]:
        print("\nNote: not running as admin, so some items may be hidden.")
    print(f"\nSaved: {path}")
    print("This file has real machine details. It stays local; don't commit or share it.")

    failed = [n for n, s in snap["sections"].items() if not s["ok"]]
    return 1 if len(failed) == len(snap["sections"]) else 0


if __name__ == "__main__":
    sys.exit(main())
