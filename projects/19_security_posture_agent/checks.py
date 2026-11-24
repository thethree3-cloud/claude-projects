"""Deterministic checks: snapshot facts -> findings.

No LLM here. Every finding comes from a fixed rule, carries the raw item it was
based on as evidence, and uses fix text written ahead of time in CATALOG.
Later slices may explain and rank these findings, but they can't add new ones
or invent fixes.

Severity: high > medium > low > info.
"""

import hashlib
import re
from datetime import datetime

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}

# NIST SP 800-171 Rev. 2 requirement IDs. CIS Benchmark IDs are left out until
# they can be checked against the actual benchmark document.
CATALOG = {
    "PERSIST-SUSPICIOUS": {
        "title": "Startup entry looks suspicious: {subject}",
        "why": "This runs automatically when the computer starts or on a schedule, and its "
               "command has traits malware often uses (see 'traits').",
        "fix": "Check that you recognize the program. If not, disable the entry (Task Scheduler, "
               "Startup apps, or Services), then scan the file with Microsoft Defender "
               "(right-click the file > Scan with Microsoft Defender).",
        "refs": ["NIST 800-171 3.14.2", "NIST 800-171 3.14.7"],
    },
    "PERSIST-REVIEW": {
        "title": "Startup entry worth a quick look: {subject}",
        "why": "This starts automatically from a folder any program can write to. Many normal "
               "apps (Notion, Discord, Spotify, Teams) do this, so it's only a problem if you "
               "don't recognize it.",
        "fix": "If you recognize the app, nothing to do. If not, disable it in Settings > Apps > "
               "Startup (or Task Scheduler / Services) and scan the file with Microsoft Defender.",
        "refs": ["NIST 800-171 3.14.7"],
    },
    "PERSIST-MULTI": {
        "title": "Same program starts itself several ways: {subject}",
        "why": "A program from a user-writable folder set up to start through more than one "
               "mechanism (or also listening on the network) is a common backdoor pattern: "
               "remove one, and another brings it back.",
        "fix": "Find out what the program is before removing anything. If you don't recognize "
               "it, disconnect from the network, remove every entry listed in the evidence, "
               "and run a Microsoft Defender Offline scan.",
        "refs": ["NIST 800-171 3.14.2", "NIST 800-171 3.14.7"],
    },
    "WMI-CONSUMER": {
        "title": "WMI event subscription runs a command: {subject}",
        "why": "WMI subscriptions that run commands or scripts are rare on personal computers "
               "and are a well-known, hard-to-see way to keep malware running.",
        "fix": "If you didn't set this up, ask someone with admin rights to remove the "
               "subscription (consumer, filter and binding) and run a full Defender scan.",
        "refs": ["NIST 800-171 3.14.2"],
    },
    "WMI-CONSUMER-REVIEW": {
        "title": "WMI event subscription runs an installed program: {subject}",
        "why": "It runs a program from Program Files or Windows (only admins can put files there) "
               "with no suspicious traits. Some hardware software, such as dock firmware updaters, "
               "works this way.",
        "fix": "If the program matches hardware or software you have, nothing to do. If not, ask "
               "someone with admin rights to remove the subscription.",
        "refs": ["NIST 800-171 3.14.7"],
    },
    "SVC-UNQUOTED-PATH": {
        "title": "Service path has spaces but no quotes: {subject}",
        "why": "Windows may run a different program (e.g. C:\\Program.exe) placed earlier in the "
               "path. Someone who can write there could gain SYSTEM rights.",
        "fix": "With admin rights, put quotes around the program path in the service's ImagePath "
               "registry value, or update/reinstall the software.",
        "refs": ["NIST 800-171 3.4.2"],
    },
    "SVC-SYSTEM-USER-PATH": {
        "title": "Service runs with full system rights from a user folder: {subject}",
        "why": "This service starts automatically as SYSTEM, the most powerful account on Windows, "
               "but its program sits in a folder ordinary users and programs can write to. Anyone "
               "who replaces that file gets full control of the computer at the next restart.",
        "fix": "If you don't recognize the service, stop and disable it (Services > the service > "
               "Startup type: Disabled) and scan the program with Defender. If it's software you "
               "use, reinstall it into Program Files or ask the vendor.",
        "refs": ["NIST 800-171 3.1.7", "NIST 800-171 3.4.2"],
    },
    "REMOTE-ACCESS-TOOL": {
        "title": "Remote-access software found: {subject}",
        "why": "These tools let someone control the computer from elsewhere. That's fine if you "
               "or your IT team installed it; if not, it may be how someone is getting in.",
        "fix": "Confirm who installed it. If nobody did, uninstall it (Settings > Apps) and change "
               "your passwords from another device.",
        "refs": ["NIST 800-171 3.1.12", "NIST 800-171 3.4.7"],
    },
    "PORT-REMOTE-SERVICE": {
        "title": "Remote-login service is listening: {subject}",
        "why": "This port accepts remote logins from other computers on the network.",
        "fix": "Turn the service off if you don't use it. If you do, allow it only from trusted "
               "addresses in Windows Defender Firewall.",
        "refs": ["NIST 800-171 3.1.12", "NIST 800-171 3.4.7"],
    },
    "PORT-ATTACK-TOOL": {
        "title": "Port often used by attack tools is open: {subject}",
        "why": "This port number is a common default for hacking tools and backdoors. Legitimate "
               "programs use it occasionally, so check the owning process.",
        "fix": "Look up the owning process in the evidence. If you don't recognize it, end it, "
               "find how it starts, and run a full Defender scan.",
        "refs": ["NIST 800-171 3.4.7", "NIST 800-171 3.14.7"],
    },
    "PORT-USER-PATH-LISTENER": {
        "title": "Program from a user folder accepts network connections: {subject}",
        "why": "Installed software normally lives in Program Files. A program in a user-writable "
               "folder listening on the network deserves a look.",
        "fix": "Check that you recognize the program. Some apps (chat, music, games) do this "
               "normally; if you don't know it, end it and scan it with Defender.",
        "refs": ["NIST 800-171 3.4.7"],
    },
    "DEF-REALTIME-OFF": {
        "title": "Microsoft Defender real-time protection is off",
        "why": "Without real-time protection, malware isn't blocked when it arrives.",
        "fix": "Windows Security > Virus & threat protection > Manage settings > turn on "
               "Real-time protection.",
        "refs": ["NIST 800-171 3.14.2"],
    },
    "DEF-PASSIVE": {
        "title": "Defender is in passive mode (another antivirus is in charge)",
        "why": "This is normal when another antivirus product is installed. Make sure that "
               "product is active and up to date.",
        "fix": "Open your other antivirus and confirm it's running and updated.",
        "refs": ["NIST 800-171 3.14.2"],
    },
    "DEF-TAMPER-OFF": {
        "title": "Defender tamper protection is off",
        "why": "Malware commonly tries to switch Defender off. Tamper protection blocks that.",
        "fix": "Windows Security > Virus & threat protection > Manage settings > turn on "
               "Tamper Protection.",
        "refs": ["NIST 800-171 3.14.2"],
    },
    "DEF-SIGNATURES-OLD": {
        "title": "Defender virus definitions are {subject} days old",
        "why": "Old definitions miss recent malware.",
        "fix": "Windows Security > Virus & threat protection > Protection updates > Check for "
               "updates.",
        "refs": ["NIST 800-171 3.14.4"],
    },
    "DEF-EXCLUSION": {
        "title": "Defender skips scanning: {subject}",
        "why": "Anything in an exclusion is never scanned. Broad exclusions (a whole drive, a user "
               "folder, a script type) are a favorite hiding place for malware.",
        "fix": "Windows Security > Virus & threat protection > Manage settings > Exclusions. "
               "Remove anything you didn't add on purpose.",
        "refs": ["NIST 800-171 3.14.2"],
    },
    "DEF-EXCLUSIONS-UNREADABLE": {
        "title": "Couldn't read Defender exclusions without admin rights",
        "why": "Exclusions are a common hiding place, but Windows only shows them to admins.",
        "fix": "Run the scan from an admin terminal to include this check.",
        "refs": [],
    },
    "FW-PROFILE-OFF": {
        "title": "Windows Firewall is off for the {subject} profile",
        "why": "With the firewall off, every listening program is reachable from the network.",
        "fix": "Windows Security > Firewall & network protection > select the profile > turn "
               "Microsoft Defender Firewall on.",
        "refs": ["NIST 800-171 3.13.1", "NIST 800-171 3.13.6"],
    },
    "PATCH-STALE": {
        "title": "Newest Windows update is {subject} days old",
        "why": "Windows security fixes come out every month. Missing them leaves known holes open.",
        "fix": "Settings > Windows Update > Check for updates, install, and restart.",
        "refs": ["NIST 800-171 3.14.1"],
    },
    "PATCH-UNKNOWN": {
        "title": "Couldn't tell when Windows was last updated",
        "why": "No installed update had a date.",
        "fix": "Check Settings > Windows Update > Update history.",
        "refs": ["NIST 800-171 3.14.1"],
    },
    "ACCT-GUEST-ENABLED": {
        "title": "The Guest account is turned on",
        "why": "Guest lets anyone sign in without a password of their own.",
        "fix": "From an admin terminal: net user Guest /active:no",
        "refs": ["NIST 800-171 3.1.1"],
    },
    "ACCT-BUILTIN-ADMIN-ENABLED": {
        "title": "The built-in Administrator account is turned on",
        "why": "Attackers know this account exists and target it with password guessing.",
        "fix": "From an admin terminal: net user Administrator /active:no",
        "refs": ["NIST 800-171 3.1.5"],
    },
    "ACCT-PASSWORD-NOT-REQUIRED": {
        "title": "Account is allowed to have a blank password: {subject}",
        "why": "Windows has the 'password not required' flag set, so this account could have no "
               "password. Windows sets this flag on many normal accounts, so it doesn't mean "
               "the password is actually blank.",
        "fix": "Make sure the account has a strong password. To remove the flag, from an admin "
               "terminal: net user \"{subject}\" /passwordreq:yes",
        "refs": ["NIST 800-171 3.5.2"],
    },
    "ACCT-EXTRA-ADMIN": {
        "title": "Check you know this admin account: {subject}",
        "why": "Every admin account can change anything on the computer. A separate admin account "
               "is good practice (see 'Your everyday account is an administrator'), but an admin "
               "account you don't recognize is a common sign of a break-in. Admins added since the "
               "last scan are reported separately, at high.",
        "fix": "If you know the account, nothing to do. If you don't, remove it from the "
               "Administrators group (Computer Management > Local Users and Groups).",
        "refs": ["NIST 800-171 3.1.5"],
    },
    "ACCT-DAILY-ADMIN": {
        "title": "Your everyday account is an administrator",
        "why": "Anything you run, including malware you open by mistake, can get full admin "
               "rights (after a UAC prompt).",
        "fix": "Optional but recommended: create a separate admin account and make your daily "
               "account a standard user.",
        "refs": ["NIST 800-171 3.1.6"],
    },
    "RDP-ENABLED": {
        "title": "Remote Desktop is turned on",
        "why": "Remote Desktop is one of the most attacked services on Windows.",
        "fix": "If you don't use it: Settings > System > Remote Desktop > Off.",
        "refs": ["NIST 800-171 3.1.12"],
    },
    "RDP-NLA-OFF": {
        "title": "Remote Desktop doesn't require Network Level Authentication",
        "why": "Without NLA, attackers reach the Windows login screen before proving who they "
               "are, which exposes more of the system.",
        "fix": "Settings > System > Remote Desktop > Advanced settings > require devices to use "
               "Network Level Authentication.",
        "refs": ["NIST 800-171 3.1.12", "NIST 800-171 3.4.2"],
    },
    # --- Changes since the baseline scan (baseline.py) ---
    "NEW-PERSISTENCE": {
        "title": "New since last scan, starts automatically: {subject}",
        "why": "This auto-start entry wasn't there at the last scan. Software installs add these "
               "all the time, but so does malware, so new entries are worth checking. Severity "
               "is raised one level above what its command alone would get.",
        "fix": "Did you install or update something since the last scan that matches this? If "
               "yes, nothing to do. If not, disable the entry and scan the program with Defender.",
        "refs": ["NIST 800-171 3.14.7", "NIST 800-171 3.4.3"],
    },
    "CHANGED-PERSISTENCE": {
        "title": "Changed since last scan: {subject}",
        "why": "An existing auto-start entry now runs something different. Updates do this, but "
               "pointing a trusted-looking entry at a new program is also a known hijack trick.",
        "fix": "Compare 'before' and 'after' in the evidence. A version-number change in the same "
               "folder is normal; a new folder or program is not.",
        "refs": ["NIST 800-171 3.14.7", "NIST 800-171 3.4.3"],
    },
    "NEW-ADMIN": {
        "title": "New administrator since last scan: {subject}",
        "why": "An account gained full control of this computer since the last scan. Attackers "
               "often add themselves as admin to stay in.",
        "fix": "If you didn't add it, remove it from the Administrators group right away and "
               "change your passwords from another device.",
        "refs": ["NIST 800-171 3.1.5", "NIST 800-171 3.14.7"],
    },
    "NEW-USER": {
        "title": "New local account since last scan: {subject}",
        "why": "A new account can be a way back in for whoever created it.",
        "fix": "If you don't know why it exists, disable it: net user \"{subject}\" /active:no",
        "refs": ["NIST 800-171 3.1.1", "NIST 800-171 3.14.7"],
    },
    "ACCOUNT-REENABLED": {
        "title": "Account was turned back on since last scan: {subject}",
        "why": "Disabled accounts that come back to life are a classic sign someone wants a "
               "quiet way in.",
        "fix": "If you didn't do this, disable it again: net user \"{subject}\" /active:no",
        "refs": ["NIST 800-171 3.1.1", "NIST 800-171 3.14.7"],
    },
    "NEW-LISTENER": {
        "title": "New program accepting network connections: {subject}",
        "why": "Something started accepting connections from other computers since the last scan.",
        "fix": "Check that you recognize the process. If not, end it and find how it starts.",
        "refs": ["NIST 800-171 3.4.7", "NIST 800-171 3.14.7"],
    },
    "SETTING-WEAKENED": {
        "title": "Security setting weakened since last scan: {subject}",
        "why": "A protection was switched off or loosened since the last scan. Malware often "
               "does this first.",
        "fix": "Turn the setting back on (see the matching finding for steps) and run a full "
               "Defender scan. If you didn't change it, treat the computer as possibly compromised.",
        "refs": ["NIST 800-171 3.4.3", "NIST 800-171 3.14.2"],
    },
    "SCAN-NOT-ADMIN": {
        "title": "Scan ran without admin rights",
        "why": "Some items (Defender exclusions, some tasks and services) are only visible to admins.",
        "fix": "For a complete scan, run it from an admin terminal.",
        "refs": [],
    },
}

