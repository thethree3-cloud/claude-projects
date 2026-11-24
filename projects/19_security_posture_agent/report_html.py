"""Render the same report as one self-contained HTML file.

Safety: process names, task names, paths and Claude's text can contain anything,
including HTML. So:
1. Every value is escaped with html.escape. Claude's text is shown as plain
   text, never rendered as Markdown or HTML.
2. A Content-Security-Policy with a random per-report nonce allows only this
   file's own <style> and <script>. Even if an escaping bug let a "<script>"
   through, the browser would refuse to run it.
3. Nothing is loaded from the network (default-src 'none'): no fonts, CDNs or images.
"""

import html
import json
import secrets
from pathlib import Path

from checks import SEVERITY_ORDER
from report import _item_label, clean

DEFAULT_DIR = Path(__file__).parent / "data" / "reports"


def esc(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    return html.escape(value, quote=True)


def _paragraphs(text):
    """Claude's prose as escaped <p> blocks, one per paragraph."""
    parts = [p.strip() for p in (text or "").replace("\r", "").split("\n\n") if p.strip()]
    return "".join(f"<p>{esc(p).replace(chr(10), '<br>')}</p>" for p in parts)


def _evidence(evidence):
    rows = [f"{k}: {clean(v)}" for k, v in (evidence or {}).items() if v not in (None, "", [])]
    return f"<pre>{esc(chr(10).join(rows))}</pre>" if rows else ""


def _finding(n, f):
    open_attr = " open" if f["severity"] in ("high", "medium") else ""
    traits = "".join(f'<span class="trait">{esc(t)}</span>' for t in f["traits"])
    refs = ", ".join(esc(r) for r in f["refs"])
    return (
        f'<details class="finding sev-{esc(f["severity"])}" id="f-{n}" data-sev="{esc(f["severity"])}"{open_attr}>'
        f'<summary><span class="badge">{esc(f["severity"].upper())}</span>'
        f'<span class="num">#{n}</span> {esc(f["title"])}</summary>'
        f'<div class="body">'
        f'<p><b>Why it matters:</b> {esc(f["why"])}</p>'
        f'<p><b>What to do:</b> {esc(f["fix"])}</p>'
        + (f'<p class="traits">{traits}</p>' if traits else "")
        + (f'<p class="label">Evidence <code>{esc(f["section"])}</code></p>{_evidence(f["evidence"])}'
           if f["evidence"] else "")
        + f'<p class="meta">ID <code>{esc(f["id"])}</code>{" · " + refs if refs else ""}</p>'
        "</div></details>"
    )


def _ai(ai, numbers):
    out = ['<section class="ai"><h2>Plain-English summary <small>written by Claude, checked by code</small></h2>']
    if ai.get("error"):
        out.append(f'<p class="muted">Not available: {esc(ai["error"])}. The findings below are complete '
                   "without it.</p></section>")
        return "".join(out)
    v = ai["validated"]
    out.append('<p class="note">Claude grouped and explained the findings below. It can\'t add findings or '
               "change severities; its text was checked against the real findings before being shown, "
               "and the fixes come from the fixed catalog, not from Claude.</p>")
    if v["summary"]:
        out.append(f'<div class="summary">{_paragraphs(v["summary"])}</div>')
    out.append("<ol class=\"groups\">")
    for g in v["groups"]:
        links = " ".join(
            f'<a href="#f-{numbers[f["id"]]}" class="ref sev-{esc(f["severity"])}">#{numbers[f["id"]]}</a>'
            for f in g["findings"])
        body = _paragraphs(g["explanation"]) if g["explanation"] else (
            '<p class="muted">Explanation removed by the validator (see below).</p>'
            if g["title"] != "Other findings" else "")
        out.append(f"<li><h3>{esc(g['title'])} <span class=\"refs\">{links}</span></h3>{body}</li>")
    out.append("</ol>")
    if v["notes"]:
        out.append("<p><b>Claude's notes on severity</b> (shown for review; the rule's severity stands):</p><ul>")
        out += [f'<li><a href="#f-{numbers[x["finding"]["id"]]}">#{numbers[x["finding"]["id"]]}</a> could be '
                f'<b>{esc(x["suggested"])}</b>. {esc(x["reason"])}</li>' for x in v["notes"]]
        out.append("</ul>")
    removed = "".join(f"<li>{esc(r)}</li>" for r in v["rejected"])
    out.append(f'<p class="muted">Checked by validate.py: {len(v["groups"])} group(s), '
               + (f"{len(v['rejected'])} item(s) removed:</p><ul class=\"muted\">{removed}</ul>"
                  if v["rejected"] else "nothing removed.</p>"))
    info = ai.get("info") or {}
    if info:
        out.append(f'<p class="muted small">Model {esc(info.get("model"))} · {esc(info.get("input_tokens"))} '
                   f'input / {esc(info.get("output_tokens"))} output tokens</p>')
    out.append("</section>")
    return "".join(out)


def _changes(changes):
    out = ["<section><h2>Changes since last scan</h2>"]
    if changes is None:
        return "".join(out) + "<p class=\"muted\">Not compared (--no-baseline).</p></section>"
    if changes.get("diff") is None:
        return "".join(out) + ("<p class=\"muted\">No earlier scan to compare with yet. The next scan "
                               "will show what changed.</p></section>")
    d = changes["diff"]
    out.append(f'<p>Compared with <code>{esc(changes["label"])}</code>. Anything already there at that scan '
               "isn't marked new, so a baseline is only as trustworthy as the computer was then. "
               "UDP ports aren't compared.</p>")
    out.append("<table><tr><th>Area</th><th>Added</th><th>Removed</th><th>Changed</th></tr>")
    out += [f"<tr><td>{esc(n)}</td><td>{len(s['added'])}</td><td>{len(s['removed'])}</td>"
            f"<td>{len(s['changed'])}</td></tr>" for n, s in d["sections"].items()]
    out.append("</table>")
    removed = [(n, i) for n, s in d["sections"].items() for i in s["removed"]]
    if removed:
        out.append("<p>Removed since last scan (usually uninstalls or updates):</p><ul>")
        out += [f"<li>{esc(n)}: <code>{esc(_item_label(n, i))}</code></li>" for n, i in removed[:30]]
        if len(removed) > 30:
            out.append(f"<li>…and {len(removed) - 30} more</li>")
        out.append("</ul>")
    if d["skipped"]:
        out.append(f'<p class="muted">Not compared (missing from the older scan, or failed in either): '
                   f'{esc(", ".join(d["skipped"]))}</p>')
    return "".join(out) + "</section>"


def render(snapshot, findings, changes=None, ai=None):
    nonce = secrets.token_urlsafe(16)
    host = ((snapshot["sections"].get("host") or {}).get("items") or [{}])[0]
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITY_ORDER}
    numbers = {f["id"]: n for n, f in enumerate(findings, 1)}
    chips = "".join(
        f'<button class="chip sev-{s}" data-filter="{s}" aria-pressed="false">{s} <b>{counts[s]}</b></button>'
        for s in SEVERITY_ORDER)

    failed = {n: s for n, s in snapshot["sections"].items() if not s["ok"]}
    warned = {n: s for n, s in snapshot["sections"].items() if s.get("warning")}
    gaps = ""
    if failed or warned:
        items = [f"<li><b>{esc(n)}</b>: {esc(s['error'])}</li>" for n, s in failed.items()]
        items += [f"<li><b>{esc(n)}</b> (partial): {esc(s['warning'])}</li>" for n, s in warned.items()]
        gaps = f"<section><h2>Couldn't fully check</h2><ul>{''.join(items)}</ul></section>"
    coverage = "".join(f"<tr><td>{esc(n)}</td><td>{len(s['items']) if s['ok'] else 'failed'}</td></tr>"
                       for n, s in snapshot["sections"].items())

    body = "".join(_finding(numbers[f["id"]], f) for f in findings) or '<p class="muted">No findings.</p>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; base-uri 'none'; form-action 'none'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Security posture report · {esc(snapshot["collected_at"])}</title>
