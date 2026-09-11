"""Pure guess-loop logic: masking a title for display (plain or with
hint reveals), and deciding whether a guess is correct. No DB, no
side effects -- attempts.py and hints.py wire this to SQLite. Kept pure
and dependency-free on purpose (per the games_track build order: "core
guess loop (pure, testable)" is its own slice) so it's trivial to unit
test.

Reuses imdb_index.normalize_title for guess comparison -- the exact same
normalization the curation script uses to match Claude's proposals
against IMDb, so "Starsky & Hutch" is accepted for an answer stored as
"Starsky and Hutch", the same equivalence curate.py already relies on.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from imdb_index import normalize_title


def _char_word_indices(title: str) -> list[int | None]:
    """Map each character position to its word index (0-based), or None
    for whitespace between words. A "word" is a run of non-space
    characters, matching the same `str.split()` word_count already uses
    (imdb_index.py / generate_pool.py)."""
    indices: list[int | None] = []
    word_idx = -1
    in_word = False
    for ch in title:
        if ch.isspace():
            indices.append(None)
            in_word = False
        else:
            if not in_word:
                word_idx += 1
                in_word = True
            indices.append(word_idx)
    return indices


def mask_title_with_reveals(
    title: str,
    revealed_letters=None,
    revealed_word_indices=None,
    revealed_char_indices=None,
) -> str:
    """Mask a title, but leave visible: any letter in revealed_letters
    (case-insensitive, every occurrence -- "buy a vowel" semantics), every
    letter of any word whose 0-based index is in revealed_word_indices,
    and any exact character position in revealed_char_indices (used by
    the Tier-3 single-word fallback -- see hints.py). Structural
    characters (digits, spaces, punctuation) are always visible, same as
    plain mask_title()."""
    revealed_letters = {l.lower() for l in (revealed_letters or ())}
    revealed_word_indices = revealed_word_indices or set()
    revealed_char_indices = revealed_char_indices or set()
    word_idx_per_char = _char_word_indices(title)

    result = []
    for i, ch in enumerate(title):
        if not ch.isalpha():
            result.append(ch)
        elif i in revealed_char_indices:
            result.append(ch)
        elif word_idx_per_char[i] in revealed_word_indices:
            result.append(ch)
        elif ch.lower() in revealed_letters:
            result.append(ch)
        else:
            result.append("_")
    return "".join(result)


def mask_title(title: str) -> str:
    """Blank out letters, keep structural characters (digits, spaces,
    punctuation) visible. "101 Dalmatians" -> "101 __________". Equivalent
    to mask_title_with_reveals(title) with nothing revealed."""
    return mask_title_with_reveals(title)


def partial_reveal_positions(title: str) -> set[int]:
    """Character indices to reveal for the Tier-3 single-word fallback:
    the first half (rounded up) of the title's alphabetic characters, in
    reading order. Deterministic from the title alone, so no extra state
    needs to be stored beyond "Tier 3 was used" -- see hints.py."""
    alpha_positions = [i for i, ch in enumerate(title) if ch.isalpha()]
    n_to_reveal = math.ceil(len(alpha_positions) / 2)
    return set(alpha_positions[:n_to_reveal])


def check_guess(guess_text: str, answer_title: str) -> bool:
    """A guess is correct if it normalizes to the same string as the
    answer."""
    return normalize_title(guess_text) == normalize_title(answer_title)


def now_iso() -> str:
    """Server-clock timestamp, ISO 8601 UTC. Every timing value in this
    game comes from calls to this, never from anything the client sends --
    see attempts.py."""
    return datetime.now(timezone.utc).isoformat()


def elapsed_ms(started_at_iso: str, finished_at_iso: str) -> int:
    """Milliseconds between two now_iso() timestamps. Both inputs are
    always server timestamps already in the DB -- there is no path where
    a client-supplied time reaches this function."""
    started = datetime.fromisoformat(started_at_iso)
    finished = datetime.fromisoformat(finished_at_iso)
    return round((finished - started).total_seconds() * 1000)
