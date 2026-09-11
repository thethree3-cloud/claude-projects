"""Leaderboard query for one puzzle: fastest finished attempts first.

Scoring itself happens in attempts.submit_guess() (final_elapsed_ms =
server-clock elapsed time + total_penalty_ms, computed the instant a
correct guess lands) -- this module only ranks what's already scored.
"""
from __future__ import annotations

import sqlite3

# Resolved 2026-09-11 (was an open question in the games_track spec):
# primary sort is final_elapsed_ms ascending. Ties break on fewer guesses,
# then on whoever finished first in absolute time -- both deterministic,
# no two attempts can tie all three (finished_at is unique per attempt).
ORDER_BY = "final_elapsed_ms ASC, guess_count ASC, finished_at ASC"


def get_leaderboard(conn: sqlite3.Connection, puzzle_id: int, limit: int = 10) -> list[dict]:
    """Top `limit` finished attempts for a puzzle, fastest first. Attempts
    with no finished_at (still in progress, or abandoned) never appear --
    there's nothing to rank yet."""
    rows = conn.execute(
        f"""
        SELECT player_id, final_elapsed_ms, guess_count, finished_at
        FROM attempts
        WHERE puzzle_id = ? AND finished_at IS NOT NULL
        ORDER BY {ORDER_BY}
        LIMIT ?
        """,
        (puzzle_id, limit),
    ).fetchall()

    return [
        {
            "rank": i,
            "player_id": player_id,
            "final_elapsed_ms": final_elapsed_ms,
            "guess_count": guess_count,
            "finished_at": finished_at,
        }
        for i, (player_id, final_elapsed_ms, guess_count, finished_at) in enumerate(rows, start=1)
    ]
