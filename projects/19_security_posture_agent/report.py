"""Render findings as a Markdown report (no LLM).

Evidence values come straight from the machine. Process names, task names
and paths can contain any text, so they're cleaned and kept inside code
blocks: shown as data, never as Markdown or instructions.
"""

import json
import re
from pathlib import Path

from checks import SEVERITY_ORDER

DEFAULT_DIR = Path(__file__).parent / "data" / "reports"
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean(value, limit=500):
    """One safe line of text for a code block."""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    value = _CONTROL.sub(" ", value).replace("\n", " ").replace("```", "'''")
    return value if len(value) <= limit else value[:limit] + "..."


def _inline(value):
    """Safe text for a heading or table cell."""
    return clean(value, 200).replace("|", "/").replace("`", "'").replace("<", "&lt;")


def _evidence_block(evidence):
    if not evidence:
        return ""
    lines = [f"{k}: {clean(v)}" for k, v in evidence.items() if v not in (None, "", [])]
    return "```text\n" + "\n".join(lines) + "\n```\n" if lines else ""


def render(snapshot, findings):
    host = (snapshot["sections"].get("host") or {}).get("items") or [{}]
    h = host[0]
    out = [
        "# Security posture report",
        "",
        f"Scanned **{snapshot['collected_at']}** · {_inline(h.get('os_caption') or 'Windows')} "
        f"build {_inline(h.get('os_build') or '?')} · admin: {'yes' if h.get('is_admin') else 'no'}",
        "",
        "> Read-only scan: nothing on this computer was changed. Findings come from fixed "
        "rules, not AI. Each one shows the exact evidence it's based on.",
        "",
        "## Summary",
        "",
        "| Severity | Count |",
        "|---|---|",
    ]
    for sev in SEVERITY_ORDER:
        out.append(f"| {sev} | {sum(1 for f in findings if f['severity'] == sev)} |")
    out.append("")

    out.append("## Findings")
    out.append("")
    if not findings:
        out.append("No findings.")
        out.append("")
    for n, f in enumerate(findings, 1):
        out += [
            f"### {n}. [{f['severity'].upper()}] {_inline(f['title'])}",
            "",
            f"**Why it matters:** {f['why']}",
            "",
            f"**What to do:** {f['fix']}",
            "",
        ]
        if f["traits"]:
            out += [f"**Traits:** {', '.join(f['traits'])}", ""]
        block = _evidence_block(f["evidence"])
        if block:
            out += [f"**Evidence** (`{f['section']}`):", "", block]
        meta = f"ID `{f['id']}`"
        if f["refs"]:
            meta += " · " + ", ".join(f["refs"])
        out += [meta, ""]

    failed = {n: s for n, s in snapshot["sections"].items() if not s["ok"]}
    warned = {n: s for n, s in snapshot["sections"].items() if s.get("warning")}
    if failed or warned:
        out += ["## Couldn't fully check", ""]
        for n, s in failed.items():
            out.append(f"- **{n}**: {_inline(s['error'])}")
        for n, s in warned.items():
            out.append(f"- **{n}** (partial): {_inline(s['warning'])}")
        out.append("")

    out += ["## What was checked", "", "| Area | Items read |", "|---|---|"]
    for n, s in snapshot["sections"].items():
        out.append(f"| {n} | {len(s['items']) if s['ok'] else 'failed'} |")
    out.append("")
    return "\n".join(out)


def save_report(text, snapshot, directory=DEFAULT_DIR):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = snapshot["collected_at"].replace(":", "").replace("-", "").replace("+0000", "Z")
    path = directory / f"report_{stamp}.md"
    path.write_text(text, encoding="utf-8")
    return path
