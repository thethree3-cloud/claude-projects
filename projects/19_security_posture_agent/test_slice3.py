"""Slice 3 tests: baseline diff, change findings, and Startup shortcut targets.

    python -m unittest test_slice3 -v
"""

import contextlib
import io
import json
import struct
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import baseline
import checks
import collectors
import lnk
import report
import runner
import scan
import snapshot
from test_slice1 import RECORDED, fake_run

T0 = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(days=7)


def fixture(name):
    return json.loads((RECORDED / f"{name}.json").read_text())


def ok(name, data):
    return runner.RunResult(name, True, json.dumps(data))


def snap(overrides=None, now=T1):
    return snapshot.build_snapshot(fake_run(overrides), now=now)


def with_added(name, *rows):
    return {name: ok(name, fixture(name) + list(rows))}


def change_findings(new_overrides, old_overrides=None):
    old, new = snap(old_overrides, T0), snap(new_overrides, T1)
    return baseline.findings_from_diff(baseline.diff(old, new), "base")


def only(findings, check):
    return [f for f in findings if f["check"] == check]


# --- Shortcut builder (MS-SHLLINK), used to make test .lnk files ----------------------

def make_lnk(target=None, arguments=None, env_target=None):
    flags = lnk.IS_UNICODE
    body = b""
    if target:
        flags |= lnk.HAS_LINK_INFO
        path = target.encode("cp1252") + b"\x00"
        header_size = 0x1C
        local_off = header_size + 4          # after header + a tiny fake VolumeID
        suffix_off = local_off + len(path)
        info = struct.pack("<IIIIIII", 0, header_size, 1, header_size, local_off, 0, suffix_off)
        info += b"\x04\x00\x00\x00" + path + b"\x00"
        info = struct.pack("<I", len(info)) + info[4:]
        body += info
    if arguments:
        flags |= lnk.HAS_ARGUMENTS
        body += struct.pack("<H", len(arguments)) + arguments.encode("utf-16-le")
    if env_target:
        block = struct.pack("<II", 0x314, 0xA0000001)
        block += env_target.encode("cp1252").ljust(260, b"\x00")
        block += env_target.encode("utf-16-le").ljust(520, b"\x00")
        body += block
    body += b"\x00\x00\x00\x00"  # terminal block
    header = struct.pack("<I", 0x4C) + bytes.fromhex("0114020000000000c000000000000046")
    header += struct.pack("<I", flags) + b"\x00" * (0x4C - 24)
    return header + body


class LnkTests(unittest.TestCase):
    def test_target_and_arguments(self):
        r = lnk.parse_lnk(make_lnk("C:\\Program Files\\App\\app.exe", "--quiet"))
        self.assertEqual(r, {"target": "C:\\Program Files\\App\\app.exe", "arguments": "--quiet"})

    def test_environment_variable_target(self):
        r = lnk.parse_lnk(make_lnk(env_target="%windir%\\system32\\charmap.exe"))
        self.assertEqual(r["target"], "%windir%\\system32\\charmap.exe")

    def test_not_a_shortcut(self):
        self.assertIsNone(lnk.parse_lnk(b"MZ\x90\x00" + b"\x00" * 100))
        self.assertIsNone(lnk.parse_lnk(b""))

    def test_truncated_shortcut_is_rejected_not_crashing(self):
        data = make_lnk("C:\\x.exe", "a long argument string here")
        self.assertIsNone(lnk.parse_lnk(data[:-30]))

    def test_windows_to_wsl_path(self):
        self.assertEqual(str(lnk.windows_to_wsl_path("C:\\Users\\a\\x.lnk")), "/mnt/c/Users/a/x.lnk")
        self.assertIsNone(lnk.windows_to_wsl_path("\\\\server\\share\\x.lnk"))
        self.assertIsNone(lnk.windows_to_wsl_path("relative\\x.lnk"))

    def test_startup_shortcut_launching_encoded_powershell_is_high(self):
        startup = ok("win_startup_folders", [{
            "Folder": "C:\\Users\\testuser\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup",
            "Name": "OneDrive.lnk", "FullName": "C:\\Users\\testuser\\Startup\\OneDrive.lnk",
            "Length": 1200, "LastWriteUtc": "2026-01-01T00:00:00.0000000Z"}])
        data = make_lnk("C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
                        "-w hidden -enc SQBFAFgAIAAoAE4A")
        sec = collectors.collect_startup_items(fake_run({"win_startup_folders": startup}),
                                               read_file=lambda p: data)
        self.assertIn("powershell.exe", sec["items"][0]["target"])
        s = snap({"win_startup_folders": startup})
        s["sections"]["startup_items"] = sec
        hit = [f for f in checks.check_persistence(s) if f["subject"] == "OneDrive.lnk"]
        self.assertEqual(hit[0]["severity"], "high")
        self.assertIn("encoded_powershell", hit[0]["traits"])

    def test_unreadable_shortcut_is_noted(self):
        startup = ok("win_startup_folders", [{"Folder": "x", "Name": "a.lnk", "FullName": "C:\\a.lnk",
                                              "Length": 1, "LastWriteUtc": None}])
        sec = collectors.collect_startup_items(fake_run({"win_startup_folders": startup}),
                                               read_file=lambda p: None)
        self.assertEqual(sec["items"][0]["shortcut_error"], "couldn't read shortcut")