# --- Command traits -----------------------------------------------------------

_USER_PATH = re.compile(
    r"\\(appdata|temp|downloads)\\|\\users\\public\\|%(appdata|localappdata|temp|tmp|userprofile)%",
    re.I,
)
_PROGRAMDATA = re.compile(r"\\programdata\\|%programdata%", re.I)
_PROGRAMDATA_MICROSOFT = re.compile(r"\\programdata\\microsoft\\", re.I)
_POWERSHELL = re.compile(r"\b(powershell|pwsh)(\.exe)?\b", re.I)
_ENCODED = re.compile(r"\s-(e|ec|en\w*)\s+[A-Za-z0-9+/=]{8,}", re.I)
_HIDDEN = re.compile(r"\s-w\w*\s+h(idden)?\b", re.I)
_SCRIPT_HOST = re.compile(r"\b(wscript|cscript|mshta)(\.exe)?\b|\.(vbs|vbe|jse?|hta|wsf)\b", re.I)
_DOWNLOAD = re.compile(
    r"https?://|\b(curl|wget|invoke-webrequest|iwr|downloadstring|downloadfile|bitsadmin)\b"
    r"|\bcertutil\b.*-urlcache",
    re.I,
)
_PIPE_SHELL = re.compile(r"\|\s*(cmd|sh|bash|iex|powershell|pwsh|invoke-expression)\b", re.I)
_LOLBIN = re.compile(r"\b(rundll32|regsvr32)(\.exe)?\b", re.I)

