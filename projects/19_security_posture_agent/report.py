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


def _item_label(section, item):
    if section == "scheduled_tasks":
        return item["task"]
    if section == "run_keys":
        return f"{item['key']}\\{item['name']}"
    if section == "listening_ports":
        return f"tcp/{item['port']} {item.get('process') or '?'}"
    return item.get("name") or item.get("path") or "?"


def _changes_section(changes):
    out = ["## Changes since last scan", ""]
    if changes is None:
        return out + ["Not compared (`--no-baseline`).", ""]
    if changes.get("diff") is None:
        return out + ["No earlier scan to compare with yet. The next scan will show what changed.", ""]
    d = changes["diff"]
    out += [
        f"Compared with `{_inline(changes['label'])}`. Anything that was already there at "
        "that scan isn't marked new, so a baseline is only as trustworthy as the computer "
        "was then. UDP ports aren't compared (browsers open and close them constantly).",
        "",
        "| Area | Added | Removed | Changed |",
        "|---|---|---|---|",
    ]
    for name, sd in d["sections"].items():
        out.append(f"| {name} | {len(sd['added'])} | {len(sd['removed'])} | {len(sd['changed'])} |")
    out.append("")
    removed = [(n, i) for n, sd in d["sections"].items() for i in sd["removed"]]
    if removed:
        out += ["Removed since last scan (usually uninstalls or updates):", ""]
        out += [f"- {n}: `{_inline(_item_label(n, i))}`" for n, i in removed[:30]]
        if len(removed) > 30:
            out.append(f"- ...and {len(removed) - 30} more")
        out.append("")
    if d["skipped"]:
        out += [f"Not compared (missing from the older scan, or failed in either): "
                f"{', '.join(d['skipped'])}", ""]
    return out


def render(snapshot, findings, changes=None):
    """changes: None = comparison turned off; {'diff': None} = no baseline yet;
    {'diff': ..., 'label': ...} = compared."""
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

    out += _changes_section(changes)

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
