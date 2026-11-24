"""Allowlisted, read-only command runner.

This is the first safety layer. Every command the tool can run is in ALLOWLIST
below as a fixed string. Nothing is built from user input or LLM output, there
is no shell, and each command has a timeout and an output size cap.

Callers ask for a command by name: run("win_listen_tcp"). An unknown name is
refused, never passed through.
"""

import subprocess
from dataclasses import dataclass

POWERSHELL = "powershell.exe"
DEFAULT_TIMEOUT_S = 60
MAX_OUTPUT_BYTES = 5 * 1024 * 1024  # 5 MB

# Makes PowerShell 5.1 write UTF-8 so non-ASCII names decode correctly.
# It only changes this one process's console output setting.
_PS_PREFIX = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "

# Each script ends in `ConvertTo-Json -InputObject @(...)` so the output is
# always a JSON array, even for zero or one item.
_WINDOWS_SCRIPTS = {
    "win_host_info": (
        "$os = Get-CimInstance Win32_OperatingSystem; "
        "$id = [Security.Principal.WindowsIdentity]::GetCurrent(); "
        "$admin = ([Security.Principal.WindowsPrincipal]$id).IsInRole("
        "[Security.Principal.WindowsBuiltInRole]::Administrator); "
        "ConvertTo-Json -Compress -InputObject @([pscustomobject]@{"
        "Hostname=$env:COMPUTERNAME; User=$env:USERNAME; IsAdmin=$admin; "
        "OsCaption=$os.Caption; OsVersion=$os.Version; OsBuild=$os.BuildNumber})"
    ),
    "win_listen_tcp": (
        "$c = Get-NetTCPConnection -State Listen | "
        "Select-Object LocalAddress, LocalPort, OwningProcess; "
        "ConvertTo-Json -Compress -InputObject @($c)"
    ),
    "win_listen_udp": (
        "$c = Get-NetUDPEndpoint | Select-Object LocalAddress, LocalPort, OwningProcess; "
        "ConvertTo-Json -Compress -InputObject @($c)"
    ),
    "win_processes": (
        "$p = Get-Process | Select-Object Id, ProcessName, Path; "
        "ConvertTo-Json -Compress -InputObject @($p)"
    ),
    "win_run_keys": (
        "$paths = @("
        "'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run',"
        "'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce',"
        "'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Run',"
        "'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\RunOnce',"
        "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run',"
        "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce'); "
        "$out = foreach ($p in $paths) { if (Test-Path $p) { $k = Get-Item $p; "
        "foreach ($n in $k.GetValueNames()) { [pscustomobject]@{"
        "Key=$p; Name=$n; Value=[string]$k.GetValue($n)} } } }; "
        "ConvertTo-Json -Compress -InputObject @($out)"
    ),
    "win_startup_folders": (
        "$dirs = @([Environment]::GetFolderPath('Startup'), "
        "[Environment]::GetFolderPath('CommonStartup')); "
        "$out = foreach ($d in $dirs) { if ($d -and (Test-Path $d)) { "
        "Get-ChildItem -LiteralPath $d -Force -File | ForEach-Object { [pscustomobject]@{"
        "Folder=$d; Name=$_.Name; FullName=$_.FullName; Length=$_.Length; "
        "LastWriteUtc=$_.LastWriteTimeUtc.ToString('o')} } } }; "
        "ConvertTo-Json -Compress -InputObject @($out)"
    ),
    "win_scheduled_tasks": (
        "$out = Get-ScheduledTask | ForEach-Object { $t = $_; "
        "foreach ($a in @($t.Actions)) { [pscustomobject]@{"
        "TaskPath=$t.TaskPath; TaskName=$t.TaskName; State=[string]$t.State; "
        "Author=$t.Author; UserId=$t.Principal.UserId; "
        "RunLevel=[string]$t.Principal.RunLevel; "
        "Execute=$a.Execute; Arguments=$a.Arguments; ClassId=$a.ClassId} } }; "
        "ConvertTo-Json -Compress -InputObject @($out)"
    ),
    "win_auto_services": (
        "$s = Get-CimInstance Win32_Service -Filter \"StartMode='Auto'\" | "
        "Select-Object Name, DisplayName, PathName, State, StartName; "
        "ConvertTo-Json -Compress -InputObject @($s)"
    ),
    "win_wmi_subscriptions": (
        "$ns = 'root/subscription'; "
        "$c = Get-CimInstance -Namespace $ns -ClassName __EventConsumer | ForEach-Object { "
        "[pscustomobject]@{Kind='consumer'; Class=$_.CimClass.CimClassName; Name=$_.Name; "
        "CommandLine=$_.CommandLineTemplate; ScriptText=$_.ScriptText; Query=$null} }; "
        "$f = Get-CimInstance -Namespace $ns -ClassName __EventFilter | ForEach-Object { "
        "[pscustomobject]@{Kind='filter'; Class=$_.CimClass.CimClassName; Name=$_.Name; "
        "CommandLine=$null; ScriptText=$null; Query=$_.Query} }; "
        "ConvertTo-Json -Compress -InputObject @(@($c) + @($f))"
    ),
}

# name -> argv. Built once at import time from fixed strings only.
ALLOWLIST = {
    name: [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", _PS_PREFIX + script]
    for name, script in _WINDOWS_SCRIPTS.items()
}


@dataclass
class RunResult:
    name: str
    ok: bool
    stdout: str = ""
    error: str | None = None


def run(name, timeout=DEFAULT_TIMEOUT_S):
    """Run one allowlisted command by name. Never raises for command failures."""
    if name not in ALLOWLIST:
        raise ValueError(f"command not in allowlist: {name!r}")
    argv = ALLOWLIST[name]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except FileNotFoundError:
        return RunResult(name, False, error=f"{argv[0]} not found (is this WSL on Windows?)")
    except subprocess.TimeoutExpired:
        return RunResult(name, False, error=f"timed out after {timeout}s")

    if len(proc.stdout) > MAX_OUTPUT_BYTES:
        return RunResult(name, False, error=f"output over {MAX_OUTPUT_BYTES} bytes, discarded")

    stdout = proc.stdout.decode("utf-8", errors="replace").lstrip("﻿").strip()
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        return RunResult(name, False, stdout, error=_first_line(stderr) or f"exit {proc.returncode}")
    return RunResult(name, True, stdout)


def _first_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:300]
    return ""