class NoNoiseTests(unittest.TestCase):
    def test_identical_scans_have_no_changes(self):
        d = baseline.diff(snap(now=T0), snap(now=T1))
        for name, sd in d["sections"].items():
            self.assertEqual((sd["added"], sd["removed"], sd["changed"]), ([], [], []), name)
        self.assertEqual(baseline.findings_from_diff(d, "base"), [])

    def test_udp_churn_is_ignored(self):
        f = change_findings(with_added("win_listen_udp", {"LocalAddress": "0.0.0.0", "LocalPort": 5555,
                                                          "OwningProcess": 1300}))
        self.assertEqual(f, [])

    def test_dynamic_port_number_change_is_ignored(self):
        old = with_added("win_listen_tcp", {"LocalAddress": "0.0.0.0", "LocalPort": 49670, "OwningProcess": 1100})
        new = with_added("win_listen_tcp", {"LocalAddress": "0.0.0.0", "LocalPort": 49733, "OwningProcess": 1100})
        self.assertEqual(change_findings(new, old), [])

    def test_older_snapshot_format_is_skipped_not_all_new(self):
        old = snap(now=T0)
        for name in ("defender", "local_admins", "local_users"):
            del old["sections"][name]
        d = baseline.diff(old, snap())
        self.assertIn("local_admins", d["skipped"])
        self.assertEqual(only(baseline.findings_from_diff(d, "base"), "NEW-ADMIN"), [])

    def test_failed_section_is_skipped(self):
        down = runner.RunResult("win_scheduled_tasks", False, error="Access is denied.")
        d = baseline.diff(snap({"win_scheduled_tasks": down}, T0), snap())
        self.assertIn("scheduled_tasks", d["skipped"])

    def test_new_disabled_task_is_not_flagged(self):
        task = {"TaskPath": "\\", "TaskName": "Off", "State": "Disabled", "Author": "", "UserId": "",
                "RunLevel": "", "Execute": "C:\\Users\\a\\AppData\\x.exe", "Arguments": None, "ClassId": None}
        self.assertEqual(change_findings(with_added("win_scheduled_tasks", task)), [])


