import sqlite3
import unittest

from attempts import AttemptError, start_attempt, submit_guess
from db import init_schema
from guess_loop import elapsed_ms


def make_test_db():
    """In-memory SQLite, schema only -- no curate.py/IMDb data needed,
    just enough seeded rows to exercise the guess loop."""
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


class StartAttemptTests(unittest.TestCase):
    def test_creates_attempt_with_server_timestamp_and_no_finish_time(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")

        row = conn.execute(
            "SELECT started_at, finished_at, guess_count FROM attempts WHERE id = ?",
            (attempt_id,),
        ).fetchone()
        self.assertIsNotNone(row[0])
        self.assertIsNone(row[1])
        self.assertEqual(row[2], 0)

    def test_second_attempt_same_player_same_puzzle_is_rejected(self):
        conn = make_test_db()
        start_attempt(conn, puzzle_id=1, player_id="alan")

        with self.assertRaises(AttemptError):
            start_attempt(conn, puzzle_id=1, player_id="alan")

    def test_same_player_different_puzzle_is_allowed(self):
        conn = make_test_db()
        conn.execute(
            "INSERT INTO puzzles (id, category_id, date, answer_movie_id) VALUES "
            "(2, 1, '2026-09-12', 1)"
        )
        conn.commit()
        start_attempt(conn, puzzle_id=1, player_id="alan")

        attempt_id_2 = start_attempt(conn, puzzle_id=2, player_id="alan")
        self.assertIsNotNone(attempt_id_2)

    def test_unknown_puzzle_raises_readable_error(self):
        conn = make_test_db()
        with self.assertRaises(AttemptError) as ctx:
            start_attempt(conn, puzzle_id=999, player_id="alan")
        self.assertIn("999", str(ctx.exception))


class SubmitGuessTests(unittest.TestCase):
    def test_correct_guess_finishes_the_attempt(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")

        result = submit_guess(conn, attempt_id, "Dirty Harry")

        self.assertTrue(result["correct"])
        self.assertEqual(result["guess_count"], 1)
        self.assertEqual(result["masked_title"], "Dirty Harry")
        finished_at = conn.execute(
            "SELECT finished_at FROM attempts WHERE id = ?", (attempt_id,)
        ).fetchone()[0]
        self.assertIsNotNone(finished_at)

    def test_wrong_guess_does_not_finish_the_attempt(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")

        result = submit_guess(conn, attempt_id, "The Godfather")

        self.assertFalse(result["correct"])
        self.assertEqual(result["guess_count"], 1)
        self.assertEqual(result["masked_title"], "_____ _____")
        finished_at = conn.execute(
            "SELECT finished_at FROM attempts WHERE id = ?", (attempt_id,)
        ).fetchone()[0]
        self.assertIsNone(finished_at)

    def test_guess_after_attempt_finished_is_rejected(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")
        submit_guess(conn, attempt_id, "Dirty Harry")

        with self.assertRaises(AttemptError):
            submit_guess(conn, attempt_id, "Dirty Harry")

    def test_guess_on_unknown_attempt_raises(self):
        conn = make_test_db()
        with self.assertRaises(AttemptError):
            submit_guess(conn, 999, "Dirty Harry")

    def test_multiple_wrong_guesses_increment_guess_count(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")
        submit_guess(conn, attempt_id, "Wrong One")

        result = submit_guess(conn, attempt_id, "Wrong Two")

        self.assertEqual(result["guess_count"], 2)

    def test_guess_is_logged_in_guesses_table(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")
        submit_guess(conn, attempt_id, "The Godfather")

        rows = conn.execute(
            "SELECT guess_text, correct FROM guesses WHERE attempt_id = ?", (attempt_id,)
        ).fetchall()
        self.assertEqual(rows, [("The Godfather", 0)])


class ScoringTests(unittest.TestCase):
    def test_final_elapsed_ms_set_on_correct_guess(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")

        submit_guess(conn, attempt_id, "Dirty Harry")

        started_at, finished_at, final_elapsed_ms, total_penalty_ms = conn.execute(
            "SELECT started_at, finished_at, final_elapsed_ms, total_penalty_ms "
            "FROM attempts WHERE id = ?",
            (attempt_id,),
        ).fetchone()
        self.assertIsNotNone(final_elapsed_ms)
        self.assertEqual(final_elapsed_ms, elapsed_ms(started_at, finished_at) + total_penalty_ms)
        self.assertGreaterEqual(final_elapsed_ms, 0)

    def test_final_elapsed_ms_folds_in_existing_penalty(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")
        conn.execute("UPDATE attempts SET total_penalty_ms = 15000 WHERE id = ?", (attempt_id,))
        conn.commit()

        submit_guess(conn, attempt_id, "Dirty Harry")

        started_at, finished_at, final_elapsed_ms = conn.execute(
            "SELECT started_at, finished_at, final_elapsed_ms FROM attempts WHERE id = ?",
            (attempt_id,),
        ).fetchone()
        raw_elapsed = elapsed_ms(started_at, finished_at)
        self.assertEqual(final_elapsed_ms, raw_elapsed + 15000)

    def test_final_elapsed_ms_stays_null_on_wrong_guess(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")

        submit_guess(conn, attempt_id, "The Godfather")

        final_elapsed_ms = conn.execute(
            "SELECT final_elapsed_ms FROM attempts WHERE id = ?", (attempt_id,)
        ).fetchone()[0]
        self.assertIsNone(final_elapsed_ms)


if __name__ == "__main__":
    unittest.main()
