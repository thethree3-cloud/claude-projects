"""Puzzle lookup: which puzzle is "today's" puzzle, and its category
metadata (theme, era, pool size) -- exactly the shape the /category/today
endpoint exposes. Deliberately does NOT return the pool itself or the
answer -- a player calling this endpoint must not be able to just read
off the answer (see games_track memory's anti-cheat notes).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from attempts import AttemptError


def today_iso() -> str:
    """Server-clock calendar date, ISO 8601 (YYYY-MM-DD), in UTC.

    Found via live testing: an earlier version used date.today(), which
    is the *local* server timezone -- inconsistent with every other
    timestamp in this app (guess_loop.now_iso() is explicit UTC), and a
    real correctness bug, not just a style nit. This machine's local date
    was already a full day behind its UTC date when this was caught
    (local 2026-09-10 vs. UTC 2026-09-11 05:42), which means a puzzle
    seeded/looked-up by local "today" would silently point at the wrong
    calendar day depending purely on which timezone the server happens to
    be deployed in (relevant given Project 15's planned Azure
    deployment) -- the exact kind of bug that's invisible in a quick
    local test and only shows up once deployed somewhere with a
    different local timezone, or at certain hours."""
    return datetime.now(timezone.utc).date().isoformat()


def get_puzzle_by_date(conn: sqlite3.Connection, date: str) -> dict:
    row = conn.execute(
        """
        SELECT puzzles.id, categories.name, categories.era,
               (SELECT COUNT(*) FROM category_pool
                WHERE category_pool.category_id = categories.id)
        FROM puzzles
        JOIN categories ON categories.id = puzzles.category_id
        WHERE puzzles.date = ?
        """,
        (date,),
    ).fetchone()
    if row is None:
        raise AttemptError(f"No puzzle scheduled for {date}")
    puzzle_id, theme, era, pool_size = row
    return {"puzzle_id": puzzle_id, "date": date, "theme": theme, "era": era, "pool_size": pool_size}


def get_todays_puzzle(conn: sqlite3.Connection) -> dict:
    return get_puzzle_by_date(conn, today_iso())
