import sqlite3
import unittest

from attempts import AttemptError
from db import init_schema
from puzzles import get_puzzle_by_date, get_todays_puzzle, today_iso


def make_test_db():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    conn.execute(
        "INSERT INTO categories (id, name, era, active_date) VALUES "
        "(1, 'Cop Movies', '1970s', '2026-09-11')"
    )
    conn.execute(
        "INSERT INTO category_pool (movie_id, category_id, imdb_id, title, year, "
        "subgenre_tags, word_count) VALUES (1, 1, 'tt0066999', 'Dirty Harry', 1971, "
        "'Action,Crime', 2)"
    )
    conn.execute(
        "INSERT INTO category_pool (movie_id, category_id, imdb_id, title, year, "
        "subgenre_tags, word_count) VALUES (2, 1, 'tt0067116', 'The French Connection', "
        "1971, 'Action,Crime,Drama', 3)"
    )
    conn.execute(
        "INSERT INTO puzzles (id, category_id, date, answer_movie_id) VALUES "
        "(1, 1, ?, 1)",
        (today_iso(),),
    )
    conn.commit()
    return conn


class GetPuzzleByDateTests(unittest.TestCase):
    def test_returns_theme_era_and_pool_size_not_the_pool_itself(self):
        conn = make_test_db()

        result = get_puzzle_by_date(conn, today_iso())

        self.assertEqual(result["puzzle_id"], 1)
        self.assertEqual(result["theme"], "Cop Movies")
        self.assertEqual(result["era"], "1970s")
        self.assertEqual(result["pool_size"], 2)
        self.assertNotIn("title", result)
        self.assertNotIn("answer_movie_id", result)

    def test_raises_when_no_puzzle_on_that_date(self):
        conn = make_test_db()
        with self.assertRaises(AttemptError):
            get_puzzle_by_date(conn, "1999-01-01")


class GetTodaysPuzzleTests(unittest.TestCase):
    def test_finds_the_puzzle_scheduled_for_today(self):
        conn = make_test_db()
        result = get_todays_puzzle(conn)
        self.assertEqual(result["puzzle_id"], 1)

    def test_raises_when_nothing_scheduled_for_today(self):
        conn = sqlite3.connect(":memory:")
        init_schema(conn)
        with self.assertRaises(AttemptError):
            get_todays_puzzle(conn)


if __name__ == "__main__":
    unittest.main()