TRAIT_WEIGHTS = {
    "user_writable_path": 1,
    "programdata_path": 1,
    "recently_modified": 1,
    "script_host": 2,
    "hidden_window": 2,
    "rundll32_or_regsvr32": 1,
    "downloads_from_internet": 3,
    "pipes_into_shell": 3,
    "encoded_powershell": 3,
}


def command_traits(command):
    """Suspicious traits of a command line. Empty list = nothing notable."""
    if not command:
        return []
    c = f" {command} "
    traits = []
    if _USER_PATH.search(c):
        traits.append("user_writable_path")
    if _PROGRAMDATA.search(c) and not _PROGRAMDATA_MICROSOFT.search(c):
        traits.append("programdata_path")
    if _POWERSHELL.search(c) and _ENCODED.search(c):
        traits.append("encoded_powershell")
    if _HIDDEN.search(c):
        traits.append("hidden_window")
    if _SCRIPT_HOST.search(c):
        traits.append("script_host")
    if _DOWNLOAD.search(c):
        traits.append("downloads_from_internet")
    if _PIPE_SHELL.search(c):
        traits.append("pipes_into_shell")
    if _LOLBIN.search(c):
        traits.append("rundll32_or_regsvr32")
    # rundll32/regsvr32 alone is everywhere in normal Windows tasks.
    if traits == ["rundll32_or_regsvr32"]:
        return []
    return traits


