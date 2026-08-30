"""A local SQLite log of job applications — what you sent where, and when.

A personal tracker in the spirit of the rest of Project 10: the database
lives in the gitignored ``data/`` directory and never leaves your machine.
The Streamlit "Applications" tab reads and writes it through the functions
here; that's the whole API.

    conn = connect("data/applications.db")
    add_application(conn, company="Northwind", role="Data Analyst",
                    resume_variant="tailored", next_action="follow up",
                    next_action_on="2026-09-05")
    agenda(conn)   # -> {"overdue": [...], "this_week": [...], "later": [...]}
"""

import datetime
import sqlite3

STATUSES = ("applied", "screening", "interview", "offer", "rejected", "withdrawn")
# statuses that still need attention — the agenda only surfaces these
_OPEN = ("applied", "screening", "interview", "offer")

_EDITABLE = (
    "company",
    "role",
    "applied_on",
    "resume_variant",
    "status",
    "next_action",
    "next_action_on",
    "link",
    "notes",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company         TEXT NOT NULL,
    role            TEXT NOT NULL,
    applied_on      TEXT NOT NULL,
    resume_variant  TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'applied',
    next_action     TEXT NOT NULL DEFAULT '',
    next_action_on  TEXT,
    link            TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
)
"""


def connect(db_path):
    """Open (creating if needed) the application-log database."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _validate(fields):
    unknown = set(fields) - set(_EDITABLE)
    if unknown:
        raise ValueError(f"unknown field(s): {sorted(unknown)}")
    status = fields.get("status")
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
    return fields


def add_application(conn, *, company, role, applied_on=None, **rest):
    """Insert one application. Returns its new id. `applied_on` defaults to
    today; `status` defaults to 'applied'."""
    fields = _validate(dict(rest))
    fields["company"] = company
    fields["role"] = role
    fields["applied_on"] = applied_on or datetime.date.today().isoformat()
    now = _now()
    columns = [*fields, "created_at", "updated_at"]
    values = [*fields.values(), now, now]
    marks = ", ".join(["?"] * len(columns))
    cur = conn.execute(
        f"INSERT INTO applications ({', '.join(columns)}) VALUES ({marks})", values
    )
    conn.commit()
    return cur.lastrowid


def update_application(conn, app_id, **fields):
    """Patch the given fields on one application. No-op if `fields` is empty."""
    fields = _validate(dict(fields))
    if not fields:
        return
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"UPDATE applications SET {assignments} WHERE id = ?",
        [*fields.values(), app_id],
    )
    conn.commit()


def delete_application(conn, app_id):
    conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
    conn.commit()


def list_applications(conn, status=None):
    """All applications, newest application-date first. `status` filters."""
    sql = "SELECT * FROM applications"
    params = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY date(applied_on) DESC, id DESC"
    return [dict(row) for row in conn.execute(sql, params)]


def agenda(conn, today=None):
    """Open applications that have a next-action date, grouped into
    ``overdue`` / ``this_week`` / ``later``. Closed applications (rejected,
    withdrawn) and entries with no next-action date are left out."""
    today = today or datetime.date.today()
    week_out = today + datetime.timedelta(days=7)
    buckets = {"overdue": [], "this_week": [], "later": []}
    rows = conn.execute(
        "SELECT * FROM applications "
        "WHERE next_action_on IS NOT NULL AND next_action_on != '' "
        "ORDER BY date(next_action_on), id"
    )
    for row in rows:
        if row["status"] not in _OPEN:
            continue
        due = datetime.date.fromisoformat(row["next_action_on"])
        entry = dict(row)
        if due < today:
            buckets["overdue"].append(entry)
        elif due <= week_out:
            buckets["this_week"].append(entry)
        else:
            buckets["later"].append(entry)
    return buckets
