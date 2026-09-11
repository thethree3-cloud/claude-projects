"""SQLite schema + connection helper for Big Money Movie's runtime
gameplay data (categories, category_pool, puzzles, attempts, guesses).
This is the *runtime* store -- curate.py's JSON output is the curation-time
review artifact; loading a reviewed pool into category_pool is a separate
seed step, not built yet (see README). Mirrors Project 11's db.py pattern,
swapped to SQLite for a zero-ops local store.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "big_money_movie.sqlite"

# category_pool's primary key is named movie_id (not the generic "id")
# because puzzles.answer_movie_id references it directly -- naming matches
# the games_track spec's data model. A pool row is one movie *in one
# category's pool*; puzzles point at that specific pool entry, not at a
# separate global movies table.
SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    era TEXT,
    active_date TEXT
);

CREATE TABLE IF NOT EXISTS category_pool (
    movie_id INTEGER PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    imdb_id TEXT,
    title TEXT NOT NULL,
    year INTEGER,
    director TEXT,
    lead_actor TEXT,
    subgenre_tags TEXT,
    word_count INTEGER
);

CREATE TABLE IF NOT EXISTS puzzles (
    id INTEGER PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    date TEXT NOT NULL UNIQUE,
    answer_movie_id INTEGER NOT NULL REFERENCES category_pool(movie_id)
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    puzzle_id INTEGER NOT NULL REFERENCES puzzles(id),
    player_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    guess_count INTEGER NOT NULL DEFAULT 0,
    total_penalty_ms INTEGER NOT NULL DEFAULT 0,
    final_elapsed_ms INTEGER,
    hint1_used INTEGER NOT NULL DEFAULT 0,
    hint1_letter TEXT,
    hint2_used INTEGER NOT NULL DEFAULT 0,
    hint2_letter TEXT,
    hint3_used INTEGER NOT NULL DEFAULT 0,
    hint3_word_index INTEGER,
    UNIQUE(puzzle_id, player_id)
);

CREATE TABLE IF NOT EXISTS guesses (
    id INTEGER PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id),
    guess_text TEXT NOT NULL,
    guessed_at TEXT NOT NULL,
    correct INTEGER NOT NULL
);
"""


def get_connection(db_path=DEFAULT_DB_PATH) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: found via live testing against api.py.
    # FastAPI runs sync `def` endpoints (and their sync dependencies) in a
    # threadpool, and a single request's dependency-open and
    # endpoint-body calls aren't guaranteed to land on the same worker
    # thread -- sqlite3's default thread affinity raised
    # "SQLite objects created in a thread can only be used in that same
    # thread" even though each request already gets its own dedicated
    # connection (opened and closed within get_db(), never shared across
    # requests). This only relaxes same-request cross-thread use; it does
    # not make one connection safe to share concurrently across requests.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


if __name__ == "__main__":
    conn = get_connection()
    init_schema(conn)
    print(f"Schema ready at {DEFAULT_DB_PATH}")
