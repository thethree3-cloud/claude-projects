"""Check Claude's explanation against the real findings before showing it.

Claude's output is treated as a draft that has to pass these checks. Anything
that fails is dropped, and the reason is listed in the report, so the
deterministic findings are always the source of truth:

1. Every finding ID it mentions must exist. Unknown IDs are dropped.
2. Every finding must be covered. Missing ones go into an "Other findings"
   group, added by code.
3. A finding sits in only one group (its first one).
4. Severity notes may suggest a change of one level at most, with a reason.
   They're shown as notes and never change the rule's severity.
5. Explanations can't contain commands or code (fixes come from the catalog).
6. Grounding: any program file name or port number an explanation mentions
   must appear in the evidence of some finding. Cross-references between
   groups are fine ("unlike port 4444 above..."); invented names are not.
   (A first version required the group's *own* findings. On the planted
   fixture it removed a correct explanation that cross-referenced another group.)
7. The summary can't call the computer safe or clean while high findings exist.
8. Length caps.
"""

import json
import re

from checks import SEVERITY_ORDER

MAX_SUMMARY = 1200
MAX_EXPLANATION = 1500
MAX_TITLE = 120
MAX_NOTE_REASON = 800

_COMMANDS = re.compile(
    # Command-shaped text only: "it runs hidden PowerShell" is a fine description,
    # "powershell -enc ..." is a command.
    r"`|\bnet\s+(user|localgroup)\b|\b(powershell|pwsh)(\.exe)?\s+-\w|\bcmd(\.exe)?\s+/c\b"
    r"|\breg(\.exe)?\s+(add|delete)\b"
    r"|\bsc(\.exe)?\s+(delete|config|stop)\b|\b(Set|Remove|Stop|Disable|New|Add)-[A-Z][a-z]+"
    r"|\bschtasks\b|\bwmic\b|\brm\s+-|\bdel\s+/",
    re.I,
)
_FILE_NAMES = re.compile(r"\b[\w.-]+\.(exe|dll|ps1|vbs|lnk|bat|cmd|js|hta|scr|sys)\b", re.I)
_PORTS = re.compile(r"\bport\s+(\d{1,5})\b|\b(?:tcp|udp)/(\d{1,5})\b", re.I)
_FALSE_ALL_CLEAR = re.compile(
    r"\b(no (serious|significant|real|major) (issues|problems|risks)|nothing to worry|all clear"
    r"|(is|looks|appears) (safe|clean|secure)|no action (is )?needed)\b",
    re.I,
)


# Words that turn "the computer is safe" into a description of what something
# else says, or into its opposite. Found by the Slice 5 pilot: Claude wrote that
# a task's name "is written to look like a message telling the reader the
# computer is safe", a correct warning, and the old check deleted it.
_NOT_ASSERTED = re.compile(
    r"\b(no|not|nothing|never|isn't|aren't|doesn't|don't|without|tell\w*|told|claim\w*|says?|said|"
    r"message|written|named|name|pretend\w*|disguis\w*|label\w*|instruct\w*|like|fake|supposed\w*)\b",
    re.I,
)


def asserts_all_clear(text):
    """True if the text itself says the computer is fine. Phrases inside quotes,
    reported speech ("its name tells you the computer is safe") or a negation
    within the 8 words before them don't count."""
    text = text or ""
    for m in _FALSE_ALL_CLEAR.finditer(text):
        before = text[:m.start()]
        if before.count("'") % 2 or before.count('"') % 2:
            continue  # inside a quotation
        window = " ".join(before.split()[-8:])
        if _NOT_ASSERTED.search(window):
            continue
        return True
    return False


def _haystack(findings):
    """Everything a group's explanation is allowed to name."""
    return json.dumps([{"t": f["title"], "s": f["subject"], "e": f["evidence"]} for f in findings],
                      ensure_ascii=False).lower()


def _ungrounded(text, findings):
    hay = _haystack(findings)
    missing = [m.group(0) for m in _FILE_NAMES.finditer(text) if m.group(0).lower() not in hay]
    for m in _PORTS.finditer(text):
        port = m.group(1) or m.group(2)
        if not re.search(rf"(?<!\d){port}(?!\d)", hay):
            missing.append(f"port {port}")
    return missing