<style nonce="{nonce}">{CSS}</style></head>
<body><main>
<header><h1>Security posture report</h1>
<p class="muted">Scanned <b>{esc(snapshot["collected_at"])}</b> · {esc(host.get("os_caption") or "Windows")}
build {esc(host.get("os_build") or "?")} · admin: {"yes" if host.get("is_admin") else "no"}</p>
<p class="note">Read-only scan: nothing on this computer was changed. Findings come from fixed rules, not AI,
and each one shows the exact evidence it's based on.</p></header>
<nav class="filters" aria-label="Filter by severity"><button class="chip all" data-filter="all" aria-pressed="true">all <b>{len(findings)}</b></button>{chips}
<button class="toggle" data-toggle="open">expand all</button><button class="toggle" data-toggle="close">collapse all</button></nav>
{_ai(ai, numbers) if ai is not None else ""}
<section><h2>Findings</h2><div id="findings">{body}</div></section>
{_changes(changes)}
{gaps}
<section><h2>What was checked</h2><table><tr><th>Area</th><th>Items read</th></tr>{coverage}</table></section>
<footer class="muted small">Holds real machine details. Keep it local; don't share it.</footer>
</main><script nonce="{nonce}">{JS}</script></body></html>
"""


def save(text, snapshot, directory=DEFAULT_DIR):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = snapshot["collected_at"].replace(":", "").replace("-", "").replace("+0000", "Z")
    path = directory / f"report_{stamp}.html"
    path.write_text(text, encoding="utf-8")
    return path


CSS = """
:root{--bg:#fff;--fg:#1f2328;--muted:#656d76;--line:#d8dee4;--card:#f6f8fa;
--high:#c62828;--medium:#b26a00;--low:#1f6feb;--info:#6e7781}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8d96a0;--line:#30363d;
--card:#161b22;--high:#f47067;--medium:#e0a33c;--low:#6cb6ff;--info:#8d96a0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:30px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
h2 small{font-weight:400;color:var(--muted);font-size:13px}h3{font-size:15px;margin:0 0 4px}
.muted{color:var(--muted)}.small{font-size:12px}
.note{background:var(--card);border-left:3px solid var(--line);padding:8px 12px;margin:10px 0}
.filters{position:sticky;top:0;background:var(--bg);padding:10px 0;display:flex;flex-wrap:wrap;gap:6px;
border-bottom:1px solid var(--line);z-index:1}
.chip,.toggle{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--card);color:var(--fg);
border-radius:999px;padding:3px 12px;cursor:pointer}
.chip[aria-pressed=true]{outline:2px solid var(--fg);outline-offset:1px}
.toggle{margin-left:auto}.toggle+.toggle{margin-left:0}
.chip.sev-high b{color:var(--high)}.chip.sev-medium b{color:var(--medium)}.chip.sev-low b{color:var(--low)}
.finding{border:1px solid var(--line);border-left:4px solid var(--info);border-radius:6px;margin:8px 0;background:var(--card)}
.finding.sev-high{border-left-color:var(--high)}.finding.sev-medium{border-left-color:var(--medium)}
.finding.sev-low{border-left-color:var(--low)}
.finding summary{cursor:pointer;padding:9px 12px;font-weight:600}
.finding .body{padding:0 14px 10px}
.badge{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.04em;border-radius:4px;padding:1px 6px;
margin-right:8px;color:#fff;background:var(--info)}
.sev-high .badge{background:var(--high)}.sev-medium .badge{background:var(--medium)}.sev-low .badge{background:var(--low)}
.num{color:var(--muted);font-weight:400;margin-right:4px}
pre{background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:8px 10px;overflow-x:auto;
white-space:pre-wrap;word-break:break-word;font-size:12.5px}
code{font-size:12.5px}.label{margin:8px 0 2px;color:var(--muted)}.meta{color:var(--muted);font-size:12.5px}
.trait{display:inline-block;font-size:12px;border:1px solid var(--line);border-radius:4px;padding:0 6px;margin:0 4px 2px 0}
.ai .summary{font-size:16px}.groups li{margin:10px 0}.refs{font-weight:400}
.ref{text-decoration:none;font-size:12px;border-radius:4px;padding:0 5px;margin-right:3px;border:1px solid var(--line)}
.ref.sev-high{color:var(--high)}.ref.sev-medium{color:var(--medium)}.ref.sev-low{color:var(--low)}.ref.sev-info{color:var(--info)}
table{border-collapse:collapse;font-size:13.5px}td,th{border:1px solid var(--line);padding:4px 10px;text-align:left}
a{color:var(--low)}footer{margin-top:40px}
@media print{.filters{display:none}details>.body{display:block}.finding{break-inside:avoid}}
"""

JS = """
(function(){
  var chips=document.querySelectorAll('.chip'),cards=document.querySelectorAll('.finding');
  chips.forEach(function(c){c.addEventListener('click',function(){
    var f=c.getAttribute('data-filter');
    chips.forEach(function(x){x.setAttribute('aria-pressed',x===c?'true':'false')});
    cards.forEach(function(card){card.hidden=!(f==='all'||card.getAttribute('data-sev')===f)});
  })});
  document.querySelectorAll('.toggle').forEach(function(b){b.addEventListener('click',function(){
    var open=b.getAttribute('data-toggle')==='open';
    cards.forEach(function(card){if(!card.hidden)card.open=open});
  })});
  document.querySelectorAll('a.ref,a[href^="#f-"]').forEach(function(a){a.addEventListener('click',function(){
    var t=document.getElementById(a.getAttribute('href').slice(1));
    if(t){t.hidden=false;t.open=true}
  })});
  window.addEventListener('beforeprint',function(){cards.forEach(function(c){c.hidden=false;c.open=true})});
})();
"""
