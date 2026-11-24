"""Compare a snapshot against an earlier one: what's new, removed, or changed.

One scan can't tell a normal startup item from a planted one. Comparing scans
can: "this task didn't exist last week and runs from AppData" is a strong
signal. Severity for a new item comes from the same command traits as
checks.py, raised one level because it's new.

Limits, stated in the report too:
- The baseline is only as trustworthy as the machine was when it was taken.
  Anything already there then is not "new".
- UDP endpoints are left out: browsers open and close them constantly.
- TCP ports in the dynamic range (49152+) are compared by process, not number.
"""

import glob
from pathlib import Path

import checks
import snapshot as snapshot_mod

# section -> (identity key, fields that count as a "change")
_PERSISTENCE = {
    "run_keys": (lambda i: f"{i['key']}\\{i['name']}", ("command",)),
    "startup_items": (lambda i: i["path"], ("size", "modified_utc", "target", "arguments")),
    "auto_services": (lambda i: i["name"], ("command", "run_as")),
    "wmi_subscriptions": (lambda i: f"{i['kind']}:{i['name']}", ("command", "script", "query")),
}
_ACCOUNTS = {
    "local_admins": (lambda i: i["sid"] or i["name"], ()),
    "local_users": (lambda i: i["sid"] or i["name"], ("enabled", "password_required")),
}

_BUMP = {"low": "medium", "medium": "high", "high": "high"}


def _usable(section_name, *snaps):
    """Both snapshots have this section and it worked in both."""
    for s in snaps:
        sec = s["sections"].get(section_name)
        if not sec or not sec["ok"]:
            return False
    return True


def _items(snap, name):
    return snap["sections"][name]["items"]


def _task_groups(snap):
    """Scheduled tasks can have several actions; compare all actions as one."""
    groups = {}
    for t in _items(snap, "scheduled_tasks"):
        groups.setdefault(t["task"], {"task": t["task"], "state": t["state"], "actions": []})
        groups[t["task"]]["actions"].append(
            " ".join(x for x in (t["execute"], t["arguments"]) if x) or (t["com_class_id"] or ""))
    for g in groups.values():
        g["actions"] = sorted(g["actions"])
    return groups


def _port_key(p):
    scope = "all" if p["address"] in ("0.0.0.0", "::") else p["address"]
    port = p["port"] if (p["port"] or 0) < 49152 else "dynamic"
    return f"tcp/{port} {scope} {p.get('process') or '?'}"


def _ports(snap):
    out = {}
    for p in _items(snap, "listening_ports"):
        if p["proto"] == "tcp" and not checks._is_loopback(p["address"]):
            out.setdefault(_port_key(p), p)
    return out


def _diff_keyed(old, new, change_fields):
    added = [new[k] for k in sorted(new.keys() - old.keys())]
    removed = [old[k] for k in sorted(old.keys() - new.keys())]
    changed = []
    for k in sorted(old.keys() & new.keys()):
        fields = [f for f in change_fields if old[k].get(f) != new[k].get(f)]
        if fields:
            changed.append({"key": k, "fields": fields, "before": old[k], "after": new[k]})
    return {"added": added, "removed": removed, "changed": changed}


def diff(old, new):
    """Section -> {added, removed, changed}. Sections missing or failed in
    either snapshot are listed under 'skipped' instead of being guessed at."""
    result, skipped = {}, []
    for name, (key, fields) in {**_PERSISTENCE, **_ACCOUNTS}.items():
        if not _usable(name, old, new):
            skipped.append(name)
            continue
        o = {key(i): i for i in _items(old, name)}
        n = {key(i): i for i in _items(new, name)}
        result[name] = _diff_keyed(o, n, fields)

    if _usable("scheduled_tasks", old, new):
        result["scheduled_tasks"] = _diff_keyed(_task_groups(old), _task_groups(new), ("actions",))
    else:
        skipped.append("scheduled_tasks")

    if _usable("listening_ports", old, new):
        d = _diff_keyed(_ports(old), _ports(new), ())
        result["listening_ports"] = d
    else:
        skipped.append("listening_ports")

    settings = {}
    for name in ("defender", "firewall", "rdp_settings"):
        if not _usable(name, old, new):
            skipped.append(name)
            continue
        settings[name] = (_items(old, name), _items(new, name))
    return {"sections": result, "settings": settings, "skipped": sorted(skipped)}


# --- Findings from a diff ------------------------------------------------------------

def _command_of(section, item):
    if section == "scheduled_tasks":
        return " ".join(item["actions"])
    if section == "startup_items":
        return " ".join(x for x in (item.get("name"), item.get("target"), item.get("arguments")) if x)
    return item.get("command") or item.get("script") or ""


def _new_item_severity(section, command):
    traits = checks.command_traits(command)
    base = checks.severity_for(traits)
    if base:
        return _BUMP[base], traits
    if not command or command.startswith("{"):  # nothing to run, or a COM handler only
        return "info", traits
    if checks.in_protected_dir(checks.executable_of(command)):
        return "info", traits  # installers add these constantly; still listed
    return "low", traits


def _subject(section, item):
    if section == "run_keys":
        return f"{item['key']}\\{item['name']}"
    if section == "scheduled_tasks":
        return item["task"]
    if section == "startup_items":
        return item["name"]
    return item.get("name") or "?"