def severity_for(traits):
    score = sum(TRAIT_WEIGHTS.get(t, 0) for t in traits)
    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    if score >= 1:
        return "low"
    return None


def executable_of(command):
    """Best-effort program path from a command line, lowercased for comparing."""
    s = (command or "").strip()
    if not s:
        return ""
    if s.startswith('"'):
        end = s.find('"', 1)
        exe = s[1:end] if end > 0 else s[1:]
    else:
        m = re.match(r"(.+?\.(exe|com|bat|cmd|vbs|js|ps1|hta|scr))\b", s, re.I)
        exe = m.group(1) if m else s.split()[0]
    return exe.lower()


# --- Finding helper -------------------------------------------------------------

def _finding(check, section, subject, evidence, severity=None, traits=None):
    entry = CATALOG[check]
    key = f"{check}|{section}|{subject}"
    return {
        "id": f"{check}:{hashlib.sha1(key.encode('utf-8')).hexdigest()[:8]}",
        "check": check,
        "severity": severity,
        "title": entry["title"].format(subject=subject),
        "section": section,
        "subject": str(subject),
        "evidence": evidence,
        "traits": traits or [],
        "why": entry["why"],
        "fix": entry["fix"].format(subject=subject),
        "refs": list(entry["refs"]),
    }


def _items(snapshot, section):
    sec = snapshot["sections"].get(section)
    return sec["items"] if sec and sec["ok"] else []


