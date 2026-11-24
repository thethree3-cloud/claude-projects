"""Replace identifying details before findings leave the machine.

Only findings go to the LLM, never the raw snapshot. Before that, the Windows
username, computer name, other local account names and account SIDs are
swapped for placeholders like <user> and <account-2>. The mapping stays local,
so the report can put the real names back.
"""

import re

_SID = re.compile(r"S-1-5-21-\d+-\d+-\d+(-\d+)?")
_USER_PATH = re.compile(r"(?i)([a-z]:\\users\\)([^\\\"'\s]+)")


class Redactor:
    def __init__(self, snapshot):
        self.mapping = {}  # real -> placeholder
        host = (snapshot["sections"].get("host") or {}).get("items") or [{}]
        user = host[0].get("user")
        hostname = host[0].get("hostname")
        if user:
            self._add(user, "<user>")
        if hostname:
            self._add(hostname, "<computer>")
        users = (snapshot["sections"].get("local_users") or {}).get("items") or []
        admins = (snapshot["sections"].get("local_admins") or {}).get("items") or []
        names = [u.get("name") for u in users] + [(a.get("name") or "").rsplit("\\", 1)[-1] for a in admins]
        n = 1
        for name in names:
            if name and name.lower() not in {k.lower() for k in self.mapping} and not _builtin(name):
                n += 1
                self._add(name, f"<account-{n}>")

    def _add(self, real, placeholder):
        if len(real) >= 2:  # never redact single characters
            self.mapping[real] = placeholder

    def text(self, value):
        if not isinstance(value, str):
            return value
        value = _SID.sub(lambda m: "<sid>" + (m.group(1) or ""), value)
        value = _USER_PATH.sub(lambda m: m.group(1) + self._placeholder_for(m.group(2)), value)
        # Longest names first, whole-word, case-insensitive.
        for real in sorted(self.mapping, key=len, reverse=True):
            value = re.sub(rf"(?i)(?<![\w-]){re.escape(real)}(?![\w-])", self.mapping[real], value)
        return value

    def _placeholder_for(self, name):
        for real, ph in self.mapping.items():
            if real.lower() == name.lower():
                return ph
        return "<other-user>"

    def obj(self, value):
        """Redact every string inside dicts / lists, keys included."""
        if isinstance(value, dict):
            return {self.text(k): self.obj(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.obj(v) for v in value]
        return self.text(value)

    def restore(self, value):
        """Put real names back into text written for the local report."""
        if not isinstance(value, str):
            return value
        for real, ph in self.mapping.items():
            value = value.replace(ph, real)
        return value


_BUILTIN = {"administrator", "guest", "defaultaccount", "wdagutilityaccount", "system"}


def _builtin(name):
    """Built-in Windows account names identify no one, and redacting them hides meaning."""
    return name.lower() in _BUILTIN
