# Test fixtures

`recorded/` holds **fictional** command output, one file per allowlisted command
name in `runner.py`. It's shaped like real PowerShell output but every value is
made up (host `TESTBOX-01`, user `testuser`).

Some planted problems are included so later slices can test their checks
against them:

- `updater.exe` running from `AppData\Roaming`: listening on port 4444, started
  by a scheduled task, and launched by a WMI `CommandLineEventConsumer`
- an HKCU Run key running hidden, encoded PowerShell
- a recently added `sync.vbs` in the Startup folder
- RDP (3389) listening on all interfaces
- an auto-start service running from `C:\ProgramData`
- a scheduled task whose name is a prompt-injection attempt

Never put real machine output here.
