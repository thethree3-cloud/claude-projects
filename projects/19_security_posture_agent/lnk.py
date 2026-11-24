"""Read the target and arguments of a Windows shortcut (.lnk) file.

A shortcut in the Startup folder is only as safe as what it points to, and a
shortcut named "OneDrive.lnk" can launch `powershell -enc ...`. This parses
the documented Shell Link format (MS-SHLLINK) directly. No PowerShell or COM
object is involved, so the PowerShell scripts in runner.py stay read-only cmdlets.

Files are read from WSL through /mnt/<drive>/, read-only, at most 1 MB, and
only for .lnk files in the Startup folders the collector already listed.
"""

import re
import struct
from pathlib import Path

MAX_LNK_BYTES = 1024 * 1024
_HEADER_SIZE = 0x4C
_LINK_CLSID = bytes.fromhex("0114020000000000c000000000000046")

HAS_ID_LIST = 1 << 0
HAS_LINK_INFO = 1 << 1
HAS_NAME = 1 << 2
HAS_RELATIVE_PATH = 1 << 3
HAS_WORKING_DIR = 1 << 4
HAS_ARGUMENTS = 1 << 5
HAS_ICON = 1 << 6
IS_UNICODE = 1 << 7


def windows_to_wsl_path(path):
    """C:\\Users\\x -> /mnt/c/Users/x. None for anything that isn't a drive path."""
    m = re.match(r"^([A-Za-z]):\\(.*)$", path or "")
    if not m:
        return None
    return Path(f"/mnt/{m.group(1).lower()}") / m.group(2).replace("\\", "/")


def read_windows_file(path):
    """Bytes of a Windows file, or None if it can't be read."""
    p = windows_to_wsl_path(path)
    if p is None:
        return None
    try:
        with open(p, "rb") as f:
            data = f.read(MAX_LNK_BYTES + 1)
    except OSError:
        return None
    return data if len(data) <= MAX_LNK_BYTES else None


def _cstring(data, start, unicode):
    if unicode:
        end = start
        while end + 1 < len(data) and data[end:end + 2] != b"\x00\x00":
            end += 2
        return data[start:end].decode("utf-16-le", errors="replace")
    end = data.find(b"\x00", start)
    return data[start:end if end >= 0 else len(data)].decode("cp1252", errors="replace")


_ENV_BLOCK_SIGNATURE = 0xA0000001
_ENV_BLOCK_SIZE = 0x314


def _env_target(data, pos):
    """Target from an EnvironmentVariableDataBlock (e.g. %windir%\\system32\\x.exe).

    Windows' own tool shortcuts store their target only here, with no LinkInfo.
    """
    while pos + 8 <= len(data):
        size, signature = struct.unpack_from("<II", data, pos)
        if size < 8:
            return None
        if signature == _ENV_BLOCK_SIGNATURE and size >= _ENV_BLOCK_SIZE:
            uni = _cstring(data, pos + 8 + 260, unicode=True)
            return uni or _cstring(data, pos + 8, unicode=False) or None
        pos += size
    return None


def parse_lnk(data):
    """{'target': str|None, 'arguments': str|None}, or None if not a shortcut."""
    try:
        if len(data) < _HEADER_SIZE or struct.unpack_from("<I", data, 0)[0] != _HEADER_SIZE:
            return None
        if data[4:20] != _LINK_CLSID:
            return None
        flags = struct.unpack_from("<I", data, 20)[0]
        pos = _HEADER_SIZE

        if flags & HAS_ID_LIST:
            pos += 2 + struct.unpack_from("<H", data, pos)[0]

        target = None
        if flags & HAS_LINK_INFO:
            start = pos
            size, header_size, info_flags = struct.unpack_from("<III", data, start)
            local_off, _, suffix_off = struct.unpack_from("<III", data, start + 16)
            if info_flags & 1:  # VolumeIDAndLocalBasePath
                if header_size >= 0x24:
                    uni_off = struct.unpack_from("<I", data, start + 28)[0]
                    target = _cstring(data, start + uni_off, unicode=True)
                else:
                    target = _cstring(data, start + local_off, unicode=False)
                suffix = _cstring(data, start + suffix_off, unicode=False) if suffix_off else ""
                target = (target or "") + suffix
            pos = start + size

        unicode = bool(flags & IS_UNICODE)
        strings = {}
        for flag, name in ((HAS_NAME, "name"), (HAS_RELATIVE_PATH, "relative_path"),
                           (HAS_WORKING_DIR, "working_dir"), (HAS_ARGUMENTS, "arguments"),
                           (HAS_ICON, "icon")):
            if flags & flag:
                count = struct.unpack_from("<H", data, pos)[0]
                pos += 2
                width = 2 if unicode else 1
                raw = data[pos:pos + count * width]
                if len(raw) < count * width:
                    return None
                strings[name] = raw.decode("utf-16-le" if unicode else "cp1252", errors="replace")
                pos += count * width

        env_target = _env_target(data, pos)
        return {
            "target": target or env_target or strings.get("relative_path"),
            "arguments": strings.get("arguments"),
        }
    except struct.error:
        return None
