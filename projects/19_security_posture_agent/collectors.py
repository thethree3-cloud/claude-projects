"""Collectors: run allowlisted commands and turn their output into clean records.

Collectors only gather facts. They don't judge anything; that's checks.py
(Slice 2). Every collector takes a `run` callable so tests can pass recorded
output instead of touching a real machine.

Each section has the same shape:
    {"ok": bool, "error": str | None, "items": [dict, ...]}
A failed command fails only its own section, never the whole scan.
"""

import json

import lnk
import runner


def _section(items=None, error=None):
    return {"ok": error is None, "error": error, "items": items or []}


NEEDS_ADMIN = "needs admin rights (run the scan from an Administrator terminal)"
_ACCESS_DENIED = ("access denied", "access is denied", "must be an administrator", "requires elevation")


def _friendly(error):
    """Turn Windows' access errors into one clear, consistent message."""
    if error and any(s in error.lower() for s in _ACCESS_DENIED):
        return NEEDS_ADMIN
    if error and "is not recognized" in error.lower():
        return "not available on this Windows edition"
    return error


def _load(run, name):
    """Run a command and parse its JSON array. Returns (items, error)."""
    result = run(name)
    if not result.ok:
        return None, _friendly(result.error)
    try:
        data = json.loads(result.stdout) if result.stdout else []
    except json.JSONDecodeError as e:
        return None, f"could not parse output of {name}: {e.msg}"
    if isinstance(data, dict):  # defensive: a single object instead of an array
        data = [data]
    if not isinstance(data, list):
        return None, f"unexpected output type from {name}: {type(data).__name__}"
    return [d for d in data if isinstance(d, dict)], None


def collect_host_info(run=runner.run):
    items, err = _load(run, "win_host_info")
    if err:
        return _section(error=err)
    if not items:
        return _section(error="no host info returned")
    h = items[0]
    return _section([{
        "hostname": h.get("Hostname"),
        "user": h.get("User"),
        "is_admin": bool(h.get("IsAdmin")),
        "os_caption": h.get("OsCaption"),
        "os_version": h.get("OsVersion"),
        "os_build": h.get("OsBuild"),
    }])


def collect_listening_ports(run=runner.run):
    """TCP listeners + UDP endpoints, each joined to its owning process."""
    procs, proc_err = _load(run, "win_processes")
    by_pid = {p.get("Id"): p for p in procs or []}

    items, errors = [], []
    for proto, name in (("tcp", "win_listen_tcp"), ("udp", "win_listen_udp")):
        rows, err = _load(run, name)
        if err:
            errors.append(f"{proto}: {err}")
            continue
        for r in rows:
            pid = r.get("OwningProcess")
            proc = by_pid.get(pid, {})
            items.append({
                "proto": proto,
                "address": r.get("LocalAddress"),
                "port": r.get("LocalPort"),
                "pid": pid,
                "process": proc.get("ProcessName"),
                "process_path": proc.get("Path"),
            })

    items.sort(key=lambda i: (i["proto"], i["port"] or 0, str(i["address"])))
    # Partial data is still useful: whatever ports were read are kept.
    # A process-list failure only loses names, so it's a warning, not an error.
    section = _section(items, "; ".join(errors) or None)
    hidden = sum(1 for i in items if i["process_path"] is None)
    if proc_err:
        section["warning"] = f"process names missing: {proc_err}"
    elif items and hidden > len(items) // 2:
        # Without admin, Windows hides the program path of most system processes,
        # so the rules can't judge where most listeners run from.
        section["warning"] = f"program path hidden for {hidden} of {len(items)} ports (usually needs admin)"
    return section


def collect_run_keys(run=runner.run):
    rows, err = _load(run, "win_run_keys")
    if err:
        return _section(error=err)
    return _section([
        {"key": r.get("Key"), "name": r.get("Name"), "command": r.get("Value")}
        for r in rows
    ])


def collect_startup_items(run=runner.run, read_file=lnk.read_windows_file):
    """Files in the Startup folders. Shortcuts get their target + arguments,
    because a shortcut is only as safe as what it launches."""
    rows, err = _load(run, "win_startup_folders")
    if err:
        return _section(error=err)
    items = []
    for r in rows:
        item = {
            "folder": r.get("Folder"),
            "name": r.get("Name"),
            "path": r.get("FullName"),
            "size": r.get("Length"),
            "modified_utc": r.get("LastWriteUtc"),
            "target": None,
            "arguments": None,
        }
        if (item["name"] or "").lower().endswith(".lnk"):
            data = read_file(item["path"])
            parsed = lnk.parse_lnk(data) if data else None
            if parsed:
                item["target"], item["arguments"] = parsed["target"], parsed["arguments"]
            else:
                item["shortcut_error"] = "couldn't read shortcut" if data is None else "not a valid shortcut"
        items.append(item)
    return _section(items)


