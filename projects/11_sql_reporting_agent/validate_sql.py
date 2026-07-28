"""Validation layer: only a single, clean T-SQL SELECT is allowed through.

This is the second safety layer (the first is the db_datareader-only login
from setup_readonly_login.py). Even though that login can't physically
write anything, this still rejects non-SELECT statements before they ever
reach the database -- both to fail fast with a clear reason, and because
relying on a single layer of defense is bad practice.
"""
import re
import sys

FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "MERGE", "GRANT", "REVOKE", "DENY", "EXEC", "EXECUTE", "BACKUP",
    "RESTORE", "SHUTDOWN", "INTO",  # INTO catches "SELECT ... INTO NewTable"
]
FORBIDDEN_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(FORBIDDEN_KEYWORDS) + r")\b", re.IGNORECASE
)
PROC_PREFIX_RE = re.compile(r"\b(sp_|xp_)\w+", re.IGNORECASE)
LINE_COMMENT_RE = re.compile(r"--[^\n]*")
BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")


class SQLValidationError(ValueError):
    pass


def _strip_comments(sql):
    sql = BLOCK_COMMENT_RE.sub(" ", sql)
    sql = LINE_COMMENT_RE.sub(" ", sql)
    return sql


def validate_select(sql):
    """Return the SQL, trimmed, if it's a safe single SELECT. Raise otherwise."""
    if not sql or not sql.strip():
        raise SQLValidationError("Empty query.")

    cleaned = _strip_comments(sql).strip()
    if not cleaned:
        raise SQLValidationError("Query contained only comments.")

    # Blank out string literal contents so keyword/semicolon checks below
    # can't be tripped up by legitimate text like WHERE Name LIKE '%update%',
    # and can't be fooled by a forbidden keyword hidden inside a string.
    scan_target = STRING_LITERAL_RE.sub("''", cleaned)

    # Allow one optional trailing semicolon; anything else means multiple
    # chained statements, which is exactly what this guards against.
    body = scan_target.strip()
    if body.endswith(";"):
        body = body[:-1].strip()
    if ";" in body:
        raise SQLValidationError("Multiple statements are not allowed (found ';' mid-query).")

    if not re.match(r"^\s*(SELECT|WITH)\b", body, re.IGNORECASE):
        raise SQLValidationError("Query must start with SELECT (or WITH ... SELECT).")

    keyword_hit = FORBIDDEN_KEYWORD_RE.search(body)
    if keyword_hit:
        raise SQLValidationError(f"Forbidden keyword '{keyword_hit.group(1)}' is not allowed.")

    proc_hit = PROC_PREFIX_RE.search(body)
    if proc_hit:
        raise SQLValidationError(f"Stored procedure calls ('{proc_hit.group(0)}') are not allowed.")

    # Return the original (not string-blanked) text, comments stripped,
    # trailing semicolon removed -- ready to execute as-is.
    trimmed = cleaned.strip()
    if trimmed.endswith(";"):
        trimmed = trimmed[:-1].strip()
    return trimmed


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {__file__} \"<sql>\"")
        sys.exit(1)
    try:
        print(validate_select(" ".join(sys.argv[1:])))
    except SQLValidationError as e:
        print(f"REJECTED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