class NewItemTests(unittest.TestCase):
    TASK = {"TaskPath": "\\", "TaskName": "Helper", "State": "Ready", "Author": "", "UserId": "testuser",
            "RunLevel": "Limited", "Arguments": None, "ClassId": None}

    def test_new_task_from_user_folder_is_raised_to_medium(self):
        task = {**self.TASK, "Execute": "C:\\Users\\testuser\\AppData\\Local\\h\\h.exe"}
        f = only(change_findings(with_added("win_scheduled_tasks", task)), "NEW-PERSISTENCE")
        self.assertEqual([(x["subject"], x["severity"]) for x in f], [("\\Helper", "medium")])
        self.assertIn("compared_with", f[0]["evidence"])

    def test_new_task_from_program_files_is_info(self):
        task = {**self.TASK, "Execute": "C:\\Program Files\\Vendor\\update.exe"}
        f = only(change_findings(with_added("win_scheduled_tasks", task)), "NEW-PERSISTENCE")
        self.assertEqual(f[0]["severity"], "info")

    def test_new_encoded_run_key_is_high(self):
        key = {"Key": "HKCU:\\Run", "Name": "Svc", "Value": "powershell -w hidden -enc SQBFAFgAIAAoAE4A"}
        f = only(change_findings(with_added("win_run_keys", key)), "NEW-PERSISTENCE")
        self.assertEqual(f[0]["severity"], "high")

    def test_new_service_and_wmi_consumer(self):
        svc = {"Name": "NewSvc", "DisplayName": "", "PathName": "C:\\Users\\Public\\s.exe", "State": "Running",
               "StartName": "LocalSystem"}
        wmi = {"Kind": "consumer", "Class": "CommandLineEventConsumer", "Name": "Late", "ScriptText": None,
               "CommandLine": "C:\\ProgramData\\l\\l.exe", "Query": None}
        f = change_findings({**with_added("win_auto_services", svc), **with_added("win_wmi_subscriptions", wmi)})
        self.assertEqual({x["subject"] for x in only(f, "NEW-PERSISTENCE")}, {"NewSvc", "Late"})

    def test_hijacked_run_key_is_a_change(self):
        keys = fixture("win_run_keys")
        keys[1] = {**keys[1], "Value": "C:\\Users\\testuser\\AppData\\Roaming\\od\\OneDrive.exe"}
        f = only(change_findings({"win_run_keys": ok("win_run_keys", keys)}), "CHANGED-PERSISTENCE")
        self.assertEqual(len(f), 1)
        self.assertIn("Program Files", f[0]["evidence"]["before"])
        self.assertIn("AppData", f[0]["evidence"]["after"])
        self.assertEqual(f[0]["severity"], "medium")

    def test_harmless_path_update_is_low(self):
        svcs = fixture("win_auto_services")
        old = {"win_auto_services": ok("win_auto_services", svcs + [
            {"Name": "WinDefend", "DisplayName": "", "State": "Running", "StartName": "LocalSystem",
             "PathName": "\"C:\\Program Files\\Windows Defender\\4.18.1\\MsMpEng.exe\""}])}
        new = {"win_auto_services": ok("win_auto_services", svcs + [
            {"Name": "WinDefend", "DisplayName": "", "State": "Running", "StartName": "LocalSystem",
             "PathName": "\"C:\\Program Files\\Windows Defender\\4.18.2\\MsMpEng.exe\""}])}
        f = only(change_findings(new, old), "CHANGED-PERSISTENCE")
        self.assertEqual(f[0]["severity"], "low")

    def test_new_admin_and_user(self):
        sid = "S-1-5-21-1111111111-2222222222-3333333333-1003"
        new = {**with_added("win_local_admins", {"Name": "TESTBOX-01\\svc_backup", "ObjectClass": "User",
                                                 "Source": "Local", "SID": sid}),
               **with_added("win_local_users", {"Name": "svc_backup", "Enabled": True, "PasswordRequired": True,
                                                "Source": "Local", "SID": sid})}
        f = change_findings(new)
        self.assertEqual([x["severity"] for x in only(f, "NEW-ADMIN")], ["high"])
        self.assertEqual([x["severity"] for x in only(f, "NEW-USER")], ["medium"])

    def test_reenabled_account(self):
        users = fixture("win_local_users")
        users[0] = {**users[0], "Enabled": True}  # built-in Administrator turned on
        f = change_findings({"win_local_users": ok("win_local_users", users)})
        self.assertEqual([x["subject"] for x in only(f, "ACCOUNT-REENABLED")], ["Administrator"])

    def test_new_vnc_listener_is_medium(self):
        f = change_findings(with_added("win_listen_tcp", {"LocalAddress": "0.0.0.0", "LocalPort": 5900,
                                                          "OwningProcess": 1100}))
        self.assertEqual([x["severity"] for x in only(f, "NEW-LISTENER")], ["medium"])

    def test_new_loopback_listener_is_ignored(self):
        f = change_findings(with_added("win_listen_tcp", {"LocalAddress": "127.0.0.1", "LocalPort": 9000,
                                                          "OwningProcess": 1100}))
        self.assertEqual(f, [])