def _is_loopback(address):
    a = str(address or "")
    return a.startswith("127.") or a == "::1"


# --- Persistence ------------------------------------------------------------------

def _persistence_entries(snapshot):
    """(section, subject, command, evidence) for every auto-start mechanism."""
    for r in _items(snapshot, "run_keys"):
        yield "run_keys", f"{r['key']}\\{r['name']}", r["command"], r
    for t in _items(snapshot, "scheduled_tasks"):
        cmd = " ".join(x for x in (t["execute"], t["arguments"]) if x)
        yield "scheduled_tasks", t["task"], cmd, t
    for s in _items(snapshot, "auto_services"):
        yield "auto_services", s["name"], s["command"], s
    for w in _items(snapshot, "wmi_subscriptions"):
        if w["kind"] == "consumer" and (w["command"] or w["script"]):
            yield "wmi_subscriptions", w["name"], w["command"] or w["script"], w


def check_persistence(snapshot):
    out = []
    in_backdoor = set(_multi_mechanism_programs(snapshot))
    for section, subject, command, evidence in _persistence_entries(snapshot):
        traits = command_traits(command)
        if section == "scheduled_tasks" and evidence.get("state") == "Disabled":
            continue  # can't run; baseline diff (Slice 3) still sees it
        sev = severity_for(traits)
        if sev == "low" and section == "auto_services" and runs_as_system(evidence) \
                and "user_writable_path" in traits:
            continue  # reported at medium by SVC-SYSTEM-USER-PATH instead
        if sev == "low" and executable_of(command) in in_backdoor:
            # Already listed in a high PERSIST-MULTI finding, whose fix covers every entry.
            # A separate low "many normal apps do this" note would contradict it.
            # (Found by Claude's rejected severity notes in Slices 4 and 5.)
            continue
        if sev:
            out.append(_persist_finding(section, subject, evidence, sev, traits))

    collected = _collected_at(snapshot)
    for item in _items(snapshot, "startup_items"):
        if item["name"].lower() == "desktop.ini":
            continue
        # The Startup folder itself lives under AppData, so judge the file name and
        # (for shortcuts) what it launches, never the folder it sits in.
        launched = " ".join(x for x in (item.get("target"), item.get("arguments")) if x)
        traits = list(dict.fromkeys(command_traits(f"{item['name']} {launched}")))
        if item["name"].lower().endswith((".bat", ".cmd", ".ps1", ".exe", ".scr")):
            traits.append("script_host")
        age = _days_since(item.get("modified_utc"), collected)
        if age is not None and age <= 14:
            traits.append("recently_modified")
        sev = severity_for(traits)
        if sev:
            out.append(_persist_finding("startup_items", item["name"], item, sev, traits))
    return out


def _persist_finding(section, subject, evidence, sev, traits):
    """Low = 'worth a look' wording; medium/high = 'looks suspicious'."""
    check = "PERSIST-REVIEW" if sev == "low" else "PERSIST-SUSPICIOUS"
    return _finding(check, section, subject, evidence, sev, traits)


