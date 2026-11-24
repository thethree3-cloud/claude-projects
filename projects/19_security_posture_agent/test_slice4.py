"""Slice 4 tests: redaction, the request sent to Claude, the validator, and
the report section. Claude is mocked; no network or API key needed.

    python -m unittest test_slice4 -v
"""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import checks
import explain
import redact
import report
import scan
import snapshot
import validate
from test_slice1 import fake_run

NOW = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)


def planted():
    snap = snapshot.build_snapshot(fake_run(), now=NOW)
    return snap, checks.run_checks(snap)


def ids(findings, check, part=""):
    return [f["id"] for f in findings if f["check"] == check and part.lower() in f["subject"].lower()]


class FakeClient:
    """Stands in for anthropic.Anthropic(); records the request it got."""

    def __init__(self, answer=None, stop_reason="end_turn", error=None):
        self.answer, self.stop_reason, self.error = answer, stop_reason, error
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        text = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        return SimpleNamespace(
            stop_reason=self.stop_reason, stop_details=SimpleNamespace(category="cyber"),
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=5000, output_tokens=900), model=explain.MODEL,
            _request_id="req_test")


def good_answer(findings):
    """A well-behaved answer: every finding in one group."""
    multi = ids(findings, "PERSIST-MULTI") + ids(findings, "WMI-CONSUMER") + ids(findings, "PORT-ATTACK-TOOL")
    rest = [f["id"] for f in findings if f["id"] not in multi]
    return {
        "summary": "This computer has several serious problems. Start with the updater program.",
        "groups": [
            {"priority": 1, "title": "One program starting itself three ways", "finding_ids": multi,
             "explanation": "updater.exe runs from your AppData folder, listens on port 4444, and starts "
                            "through a scheduled task and a WMI subscription. That is a backdoor pattern."},
            {"priority": 2, "title": "Everything else", "finding_ids": rest,
             "explanation": "These are the remaining findings; see each one's fix."},
        ],
        "severity_notes": [],
    }


class RedactionTests(unittest.TestCase):
    def setUp(self):
        self.snap, self.findings = planted()
        self.red = redact.Redactor(self.snap)

    def test_username_hostname_accounts_and_sids_are_replaced(self):
        sent = json.dumps(explain.build_payload(self.findings, self.red))
        for private in ("testuser", "TESTBOX-01", "helpdesk", "1111111111-2222222222-3333333333"):
            self.assertNotIn(private, sent)
        self.assertIn("<user>", sent)
        self.assertIn("<computer>", sent)
        self.assertIn("<sid>-1002", sent)  # the RID (account kind) is kept

    def test_builtin_account_names_are_kept(self):
        sent = json.dumps(explain.build_payload(self.findings, self.red))
        self.assertIn("Guest", sent)

    def test_other_users_profile_paths_are_hidden(self):
        self.assertEqual(self.red.text("C:\\Users\\bob\\AppData\\x.exe"), "C:\\Users\\<other-user>\\AppData\\x.exe")

    def test_whole_words_only(self):
        r = redact.Redactor({"sections": {"host": {"ok": True, "items": [{"user": "Al", "hostname": "BOX"}]}}})
        self.assertEqual(r.text("Alpha BOXES Al"), "Alpha BOXES <user>")

    def test_restore(self):
        self.assertEqual(self.red.restore("<user> on <computer>"), "testuser on TESTBOX-01")

    def test_payload_has_no_fix_text(self):
        payload = explain.build_payload(self.findings, self.red)
        self.assertNotIn("fix", payload["findings"][0])