def validate(raw, findings, redactor=None):
    """Returns a dict: summary, groups (with real finding dicts), notes,
    rejected (list of reasons), accepted (bool: anything usable at all)."""
    by_id = {f["id"]: f for f in findings}
    rejected = []

    if not isinstance(raw, dict) or not isinstance(raw.get("groups"), list):
        return {"accepted": False, "summary": None, "groups": [], "notes": [],
                "rejected": ["answer didn't match the expected shape"]}

    # Check against real names (placeholders restored), since evidence has real names.
    restore = redactor.restore if redactor else (lambda s: s)

    summary = restore(str(raw.get("summary") or "").strip())
    if len(summary) > MAX_SUMMARY:
        rejected.append(f"summary over {MAX_SUMMARY} characters")
        summary = None
    elif summary and _COMMANDS.search(summary):
        rejected.append("summary contained a command")
        summary = None
    elif summary and any(f["severity"] == "high" for f in findings) and asserts_all_clear(summary):
        rejected.append("summary called the computer safe while high findings exist")
        summary = None

    seen, groups = set(), []
    for g in sorted((g for g in raw["groups"] if isinstance(g, dict)),
                    key=lambda g: g.get("priority") if isinstance(g.get("priority"), int) else 999):
        title = restore(str(g.get("title") or "").strip())[:MAX_TITLE] or "Findings"
        ids = [i for i in g.get("finding_ids") or [] if isinstance(i, str)]
        unknown = [i for i in ids if i not in by_id]
        if unknown:
            rejected.append(f"group '{title}' named finding IDs that don't exist: {', '.join(unknown)}")
        dupes = [i for i in ids if i in seen and i in by_id]
        if dupes:
            rejected.append(f"group '{title}' repeated findings already in another group")
        members = []
        for i in ids:
            if i in by_id and i not in seen:
                members.append(by_id[i])
                seen.add(i)
        if not members:
            continue

        explanation = restore(str(g.get("explanation") or "").strip())
        if len(explanation) > MAX_EXPLANATION:
            rejected.append(f"group '{title}': explanation over {MAX_EXPLANATION} characters")
            explanation = None
        elif _COMMANDS.search(explanation):
            rejected.append(f"group '{title}': explanation contained a command or code")
            explanation = None
        else:
            missing = _ungrounded(explanation, findings)
            if missing:
                rejected.append(f"group '{title}': mentioned things not in its findings' evidence: "
                                f"{', '.join(sorted(set(missing)))}")
                explanation = None
        groups.append({"title": title, "explanation": explanation,
                       "findings": sorted(members, key=lambda f: SEVERITY_ORDER[f["severity"]])})

    left_out = [f for f in findings if f["id"] not in seen]
    if left_out:
        if groups:
            rejected.append(f"{len(left_out)} finding(s) weren't covered; listed under 'Other findings'")
        groups.append({"title": "Other findings", "explanation": None, "findings": left_out})

    notes = []
    for n in raw.get("severity_notes") or []:
        if not isinstance(n, dict) or n.get("finding_id") not in by_id:
            rejected.append("severity note for an unknown finding")
            continue
        current = by_id[n["finding_id"]]["severity"]
        suggested = n.get("suggested_severity")
        reason = restore(str(n.get("reason") or "").strip())
        if suggested not in SEVERITY_ORDER or suggested == current:
            continue
        if abs(SEVERITY_ORDER[suggested] - SEVERITY_ORDER[current]) > 1:
            rejected.append(f"severity note for {n['finding_id']} jumped more than one level")
            continue
        # 800, not 400: the Slice 5 eval's one failure was a correct ~470-character reason.
        if not reason or _COMMANDS.search(reason) or len(reason) > MAX_NOTE_REASON:
            rejected.append(f"severity note for {n['finding_id']} had no usable reason")
            continue
        notes.append({"finding": by_id[n["finding_id"]], "suggested": suggested, "reason": reason})

    accepted = bool(summary) or any(g["explanation"] for g in groups)
    return {"accepted": accepted, "summary": summary, "groups": groups, "notes": notes, "rejected": rejected}