def check_multi_mechanism(snapshot):
    """Same user-writable program wired up through 2+ mechanisms (or also listening)."""
    return [_finding("PERSIST-MULTI", "persistence", exe, {"program": exe, "found_in": uses}, "high")
            for exe, uses in _multi_mechanism_programs(snapshot).items()]


def _multi_mechanism_programs(snapshot):
    """program -> where it's found, for user-writable programs in 2+ places."""
    seen = {}
    for section, subject, command, _ in _persistence_entries(snapshot):
        exe = executable_of(command)
        traits = command_traits(exe)
        if "user_writable_path" in traits or "programdata_path" in traits:
            seen.setdefault(exe, []).append({"section": section, "entry": subject})
    for p in _items(snapshot, "listening_ports"):
        exe = (p.get("process_path") or "").lower()
        if exe in seen:
            seen[exe].append({"section": "listening_ports", "entry": f"{p['proto']}/{p['port']}"})

    return {exe: uses for exe, uses in seen.items() if len({u["section"] for u in uses}) >= 2}


_PROTECTED_DIR = re.compile(
    r"^(c:\\program files( \(x86\))?\\|c:\\windows\\|%programfiles(\(x86\))?%\\|%(windir|systemroot)%\\)",
    re.I,
)


def in_protected_dir(exe):
    """Program Files / Windows: only admins can write there."""
    return bool(_PROTECTED_DIR.match(exe or ""))


def check_wmi(snapshot):
    """Command-running WMI consumers.

    Judged by what they run, never by their name (anyone can call one "HP ...").
    Script consumers, suspicious commands, or programs outside Program Files /
    Windows are high. A plain program in a protected folder is low (some
    hardware vendors, e.g. dock firmware updaters, use this legitimately).
    """
    out = []
    for w in _items(snapshot, "wmi_subscriptions"):
        if w["kind"] != "consumer":
            continue
        if w["class"] == "ActiveScriptEventConsumer":
            out.append(_finding("WMI-CONSUMER", "wmi_subscriptions", w["name"], w, "high", ["inline_script"]))
        elif w["class"] == "CommandLineEventConsumer":
            traits = command_traits(w["command"])
            if not in_protected_dir(executable_of(w["command"])):
                traits.append("outside_program_files")
            if traits:
                out.append(_finding("WMI-CONSUMER", "wmi_subscriptions", w["name"], w, "high", traits))
            else:
                out.append(_finding("WMI-CONSUMER-REVIEW", "wmi_subscriptions", w["name"], w, "low"))
    return out


_SYSTEM_ACCOUNTS = {"localsystem", "nt authority\\system", ".\\localsystem"}


def runs_as_system(service):
    return (service.get("run_as") or "").strip().lower() in _SYSTEM_ACCOUNTS


def check_system_service_user_path(snapshot):
    """SYSTEM service whose program is in a user-writable folder (AppData, Temp, Downloads,
    Users\\Public). Added after the Slice 5 eval, where Claude correctly argued such a
    service deserved more than a low 'worth a look'. ProgramData is left out: many
    legitimate services install there, and its folders aren't user-writable by default."""
    out = []
    for s in _items(snapshot, "auto_services"):
        exe = executable_of(s["command"])
        if runs_as_system(s) and "user_writable_path" in command_traits(exe):
            out.append(_finding("SVC-SYSTEM-USER-PATH", "auto_services", s["name"], s, "medium",
                                ["user_writable_path", "runs_as_system"]))
    return out


def check_unquoted_service_paths(snapshot):
    out = []
    for s in _items(snapshot, "auto_services"):
        cmd = (s["command"] or "").strip()
        if not cmd or cmd.startswith('"'):
            continue
        idx = cmd.lower().find(".exe")
        if idx > 0 and " " in cmd[:idx]:
            out.append(_finding("SVC-UNQUOTED-PATH", "auto_services", s["name"], s, "medium"))
    return out


REMOTE_ACCESS_TOOLS = {
    "anydesk": "AnyDesk", "teamviewer": "TeamViewer", "screenconnect": "ScreenConnect",
    "connectwisecontrol": "ScreenConnect", "splashtop": "Splashtop", "rustdesk": "RustDesk",
    "tvnserver": "TightVNC", "tightvnc": "TightVNC", "winvnc": "VNC", "uvnc": "UltraVNC",
    "vncserver": "VNC", "logmein": "LogMeIn", "gotoassist": "GoTo Assist", "atera": "Atera",
    "ninjarmm": "NinjaOne", "kaseya": "Kaseya", "meshagent": "MeshCentral",
    "remoting_host": "Chrome Remote Desktop", "parsec": "Parsec", "dwagent": "DWService",
}


