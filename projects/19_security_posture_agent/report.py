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
PARTIAL_SCAN_NOTE = ("Partial scan: this ran without admin rights, so Defender exclusions, BitLocker and "
                     "the program behind most listening ports weren't checked. For a full scan, open "
                     "PowerShell as Administrator and run the scan from there (scan.py prints the exact command).")
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


def _prose(text):
    """Claude's text, made safe to drop into Markdown: no raw HTML, headings or images."""
    text = _CONTROL.sub(" ", text or "").replace("<", "&lt;").replace("![", "!\\[")
    lines = [re.sub(r"^\s*#+\s*", "", line) for line in text.splitlines()]
    return "\n".join(lines).strip()


def _ai_section(ai, numbers):
    out = ["## Plain-English summary (written by Claude, checked by code)", ""]
    if ai.get("error"):
        return out + [f"Not available: {_inline(ai['error'])}. The findings below are complete "
                      "without it.", ""]
    v = ai["validated"]
    out += ["> Claude grouped and explained the findings below. It can't add findings or change "
            "severities, and its text was checked against the real findings before being shown. "
            "The fixes come from the fixed catalog, not from Claude.", ""]
    if v["summary"]:
        out += [_prose(v["summary"]), ""]
    for n, g in enumerate(v["groups"], 1):
        refs = ", ".join(f"#{numbers[f['id']]} [{f['severity'].upper()}]" for f in g["findings"])
        out += [f"**{n}. {_inline(g['title'])}** ({refs})", ""]
        if g["explanation"]:
            out += [_prose(g["explanation"]), ""]
        elif g["title"] != "Other findings":
            out += ["_Explanation removed by the validator (see below)._", ""]
    if v["notes"]:
        out += ["Claude's notes on severity (shown for review; the rule's severity stands):", ""]
        out += [f"- #{numbers[x['finding']['id']]}: could be **{x['suggested']}**. {_prose(x['reason'])}"
                for x in v["notes"]]
        out.append("")
    checked = f"Checked by validate.py: {len(v['groups'])} group(s)"
    if v["rejected"]:
        out += [checked + f", {len(v['rejected'])} item(s) removed:", ""]
        out += [f"- {_inline(r)}" for r in v["rejected"]]
    else:
        out.append(checked + ", nothing removed.")
    info = ai.get("info") or {}
    if info:
        out += ["", f"<sub>Model {_inline(info.get('model'))} · {info.get('input_tokens')} input / "
                    f"{info.get('output_tokens')} output tokens</sub>"]
    out.append("")
    return out


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
        out += [f"Not compared ({skipped_reason(d)}): {', '.join(d['skipped'])}", ""]
    return out


def skipped_reason(d):
    if d.get("admin_mismatch"):
        return ("one scan ran as admin and the other didn't, so these would show items that were only "
                "hidden before as 'new'; or the section was missing or failed")
    return "missing from the older scan, or failed in either"


def render(snapshot, findings, changes=None, ai=None):
    """changes: None = comparison turned off; {'diff': None} = no baseline yet;
    {'diff': ..., 'label': ...} = compared.
    ai: None = not requested; {'error': str} or {'validated': ..., 'info': ...}."""
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
    ]
    if h.get("is_admin") is False:
        out += [f"> **{PARTIAL_SCAN_NOTE}**", ""]
    out += [
        "## Summary",
        "",
        "| Severity | Count |",
        "|---|---|",
    ]
    for sev in SEVERITY_ORDER:
        out.append(f"| {sev} | {sum(1 for f in findings if f['severity'] == sev)} |")
    out.append("")

    if ai is not None:
        out += _ai_section(ai, {f["id"]: n for n, f in enumerate(findings, 1)})

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
