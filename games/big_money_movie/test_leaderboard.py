import sqlite3
import unittest

from attempts import start_attempt
from db import init_schema
from leaderboard import get_leaderboard


def make_test_db():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    conn.execute(
        "INSERT INTO categories (id, name, era, active_date) VALUES "
        "(1, 'Cop Movies', '1970s', '2026-09-11')"
    )
    conn.execute(
        "INSERT INTO category_pool (movie_id, category_id, imdb_id, title, year, "
        "subgenre_tags, word_count) VALUES "
        "(1, 1, 'tt0066999', 'Dirty Harry', 1971, 'Action,Crime,Thriller', 2)"
    )
    conn.execute(
        "INSERT INTO puzzles (id, category_id, date, answer_movie_id) VALUES "
        "(1, 1, '2026-09-11', 1)"
    )
    conn.commit()
    return conn


def finish_attempt(conn, player_id, final_elapsed_ms, guess_count=1,
                    finished_at="2026-09-11T12:00:00+00:00", puzzle_id=1):
    """Directly seed a finished attempt with a chosen score, bypassing
    submit_guess -- ordering tests care about comparing many pre-set
    scores, not re-deriving timing math (that's test_attempts.py's job)."""
    conn.execute(
        "INSERT INTO attempts (puzzle_id, player_id, started_at, finished_at, guess_count, "
        "total_penalty_ms, final_elapsed_ms) VALUES (?, ?, '2026-09-11T11:00:00+00:00', ?, ?, 0, ?)",
        (puzzle_id, player_id, finished_at, guess_count, final_elapsed_ms),
    )
    conn.commit()


class GetLeaderboardTests(unittest.TestCase):
    def test_orders_fastest_first(self):
        conn = make_test_db()
        finish_attempt(conn, "slow", 9000)
        finish_attempt(conn, "fast", 3000)
        finish_attempt(conn, "mid", 6000)

        board = get_leaderboard(conn, puzzle_id=1)

        self.assertEqual([row["player_id"] for row in board], ["fast", "mid", "slow"])
        self.assertEqual([row["rank"] for row in board], [1, 2, 3])

    def test_ties_break_on_fewer_guesses(self):
        conn = make_test_db()
        finish_attempt(conn, "many_guesses", 5000, guess_count=4)
        finish_attempt(conn, "few_guesses", 5000, guess_count=1)

        board = get_leaderboard(conn, puzzle_id=1)

        self.assertEqual([row["player_id"] for row in board], ["few_guesses", "many_guesses"])

    def test_unfinished_attempts_are_excluded(self):
        conn = make_test_db()
        start_attempt(conn, puzzle_id=1, player_id="still_playing")
        finish_attempt(conn, "done", 5000)

        board = get_leaderboard(conn, puzzle_id=1)

        self.assertEqual([row["player_id"] for row in board], ["done"])

    def test_limit_truncates_results(self):
        conn = make_test_db()
        for i in range(5):
            finish_attempt(conn, f"player{i}", 1000 * i)

        board = get_leaderboard(conn, puzzle_id=1, limit=2)

        self.assertEqual([row["player_id"] for row in board], ["player0", "player1"])

    def test_empty_leaderboard_for_puzzle_with_no_finishers(self):
        conn = make_test_db()
        self.assertEqual(get_leaderboard(conn, puzzle_id=1), [])

    def test_only_includes_the_requested_puzzle(self):
        conn = make_test_db()
        conn.execute(
            "INSERT INTO puzzles (id, category_id, date, answer_movie_id) VALUES "
            "(2, 1, '2026-09-12', 1)"
        )
        conn.commit()
        finish_attempt(conn, "puzzle1_player", 4000, puzzle_id=1)
        finish_attempt(conn, "puzzle2_player", 1000, puzzle_id=2)

        board = get_leaderboard(conn, puzzle_id=1)

        self.assertEqual([row["player_id"] for row in board], ["puzzle1_player"])


if __name__ == "__main__":
    unittest.main()