def check_remote_access_tools(snapshot):
    hits = {}

    def scan(text, where):
        low = (text or "").lower()
        for needle, tool in REMOTE_ACCESS_TOOLS.items():
            if re.search(rf"(?<![a-z]){needle}", low):
                hits.setdefault(tool, []).append(where)

    for s in _items(snapshot, "auto_services"):
        scan(f"{s['name']} {s['display_name']} {s['command']}", f"service: {s['name']}")
    for r in _items(snapshot, "run_keys"):
        scan(f"{r['name']} {r['command']}", f"run key: {r['name']}")
    for t in _items(snapshot, "scheduled_tasks"):
        scan(f"{t['task']} {t['execute']}", f"task: {t['task']}")
    for p in _items(snapshot, "listening_ports"):
        scan(f"{p['process']} {p['process_path']}", f"listening: {p['proto']}/{p['port']}")

    return [
        _finding("REMOTE-ACCESS-TOOL", "software", tool, {"found_in": sorted(set(w))}, "medium")
        for tool, w in sorted(hits.items())
    ]


# --- Network ------------------------------------------------------------------------

REMOTE_SERVICE_PORTS = {
    21: ("FTP", "medium"), 22: ("SSH", "medium"), 23: ("Telnet", "high"),
    3389: ("Remote Desktop", "medium"), 5900: ("VNC", "high"), 5901: ("VNC", "high"),
    5938: ("TeamViewer", "medium"), 5985: ("WinRM", "medium"), 5986: ("WinRM", "medium"),
}
ATTACK_TOOL_PORTS = {4444, 1337, 31337, 6667, 12345, 54321}


def check_ports(snapshot):
    out = []
    flagged = set()
    for p in _items(snapshot, "listening_ports"):
        if p["proto"] != "tcp" or _is_loopback(p["address"]):
            continue
        port = p["port"]
        label = f"tcp/{port} ({p.get('process') or 'unknown process'})"
        if port in REMOTE_SERVICE_PORTS and port not in flagged:
            name, sev = REMOTE_SERVICE_PORTS[port]
            out.append(_finding("PORT-REMOTE-SERVICE", "listening_ports", f"{name}, {label}", p, sev))
            flagged.add(port)
        elif port in ATTACK_TOOL_PORTS and port not in flagged:
            out.append(_finding("PORT-ATTACK-TOOL", "listening_ports", label, p, "medium"))
            flagged.add(port)
        if "user_writable_path" in command_traits(p.get("process_path")) and port not in flagged:
            out.append(_finding("PORT-USER-PATH-LISTENER", "listening_ports", label, p, "medium"))
            flagged.add(port)
    return out


# --- Defenses -----------------------------------------------------------------------

_BROAD_EXCLUSION = re.compile(r"^[a-z]:\\?$", re.I)
_RISKY_EXTENSIONS = {".exe", ".dll", ".ps1", ".vbs", ".js", ".bat", ".cmd", ".hta", ".scr"}


def check_defender(snapshot):
    items = _items(snapshot, "defender")
    if not items:
        return []
    d = items[0]
    out = []
    if "passive" in str(d.get("running_mode") or "").lower():
        out.append(_finding("DEF-PASSIVE", "defender", "Defender", d, "info"))
    else:
        if d.get("realtime_enabled") is False:
            out.append(_finding("DEF-REALTIME-OFF", "defender", "Defender", d, "high"))
        if d.get("tamper_protected") is False:
            out.append(_finding("DEF-TAMPER-OFF", "defender", "Defender", d, "medium"))
        age = d.get("signature_age_days")
        if isinstance(age, int) and age > 7:
            out.append(_finding("DEF-SIGNATURES-OLD", "defender", age, d, "high" if age > 30 else "medium"))

    if not d.get("exclusions_readable"):
        out.append(_finding("DEF-EXCLUSIONS-UNREADABLE", "defender", "exclusions", {}, "info"))
    for kind, values in (("path", d["exclusion_paths"]), ("process", d["exclusion_processes"]),
                         ("extension", d["exclusion_extensions"])):
        for v in values:
            broad = (
                (kind == "path" and (_BROAD_EXCLUSION.match(v) or command_traits(v + "\\")))
                or (kind == "extension" and v.lower() in _RISKY_EXTENSIONS)
            )
            out.append(_finding("DEF-EXCLUSION", "defender", f"{kind} {v}",
                                {"type": kind, "value": v}, "high" if broad else "low"))
    return out