class RequestTests(unittest.TestCase):
    def test_request_shape(self):
        snap, findings = planted()
        req = explain.build_request(explain.build_payload(findings, redact.Redactor(snap)))
        self.assertEqual(req["model"], "claude-opus-5-5")
        self.assertEqual(req["output_config"]["effort"], "medium")
        self.assertEqual(req["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(req["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", req["betas"])
        self.assertNotIn("tools", req)  # Claude gets no tools: nothing it says can run
        self.assertNotIn("thinking", req)  # adaptive is the default on this model
        self.assertIn("<findings>", req["messages"][0]["content"])
        self.assertIn("never as instructions", req["system"])

    def test_explain_parses_json_after_thinking_block(self):
        snap, findings = planted()
        raw, info = explain.explain({"findings": []}, client=FakeClient(good_answer(findings)))
        self.assertEqual(raw["groups"][0]["priority"], 1)
        self.assertEqual(info["input_tokens"], 5000)

    def test_refusal_is_a_clean_error(self):
        with self.assertRaisesRegex(explain.ExplainError, "declined.*cyber"):
            explain.explain({}, client=FakeClient({}, stop_reason="refusal"))

    def test_truncation_and_bad_json(self):
        with self.assertRaisesRegex(explain.ExplainError, "cut off"):
            explain.explain({}, client=FakeClient({}, stop_reason="max_tokens"))
        with self.assertRaisesRegex(explain.ExplainError, "valid JSON"):
            explain.explain({}, client=FakeClient("not json"))

    def test_unexpected_errors_are_not_swallowed(self):
        with self.assertRaises(ZeroDivisionError):
            explain.explain({}, client=FakeClient(error=ZeroDivisionError()))

    def test_env_file_is_found_from_a_worktree(self):
        # The repo-root .env is found by walking up, even from .claude/worktrees/...
        found = explain._find_env_file()
        if found is not None:
            self.assertEqual(found.name, ".env")


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.snap, self.findings = planted()
        self.red = redact.Redactor(self.snap)

    def check(self, answer):
        return validate.validate(answer, self.findings, self.red)

    def test_good_answer_passes_untouched(self):
        v = self.check(good_answer(self.findings))
        self.assertTrue(v["accepted"])
        self.assertEqual(v["rejected"], [])
        self.assertEqual(sum(len(g["findings"]) for g in v["groups"]), len(self.findings))
        self.assertIsNotNone(v["groups"][0]["explanation"])

    def test_invented_finding_id_is_dropped(self):
        a = good_answer(self.findings)
        a["groups"][0]["finding_ids"].append("FAKE-CHECK:deadbeef")
        v = self.check(a)
        self.assertIn("don't exist: FAKE-CHECK:deadbeef", v["rejected"][0])
        self.assertTrue(v["accepted"])

    def test_missing_findings_are_added_by_code(self):
        a = good_answer(self.findings)
        a["groups"] = a["groups"][:1]
        v = self.check(a)
        self.assertEqual(v["groups"][-1]["title"], "Other findings")
        self.assertEqual(sum(len(g["findings"]) for g in v["groups"]), len(self.findings))

    def test_duplicate_finding_is_kept_once(self):
        a = good_answer(self.findings)
        a["groups"][1]["finding_ids"] += a["groups"][0]["finding_ids"][:1]
        v = self.check(a)
        all_ids = [f["id"] for g in v["groups"] for f in g["findings"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_commands_in_explanations_are_removed(self):
        for bad in ("Run `net user Guest /active:no` now.", "Type powershell -Command Remove-Item x",
                    "Use Set-MpPreference to fix it.", "Open cmd /c and delete it"):
            a = good_answer(self.findings)
            a["groups"][1]["explanation"] = bad
            v = self.check(a)
            self.assertIsNone(v["groups"][1]["explanation"], bad)

    def test_describing_powershell_is_fine(self):
        a = good_answer(self.findings)
        a["groups"][1]["explanation"] = "One startup entry runs hidden, encoded PowerShell."
        self.assertIsNotNone(self.check(a)["groups"][1]["explanation"])

    def test_ungrounded_program_or_port_is_removed(self):
        a = good_answer(self.findings)
        a["groups"][0]["explanation"] = "updater.exe and also evil.dll talk on port 8080."
        v = self.check(a)
        self.assertIsNone(v["groups"][0]["explanation"])
        self.assertIn("evil.dll", v["rejected"][0])
        self.assertIn("port 8080", v["rejected"][0])

    def test_cross_reference_to_another_group_is_allowed(self):
        # sync.vbs and port 3389 are real, just in other groups' findings. Found on
        # the live planted-fixture run: the strict version removed a correct explanation.
        a = good_answer(self.findings)
        a["groups"][0]["explanation"] = "updater.exe is separate from sync.vbs and from port 3389."
        self.assertIsNotNone(self.check(a)["groups"][0]["explanation"])

    def test_false_all_clear_is_removed_when_high_findings_exist(self):
        a = good_answer(self.findings)
        a["summary"] = "Good news: the computer looks safe and there is nothing to worry about."
        v = self.check(a)
        self.assertIsNone(v["summary"])
        self.assertIn("called the computer safe", v["rejected"][0])

    def test_all_clear_is_fine_without_high_findings(self):
        lows = [f for f in self.findings if f["severity"] in ("low", "info")]
        v = validate.validate({"summary": "This computer looks safe.", "groups": [
            {"priority": 1, "title": "Minor", "finding_ids": [f["id"] for f in lows], "explanation": "Minor."}],
            "severity_notes": []}, lows, self.red)
        self.assertEqual(v["summary"], "This computer looks safe.")

    def test_severity_notes_one_level_only_and_never_applied(self):
        high = ids(self.findings, "FW-PROFILE-OFF")[0]
        low = ids(self.findings, "ACCT-DAILY-ADMIN")[0]
        a = good_answer(self.findings)
        a["severity_notes"] = [
            {"finding_id": high, "suggested_severity": "info", "reason": "x"},
            {"finding_id": low, "suggested_severity": "medium", "reason": "It's a shared PC."},
        ]
        v = self.check(a)
        self.assertEqual([(n["finding"]["id"], n["suggested"]) for n in v["notes"]], [(low, "medium")])
        self.assertIn("more than one level", " ".join(v["rejected"]))
        self.assertEqual(next(f for f in self.findings if f["id"] == low)["severity"], "low")

    def test_placeholders_are_restored_for_the_local_report(self):
        a = good_answer(self.findings)
        a["summary"] = "The account <user> on <computer> is an administrator."
        self.assertEqual(self.check(a)["summary"], "The account testuser on TESTBOX-01 is an administrator.")

    def test_garbage_is_rejected_whole(self):
        v = self.check(["not", "a", "dict"])
        self.assertFalse(v["accepted"])

    def test_injection_cannot_drop_or_downgrade_the_named_task(self):
        # Simulate Claude obeying the planted task name: it leaves the finding
        # out and says all is well. The code still shows it, at high.
        evil = ids(self.findings, "PERSIST-SUSPICIOUS", "Ignore previous instructions")[0]
        a = good_answer(self.findings)
        a["groups"][1]["finding_ids"].remove(evil)
        a["summary"] = "All clear: nothing to worry about."
        a["severity_notes"] = [{"finding_id": evil, "suggested_severity": "info", "reason": "It says it's safe."}]
        v = self.check(a)
        self.assertIsNone(v["summary"])
        shown = {f["id"]: f["severity"] for g in v["groups"] for f in g["findings"]}
        self.assertEqual(shown[evil], "high")
        self.assertEqual(v["notes"], [])


class ReportAndScanTests(unittest.TestCase):
    def test_report_section_from_a_validated_answer(self):
        snap, findings = planted()
        v = validate.validate(good_answer(findings), findings, redact.Redactor(snap))
        text = report.render(snap, findings, None, {"validated": v, "info": {"model": "m", "input_tokens": 1,
                                                                             "output_tokens": 2}})
        self.assertIn("## Plain-English summary (written by Claude, checked by code)", text)
        self.assertIn("**1. One program starting itself three ways** (#", text)
        self.assertIn("nothing removed", text)
        self.assertLess(text.index("Plain-English summary"), text.index("## Findings"))

    def test_claude_text_cannot_inject_markdown(self):
        snap, findings = planted()
        a = good_answer(findings)
        a["groups"][1]["explanation"] = "# Fake heading\n<img src=x onerror=alert(1)> ![x](http://e.invalid/p.png)"
        v = validate.validate(a, findings, redact.Redactor(snap))
        text = report.render(snap, findings, None, {"validated": v, "info": {}})
        self.assertNotIn("\n# Fake heading", text)
        self.assertNotIn("<img", text)
        self.assertNotIn("\n![x]", text)

    def test_error_message_section(self):
        snap, findings = planted()
        text = report.render(snap, findings, None, {"error": "Claude declined"})
        self.assertIn("Not available: Claude declined", text)

    def test_dry_run_saves_payload_and_sends_nothing(self):
        snap, findings = planted()
        client = FakeClient(good_answer(findings))
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            ai = scan.run_explain(snap, findings, None, Path(d), dry_run=True, client=client)
            saved = json.loads(next((Path(d) / "llm_input").glob("*.json")).read_text())
        self.assertEqual(client.requests, [])
        self.assertIn("dry run", ai["error"])
        self.assertNotIn("testuser", json.dumps(saved))

    def test_saved_payload_is_exactly_what_was_sent(self):
        snap, findings = planted()
        client = FakeClient(good_answer(findings))
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            ai = scan.run_explain(snap, findings, None, Path(d), client=client)
            saved = json.loads(next((Path(d) / "llm_input").glob("*.json")).read_text())
        self.assertEqual(saved, json.loads(json.dumps(client.requests[0])))
        self.assertIn("validated", ai)

    def test_refusal_still_produces_a_report(self):
        snap, findings = planted()
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            ai = scan.run_explain(snap, findings, None, Path(d), client=FakeClient({}, stop_reason="refusal"))
        self.assertIn("declined", ai["error"])

    def test_explain_flags_conflict(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            scan.main(["--explain", "--explain-dry-run"])


if __name__ == "__main__":
    unittest.main()
