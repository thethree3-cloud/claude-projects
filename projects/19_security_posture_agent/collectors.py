"""Collectors: run allowlisted commands and turn their output into clean records.

Collectors only gather facts. They don't judge anything; that's checks.py
(Slice 2). Every collector takes a `run` callable so tests can pass recorded
output instead of touching a real machine.

Each section has the same shape:
    {"ok": bool, "error": str | None, "items": [dict, ...]}
A failed command fails only its own section, never the whole scan.
"""

import json

import runner


def _section(items=None, error=None):
    return {"ok": error is None, "error": error, "items": items or []}


def _load(run, name):
    """Run a command and parse its JSON array. Returns (items, error)."""
    result = run(name)
    if not result.ok:
        return None, result.error
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
    if proc_err:
        section["warning"] = f"process names missing: {proc_err}"
    return section


def collect_run_keys(run=runner.run):
    rows, err = _load(run, "win_run_keys")
    if err:
        return _section(error=err)
    return _section([
        {"key": r.get("Key"), "name": r.get("Name"), "command": r.get("Value")}
        for r in rows
    ])


def collect_startup_items(run=runner.run):
    rows, err = _load(run, "win_startup_folders")
    if err:
        return _section(error=err)
    return _section([
        {
            "folder": r.get("Folder"),
            "name": r.get("Name"),
            "path": r.get("FullName"),
            "size": r.get("Length"),
            "modified_utc": r.get("LastWriteUtc"),
        }
        for r in rows
    ])


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


# Order here is the order sections appear in the snapshot.
COLLECTORS = {
    "host": collect_host_info,
    "listening_ports": collect_listening_ports,
    "run_keys": collect_run_keys,
    "startup_items": collect_startup_items,
    "scheduled_tasks": collect_scheduled_tasks,
    "auto_services": collect_auto_services,
    "wmi_subscriptions": collect_wmi_subscriptions,
}
