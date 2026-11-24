"""Build and save a snapshot: every collector's output plus metadata.

Snapshots contain real machine details (usernames, paths, installed software),
so they're saved under data/, which is gitignored. Never commit one.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import collectors
import runner

SCHEMA_VERSION = 1
DEFAULT_DIR = Path(__file__).parent / "data" / "snapshots"


def build_snapshot(run=runner.run, now=None):
    now = now or datetime.now(timezone.utc)
    sections = {name: collect(run) for name, collect in collectors.COLLECTORS.items()}
    return {
        "schema_version": SCHEMA_VERSION,
        "collected_at": now.isoformat(timespec="seconds"),
        "platform": "windows",
        "sections": sections,
    }


def save_snapshot(snapshot, directory=DEFAULT_DIR):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = snapshot["collected_at"].replace(":", "").replace("-", "").replace("+0000", "Z")
    path = directory / f"snapshot_{stamp}.json"
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_snapshot(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def summarize(snapshot):
    """One line per section: name, item count, and status. No item details."""
    lines = []
    for name, sec in snapshot["sections"].items():
        status = "ok" if sec["ok"] else f"FAILED: {sec['error']}"
        if sec.get("warning"):
            status += f" (warning: {sec['warning']})"
        lines.append(f"  {name:20} {len(sec['items']):4} items  {status}")
    return "\n".join(lines)