class WeakenedSettingTests(unittest.TestCase):
    def _defender(self, **changes):
        d = fixture("win_defender")[0]
        return {"win_defender": ok("win_defender", [{**d, **changes}])}

    def test_defender_turned_off(self):
        old = self._defender(IsTamperProtected=True)
        new = self._defender(IsTamperProtected=False, RealTimeProtectionEnabled=False)
        subjects = {f["subject"] for f in only(change_findings(new, old), "SETTING-WEAKENED")}
        self.assertEqual(subjects, {"Defender real-time protection", "Defender tamper protection"})

    def test_new_exclusion(self):
        old = self._defender()
        new = self._defender(ExclusionPath=fixture("win_defender")[0]["ExclusionPath"] + ["C:\\Temp\\x"])
        f = only(change_findings(new, old), "SETTING-WEAKENED")
        self.assertEqual([x["subject"] for x in f], ["new Defender exclusion (path) C:\\Temp\\x"])

    def test_firewall_and_rdp(self):
        old = {"win_firewall_profiles": ok("win_firewall_profiles", [{"Name": "Private", "Enabled": "True"}]),
               "win_rdp_settings": ok("win_rdp_settings", [{"DenyConnections": 1, "NlaRequired": 1, "Port": 3389}])}
        new = {"win_firewall_profiles": ok("win_firewall_profiles", [{"Name": "Private", "Enabled": "False"}]),
               "win_rdp_settings": ok("win_rdp_settings", [{"DenyConnections": 0, "NlaRequired": 0, "Port": 3389}])}
        f = {(x["subject"], x["severity"]) for x in only(change_findings(new, old), "SETTING-WEAKENED")}
        self.assertEqual(f, {("Firewall Private profile", "high"), ("Remote Desktop", "medium"),
                             ("Remote Desktop Network Level Authentication", "high")})


class BaselinePickTests(unittest.TestCase):
    def test_picks_the_scan_just_before(self):
        with tempfile.TemporaryDirectory() as d:
            for stamp in ("20261101T000000Z", "20261108T000000Z", "20261115T000000Z"):
                (Path(d) / f"snapshot_{stamp}.json").write_text("{}")
            middle = Path(d) / "snapshot_20261108T000000Z.json"
            self.assertTrue(baseline.previous_snapshot_path(d, middle).endswith("20261101T000000Z.json"))
            first = Path(d) / "snapshot_20261101T000000Z.json"
            self.assertIsNone(baseline.previous_snapshot_path(d, first))


class ReportAndScanTests(unittest.TestCase):
    def test_no_baseline_message(self):
        text = report.render(snap(), [], {"diff": None})
        self.assertIn("No earlier scan to compare with yet", text)

    def test_removed_items_are_listed_and_cleaned(self):
        old_tasks = fixture("win_scheduled_tasks") + [{
            "TaskPath": "\\", "TaskName": "gone`|<b>", "State": "Ready", "Author": "", "UserId": "",
            "RunLevel": "", "Execute": "x.exe", "Arguments": None, "ClassId": None}]
        old = snap({"win_scheduled_tasks": ok("win_scheduled_tasks", old_tasks)}, T0)
        d = baseline.diff(old, snap())
        text = report.render(snap(), [], {"diff": d, "label": "base"})
        self.assertIn("Removed since last scan", text)
        self.assertIn("scheduled_tasks: `\\gone'/&lt;b>`", text)

    def test_scan_compares_with_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            snapshot.save_snapshot(snap(now=T0), Path(d) / "snapshots")
            key = {"Key": "HKCU:\\Run", "Name": "Late", "Value": "powershell -w hidden -enc SQBFAFgAIAAoAE4A"}
            newer = snapshot.save_snapshot(snap(with_added("win_run_keys", key)), Path(d) / "snapshots")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                scan.main(["--from-snapshot", str(newer), "--out", d])
            self.assertIn("1 change finding", out.getvalue())
            text = next((Path(d) / "reports").glob("*.md")).read_text()
            self.assertIn("## Changes since last scan", text)
            self.assertIn("New since last scan, starts automatically", text)

            with contextlib.redirect_stdout(io.StringIO()):
                scan.main(["--from-snapshot", str(newer), "--out", d, "--no-baseline"])
            self.assertIn("Not compared (`--no-baseline`)", next((Path(d) / "reports").glob("*.md")).read_text())

    def test_baseline_flags_conflict(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            scan.main(["--baseline", "x", "--no-baseline"])


if __name__ == "__main__":
    unittest.main()