def findings_from_diff(d, baseline_label):
    out = []
    evidence_base = {"compared_with": baseline_label}

    for section in ("run_keys", "startup_items", "scheduled_tasks", "auto_services", "wmi_subscriptions"):
        sd = d["sections"].get(section)
        if not sd:
            continue
        for item in sd["added"]:
            if section == "startup_items" and item["name"].lower() == "desktop.ini":
                continue
            if section == "wmi_subscriptions" and item["kind"] != "consumer":
                continue
            if section == "scheduled_tasks" and item["state"] == "Disabled":
                continue
            sev, traits = _new_item_severity(section, _command_of(section, item))
            out.append(checks._finding("NEW-PERSISTENCE", section, _subject(section, item),
                                       {**evidence_base, **item}, sev, traits))
        for ch in sd["changed"]:
            after = ch["after"]
            # A changed command is worth seeing even when harmless-looking (e.g.
            # Defender's own service path moves with each platform update), so
            # "info" becomes "low"; anything with traits is raised as for new items.
            sev, traits = _new_item_severity(section, _command_of(section, after))
            sev = "low" if sev == "info" else sev
            out.append(checks._finding(
                "CHANGED-PERSISTENCE", section, _subject(section, after),
                {**evidence_base, "changed_fields": ch["fields"],
                 "before": _command_of(section, ch["before"]), "after": _command_of(section, after)},
                sev, traits))

    admins = d["sections"].get("local_admins")
    for a in (admins or {}).get("added", []):
        out.append(checks._finding("NEW-ADMIN", "local_admins", a["name"], {**evidence_base, **a}, "high"))

    users = d["sections"].get("local_users")
    for u in (users or {}).get("added", []):
        out.append(checks._finding("NEW-USER", "local_users", u["name"], {**evidence_base, **u},
                                   "medium" if u["enabled"] else "low"))
    for ch in (users or {}).get("changed", []):
        if "enabled" in ch["fields"] and ch["after"]["enabled"]:
            out.append(checks._finding("ACCOUNT-REENABLED", "local_users", ch["after"]["name"],
                                       {**evidence_base, **ch["after"]}, "medium"))

    ports = d["sections"].get("listening_ports")
    for p in (ports or {}).get("added", []):
        sev = "medium" if p["port"] in checks.REMOTE_SERVICE_PORTS or p["port"] in checks.ATTACK_TOOL_PORTS \
            or "user_writable_path" in checks.command_traits(p.get("process_path")) else "low"
        out.append(checks._finding("NEW-LISTENER", "listening_ports", _port_key(p),
                                   {**evidence_base, **p}, sev))

    out.extend(_weakened_settings(d["settings"], evidence_base))
    return out


def _first(items):
    return items[0] if items else {}


def _weakened_settings(settings, evidence_base):
    out = []

    def weakened(what, before, after, sev="high"):
        out.append(checks._finding("SETTING-WEAKENED", "settings", what,
                                   {**evidence_base, "before": before, "after": after}, sev))

    if "defender" in settings:
        old, new = (_first(x) for x in settings["defender"])
        for field, label in (("realtime_enabled", "Defender real-time protection"),
                             ("tamper_protected", "Defender tamper protection")):
            if old.get(field) is True and new.get(field) is False:
                weakened(label, "on", "off")
        if old.get("exclusions_readable") and new.get("exclusions_readable"):
            for kind in ("exclusion_paths", "exclusion_processes", "exclusion_extensions"):
                for v in sorted(set(new.get(kind, [])) - set(old.get(kind, []))):
                    weakened(f"new Defender exclusion ({kind.split('_')[1][:-1]}) {v}", "absent", v)

    if "firewall" in settings:
        old = {f["profile"]: f["enabled"] for f in settings["firewall"][0]}
        for f in settings["firewall"][1]:
            if old.get(f["profile"]) is True and not f["enabled"]:
                weakened(f"Firewall {f['profile']} profile", "on", "off")

    if "rdp_settings" in settings:
        old, new = (_first(x) for x in settings["rdp_settings"])
        if old.get("enabled") is False and new.get("enabled") is True:
            weakened("Remote Desktop", "off", "on", "medium")
        if old.get("nla_required") is True and new.get("nla_required") is False:
            weakened("Remote Desktop Network Level Authentication", "required", "not required")
    return out


# --- Picking a baseline --------------------------------------------------------------

def previous_snapshot_path(directory, current_path):
    """The newest snapshot taken before `current_path`, or None.

    Filenames are UTC timestamps, so name order is time order. Re-checking an
    old snapshot compares it with the one before it, not the newest scan.
    """
    current = Path(current_path).name
    older = [p for p in sorted(glob.glob(str(Path(directory) / "snapshot_*.json")))
             if Path(p).name < current]
    return older[-1] if older else None


def compare(new_snapshot, baseline_path):
    """Load the baseline and return (diff, findings, label)."""
    old = snapshot_mod.load_snapshot(baseline_path)
    label = f"{Path(baseline_path).name} ({old['collected_at']})"
    d = diff(old, new_snapshot)
    return d, findings_from_diff(d, label), label