def collect_scheduled_tasks(run=runner.run):
    rows, err = _load(run, "win_scheduled_tasks")
    if err:
        return _section(error=err)
    return _section([
        {
            "task": f"{r.get('TaskPath') or ''}{r.get('TaskName') or ''}",
            "state": r.get("State"),
            "author": r.get("Author"),
            "run_as": r.get("UserId"),
            "run_level": r.get("RunLevel"),
            "execute": r.get("Execute"),
            "arguments": r.get("Arguments"),
            "com_class_id": r.get("ClassId"),
        }
        for r in rows
    ])


def collect_auto_services(run=runner.run):
    rows, err = _load(run, "win_auto_services")
    if err:
        return _section(error=err)
    return _section([
        {
            "name": r.get("Name"),
            "display_name": r.get("DisplayName"),
            "command": r.get("PathName"),
            "state": r.get("State"),
            "run_as": r.get("StartName"),
        }
        for r in rows
    ])


def collect_wmi_subscriptions(run=runner.run):
    rows, err = _load(run, "win_wmi_subscriptions")
    if err:
        return _section(error=err)
    return _section([
        {
            "kind": r.get("Kind"),
            "class": r.get("Class"),
            "name": r.get("Name"),
            "command": r.get("CommandLine"),
            "script": r.get("ScriptText"),
            "query": r.get("Query"),
        }
        for r in rows
    ])


def _single(run, name):
    """For commands that return exactly one settings object."""
    rows, err = _load(run, name)
    if err:
        return None, err
    if not rows:
        return None, f"{name} returned nothing"
    return rows[0], None


def collect_defender(run=runner.run):
    d, err = _single(run, "win_defender")
    if err:
        return _section(error=err)

    def exclusions(key):
        values = [v for v in (d.get(key) or []) if isinstance(v, str)]
        if any(v.startswith("N/A") for v in values):
            return None  # not readable without admin; unknown, not "none"
        return values

    paths, procs, exts = (exclusions(k) for k in ("ExclusionPath", "ExclusionProcess", "ExclusionExtension"))
    return _section([{
        "running_mode": d.get("AMRunningMode"),
        "antivirus_enabled": d.get("AntivirusEnabled"),
        "realtime_enabled": d.get("RealTimeProtectionEnabled"),
        "tamper_protected": d.get("IsTamperProtected"),
        "signature_age_days": d.get("SignatureAgeDays"),
        "exclusions_readable": None not in (paths, procs, exts),
        "exclusion_paths": paths or [],
        "exclusion_processes": procs or [],
        "exclusion_extensions": exts or [],
    }])


def collect_firewall(run=runner.run):
    rows, err = _load(run, "win_firewall_profiles")
    if err:
        return _section(error=err)
    return _section([
        {"profile": r.get("Name"), "enabled": str(r.get("Enabled")).lower() == "true"}
        for r in rows
    ])


def collect_hotfixes(run=runner.run):
    rows, err = _load(run, "win_hotfixes")
    if err:
        return _section(error=err)
    return _section([
        {"id": r.get("HotFixID"), "description": r.get("Description"), "installed_on": r.get("InstalledOn")}
        for r in rows
    ])


def collect_local_admins(run=runner.run):
    rows, err = _load(run, "win_local_admins")
    if err:
        return _section(error=err)
    return _section([
        {"name": r.get("Name"), "type": r.get("ObjectClass"), "source": r.get("Source"), "sid": r.get("SID")}
        for r in rows
    ])


def collect_local_users(run=runner.run):
    rows, err = _load(run, "win_local_users")
    if err:
        return _section(error=err)
    return _section([
        {
            "name": r.get("Name"),
            "enabled": bool(r.get("Enabled")),
            "password_required": bool(r.get("PasswordRequired")),
            "sid": r.get("SID"),
        }
        for r in rows
    ])


def collect_bitlocker(run=runner.run):
    rows, err = _load(run, "win_bitlocker")
    if err:
        return _section(error=err)
    return _section([
        {
            "drive": r.get("MountPoint"),
            "type": r.get("VolumeType"),
            "protection": r.get("ProtectionStatus"),
            "encrypted_percent": r.get("EncryptionPercentage"),
        }
        for r in rows
    ])


def collect_rdp_settings(run=runner.run):
    d, err = _single(run, "win_rdp_settings")
    if err:
        return _section(error=err)
    return _section([{
        "enabled": d.get("DenyConnections") == 0,
        "nla_required": d.get("NlaRequired") == 1,
        "port": d.get("Port"),
    }])


# Order here is the order sections appear in the snapshot.
COLLECTORS = {
    "host": collect_host_info,
    "listening_ports": collect_listening_ports,
    "run_keys": collect_run_keys,
    "startup_items": collect_startup_items,
    "scheduled_tasks": collect_scheduled_tasks,
    "auto_services": collect_auto_services,
    "wmi_subscriptions": collect_wmi_subscriptions,
    "defender": collect_defender,
    "firewall": collect_firewall,
    "hotfixes": collect_hotfixes,
    "local_admins": collect_local_admins,
    "local_users": collect_local_users,
    "rdp_settings": collect_rdp_settings,
    "bitlocker": collect_bitlocker,
}
