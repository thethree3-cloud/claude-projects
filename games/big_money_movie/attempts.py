"""Attempt orchestration: starting an attempt, recording guesses, scoring
a finished attempt's elapsed time, and rendering the masked title
(reflecting any hints -- see hints.py -- already used on the attempt).
Wires guess_loop.py's pure logic to the SQLite schema in db.py. Every
timestamp comes from guess_loop.now_iso() (server clock) -- never from
the caller.
"""
from __future__ import annotations

import sqlite3

from guess_loop import (
    check_guess,
    elapsed_ms,
    mask_title_with_reveals,
    now_iso,
    partial_reveal_positions,
)


class AttemptError(Exception):
    """An expected game-state problem the caller should show the player a
    readable message for (already finished, duplicate attempt, unknown
    id) -- not a bug."""


def get_puzzle_answer(conn: sqlite3.Connection, puzzle_id: int) -> dict:
    row = conn.execute(
        """
        SELECT category_pool.title, category_pool.word_count
        FROM puzzles
        JOIN category_pool ON category_pool.movie_id = puzzles.answer_movie_id
        WHERE puzzles.id = ?
        """,
        (puzzle_id,),
    ).fetchone()
    if row is None:
        raise AttemptError(f"No puzzle with id {puzzle_id}")
    return {"title": row[0], "word_count": row[1]}


def get_masked_title(conn: sqlite3.Connection, attempt_id: int) -> str:
    """Masked title reflecting the answer plus whatever hints this
    attempt has already used, if any (hint1/2 reveal a letter each,
    hint3 reveals a whole word -- or, for a single-word title, the first
    half of its letters; see hints.py). Used both for a wrong-guess
    response and for a hint response, so the reveal never regresses
    between calls."""
    row = conn.execute(
        "SELECT puzzle_id, hint1_letter, hint2_letter, hint3_used, hint3_word_index "
        "FROM attempts WHERE id = ?",
        (attempt_id,),
    ).fetchone()
    if row is None:
        raise AttemptError(f"No attempt with id {attempt_id}")
    puzzle_id, hint1_letter, hint2_letter, hint3_used, hint3_word_index = row
    answer = get_puzzle_answer(conn, puzzle_id)
    title = answer["title"]

    revealed_letters = {letter for letter in (hint1_letter, hint2_letter) if letter}
    revealed_word_indices = set()
    revealed_char_indices = set()
    if hint3_used:
        if answer["word_count"] > 1 and hint3_word_index is not None:
            revealed_word_indices.add(hint3_word_index)
        else:
            revealed_char_indices = partial_reveal_positions(title)

    return mask_title_with_reveals(
        title,
        revealed_letters=revealed_letters,
        revealed_word_indices=revealed_word_indices,
        revealed_char_indices=revealed_char_indices,
    )


def start_attempt(conn: sqlite3.Connection, puzzle_id: int, player_id: str) -> int:
    """Create a new attempt, server-stamped with the current time. One
    attempt per player per puzzle -- checked here, and backstopped by the
    UNIQUE(puzzle_id, player_id) constraint in the schema."""
    existing = conn.execute(
        "SELECT id FROM attempts WHERE puzzle_id = ? AND player_id = ?",
        (puzzle_id, player_id),
    ).fetchone()
    if existing is not None:
        raise AttemptError(f"Player {player_id!r} already has an attempt on puzzle {puzzle_id}")

    # get_puzzle_answer both validates the puzzle exists and fails fast
    # with a readable error if it doesn't, before an attempt row is created.
    get_puzzle_answer(conn, puzzle_id)

    cursor = conn.execute(
        "INSERT INTO attempts (puzzle_id, player_id, started_at, guess_count, total_penalty_ms) "
        "VALUES (?, ?, ?, 0, 0)",
        (puzzle_id, player_id, now_iso()),
    )
    conn.commit()
    return cursor.lastrowid


def submit_guess(conn: sqlite3.Connection, attempt_id: int, guess_text: str) -> dict:
    """Record a guess against an attempt. A correct guess stops the clock
    -- finished_at and final_elapsed_ms are both set server-side, right
    here, never trusted from the client. Raises AttemptError if the
    attempt doesn't exist or is already finished (no retry-until-fast)."""
    attempt = conn.execute(
        "SELECT puzzle_id, finished_at, started_at, total_penalty_ms FROM attempts WHERE id = ?",
        (attempt_id,),
    ).fetchone()
    if attempt is None:
        raise AttemptError(f"No attempt with id {attempt_id}")
    puzzle_id, finished_at, started_at, total_penalty_ms = attempt
    if finished_at is not None:
        raise AttemptError(f"Attempt {attempt_id} is already finished")

    answer = get_puzzle_answer(conn, puzzle_id)
    correct = check_guess(guess_text, answer["title"])
    guessed_at = now_iso()

    conn.execute(
        "INSERT INTO guesses (attempt_id, guess_text, guessed_at, correct) VALUES (?, ?, ?, ?)",
        (attempt_id, guess_text, guessed_at, int(correct)),
    )
    conn.execute("UPDATE attempts SET guess_count = guess_count + 1 WHERE id = ?", (attempt_id,))
    if correct:
        final_elapsed = elapsed_ms(started_at, guessed_at) + total_penalty_ms
        conn.execute(
            "UPDATE attempts SET finished_at = ?, final_elapsed_ms = ? WHERE id = ?",
            (guessed_at, final_elapsed, attempt_id),
        )
    conn.commit()

    guess_count = conn.execute(
        "SELECT guess_count FROM attempts WHERE id = ?", (attempt_id,)
    ).fetchone()[0]

    return {
        "correct": correct,
        "guess_count": guess_count,
        "masked_title": answer["title"] if correct else get_masked_title(conn, attempt_id),
    }