def check_firewall(snapshot):
    return [
        _finding("FW-PROFILE-OFF", "firewall", f["profile"], f, "high")
        for f in _items(snapshot, "firewall") if not f["enabled"]
    ]


def check_patching(snapshot):
    sec = snapshot["sections"].get("hotfixes")
    if not sec or not sec["ok"]:
        return []
    dates = sorted(h["installed_on"] for h in sec["items"] if h.get("installed_on"))
    if not dates:
        return [_finding("PATCH-UNKNOWN", "hotfixes", "updates", {"updates_listed": len(sec["items"])}, "info")]
    age = _days_since(dates[-1], _collected_at(snapshot))
    if age is None or age <= 35:
        return []
    return [_finding("PATCH-STALE", "hotfixes", age,
                     {"newest_update": dates[-1], "updates_listed": len(sec["items"])},
                     "high" if age > 60 else "medium")]


# --- Accounts -----------------------------------------------------------------------

def _rid(sid):
    return str(sid or "").rsplit("-", 1)[-1]


def check_accounts(snapshot):
    out = []
    users = _items(snapshot, "local_users")
    for u in users:
        if not u["enabled"]:
            continue
        if _rid(u["sid"]) == "501":
            out.append(_finding("ACCT-GUEST-ENABLED", "local_users", u["name"], u, "high"))
            continue
        if _rid(u["sid"]) == "500":
            out.append(_finding("ACCT-BUILTIN-ADMIN-ENABLED", "local_users", u["name"], u, "medium"))
        if not u["password_required"]:
            out.append(_finding("ACCT-PASSWORD-NOT-REQUIRED", "local_users", u["name"], u, "low"))

    host = _items(snapshot, "host")
    me = (host[0]["user"] or "").lower() if host else ""
    enabled = {u["sid"]: u["enabled"] for u in users}
    for a in _items(snapshot, "local_admins"):
        short = (a["name"] or "").rsplit("\\", 1)[-1].lower()
        if me and short == me:
            out.append(_finding("ACCT-DAILY-ADMIN", "local_admins", a["name"], a, "low"))
        elif _rid(a["sid"]) == "500" or a["type"] != "User":
            continue  # built-in admin is covered above; groups need admin-side review
        elif enabled.get(a["sid"], True):
            # Low, not medium: a separate admin account is what ACCT-DAILY-ADMIN recommends.
            # Found by the Slice 5 eval (it fired on every scenario's healthy base machine).
            out.append(_finding("ACCT-EXTRA-ADMIN", "local_admins", a["name"], a, "low"))
    return out


def check_rdp(snapshot):
    items = _items(snapshot, "rdp_settings")
    if not items or not items[0]["enabled"]:
        return []
    r = items[0]
    out = [_finding("RDP-ENABLED", "rdp_settings", "Remote Desktop", r, "medium")]
    if not r["nla_required"]:
        out.append(_finding("RDP-NLA-OFF", "rdp_settings", "Remote Desktop", r, "high"))
    return out


def check_scan_context(snapshot):
    host = _items(snapshot, "host")
    if host and not host[0]["is_admin"]:
        return [_finding("SCAN-NOT-ADMIN", "host", "scan", {"is_admin": False}, "info")]
    return []


# --- Dates --------------------------------------------------------------------------

def _collected_at(snapshot):
    return datetime.fromisoformat(snapshot["collected_at"])


def _days_since(value, now):
    """Whole days from an ISO date or datetime to `now`. Treats values as UTC.

    Only the 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS' part is used, because
    PowerShell writes 7-digit fractional seconds that Python won't parse.
    """
    if not value:
        return None
    text = value[:19] if "T" in value else value[:10]
    try:
        then = datetime.fromisoformat(text).replace(tzinfo=now.tzinfo)
    except ValueError:
        return None
    return (now - then).days


# --- Entry point --------------------------------------------------------------------

ALL_CHECKS = [
    check_persistence, check_multi_mechanism, check_wmi, check_system_service_user_path,
    check_unquoted_service_paths,
    check_remote_access_tools, check_ports, check_defender, check_firewall,
    check_patching, check_accounts, check_rdp, check_scan_context,
]


def sort_findings(findings):
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f["severity"]], f["check"], f["subject"]))


def run_checks(snapshot):
    findings = []
    for check in ALL_CHECKS:
        findings.extend(check(snapshot))
    return sort_findings(findings)
