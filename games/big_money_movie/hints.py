"""Hint system, v1: three tiers, each usable once per attempt, each
adding a fixed time penalty to total_penalty_ms (already folded into
final_elapsed_ms by attempts.submit_guess -- see games_track memory).

  Tier 1 -- vowel:     reveal every occurrence of one vowel.     +15s
  Tier 2 -- consonant: reveal every occurrence of one consonant. +30s
  Tier 3 -- word:      reveal one whole word.                    +60s

Selection rule (v1, locked in): the server always picks a letter/word
that's actually in the title -- no wasted hints, no exploit where a
player always requests the rarest letter for outsized value. A v2
user-picks-the-letter mode (Wheel-of-Fortune style, miss costs the hint
too) is explicitly deferred, not built here.

Tier 3 on a single-word title has nothing else to reveal without
trivially solving the puzzle, so it falls back to revealing the first
half of that word's letters instead -- see partial_reveal_positions in
guess_loop.py.
"""
from __future__ import annotations

import random
import sqlite3

from attempts import AttemptError, get_masked_title, get_puzzle_answer

# Placeholders -- tune from real median solve times once played (per spec).
TIER_PENALTIES_MS = {1: 15_000, 2: 30_000, 3: 60_000}

VOWELS = set("aeiou")


class HintError(AttemptError):
    """Hint-specific expected-state problem (already used, invalid tier,
    nothing left to reveal) -- same "readable message, not a bug"
    contract as AttemptError."""


def _present_letters(title: str, is_match) -> list[str]:
    """Distinct lowercase letters in `title` satisfying `is_match`, in
    first-appearance order. Only ever returns letters guaranteed to be in
    the title -- the whole point of the v1 selection rule."""
    seen = []
    for ch in title.lower():
        if ch.isalpha() and is_match(ch) and ch not in seen:
            seen.append(ch)
    return seen


def apply_hint(conn: sqlite3.Connection, attempt_id: int, tier: int) -> dict:
    """Apply one hint tier to an attempt. Raises HintError if the tier is
    invalid, already used on this attempt, or the attempt doesn't exist
    or is already finished."""
    if tier not in TIER_PENALTIES_MS:
        raise HintError(f"Invalid hint tier {tier!r}; must be 1, 2, or 3")

    row = conn.execute(
        "SELECT puzzle_id, finished_at, hint1_used, hint2_used, hint3_used, total_penalty_ms "
        "FROM attempts WHERE id = ?",
        (attempt_id,),
    ).fetchone()
    if row is None:
        raise HintError(f"No attempt with id {attempt_id}")
    puzzle_id, finished_at, hint1_used, hint2_used, hint3_used, total_penalty_ms = row
    if finished_at is not None:
        raise HintError(f"Attempt {attempt_id} is already finished")

    already_used = {1: hint1_used, 2: hint2_used, 3: hint3_used}[tier]
    if already_used:
        raise HintError(f"Tier {tier} hint already used on attempt {attempt_id}")

    answer = get_puzzle_answer(conn, puzzle_id)
    title = answer["title"]

    if tier == 1:
        candidates = _present_letters(title, lambda ch: ch in VOWELS)
        if not candidates:
            raise HintError("No vowel available to reveal for this title")
        letter = random.choice(candidates)
        conn.execute(
            "UPDATE attempts SET hint1_used = 1, hint1_letter = ? WHERE id = ?",
            (letter, attempt_id),
        )
    elif tier == 2:
        candidates = _present_letters(title, lambda ch: ch not in VOWELS)
        if not candidates:
            raise HintError("No consonant available to reveal for this title")
        letter = random.choice(candidates)
        conn.execute(
            "UPDATE attempts SET hint2_used = 1, hint2_letter = ? WHERE id = ?",
            (letter, attempt_id),
        )
    else:  # tier == 3
        if answer["word_count"] > 1:
            word_index = random.randrange(answer["word_count"])
            conn.execute(
                "UPDATE attempts SET hint3_used = 1, hint3_word_index = ? WHERE id = ?",
                (word_index, attempt_id),
            )
        else:
            # Single-word fallback: hint3_word_index stays NULL. At
            # render time, get_masked_title() treats
            # (hint3_used AND word_count == 1) as the signal to apply
            # the deterministic partial reveal -- no extra column needed.
            conn.execute("UPDATE attempts SET hint3_used = 1 WHERE id = ?", (attempt_id,))

    new_total_penalty = total_penalty_ms + TIER_PENALTIES_MS[tier]
    conn.execute(
        "UPDATE attempts SET total_penalty_ms = ? WHERE id = ?", (new_total_penalty, attempt_id)
    )
    conn.commit()

    return {
        "tier": tier,
        "penalty_ms": TIER_PENALTIES_MS[tier],
        "total_penalty_ms": new_total_penalty,
        "masked_title": get_masked_title(conn, attempt_id),
    }
