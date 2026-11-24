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

Added in Slice 2:

- Defender: tamper protection off, signatures 12 days old, exclusions on `C:\`,
  the `updater` folder and the `.vbs` extension
- Public firewall profile off
- newest update installed 2026-08-01 (stale by the test date, 2026-11-23)
- an extra local admin (`helpdesk`) whose account allows a blank password
- Guest account enabled
- RDP turned on with Network Level Authentication off
- an auto-start service with an unquoted path containing spaces (`Acme Backup`)
- BitLocker off on the system drive C: (and on data drive D:, which is not flagged)
