import sqlite3
import unittest

from fastapi.testclient import TestClient

from api import app, get_db
from db import init_schema
from puzzles import today_iso


def make_seeded_connection():
    # check_same_thread=False -- this connection is created in the test's
    # thread but reused across TestClient calls, which FastAPI dispatches
    # into a threadpool. See db.get_connection()'s comment for the full
    # explanation (found via this exact failure while building api.py).
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
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
        "INSERT INTO puzzles (id, category_id, date, answer_movie_id) VALUES "
        "(1, 1, ?, 1)",
        (today_iso(),),
    )
    conn.commit()
    return conn


class BigMoneyMovieAPITests(unittest.TestCase):
    """Exercises api.py's HTTP layer only -- the business logic these
    endpoints call is already covered by test_attempts.py/test_hints.py/
    test_leaderboard.py/test_puzzles.py. What's under test here is
    routing, request/response shape, and error-to-status-code mapping."""

    def setUp(self):
        self.conn = make_seeded_connection()

        def override_get_db():
            # No init_schema/close here -- this is the one shared
            # connection every request in a test reuses, unlike the real
            # get_db which opens/closes a connection per request.
            yield self.conn

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.conn.close()

    def test_health_check(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_category_today_returns_theme_and_pool_size_not_the_pool(self):
        response = self.client.get("/category/today")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["theme"], "Cop Movies")
        self.assertEqual(body["pool_size"], 1)
        self.assertNotIn("title", body)  # never leak the answer here

    def test_category_today_404_when_nothing_scheduled(self):
        self.conn.execute("DELETE FROM puzzles")
        self.conn.commit()

        response = self.client.get("/category/today")

        self.assertEqual(response.status_code, 404)

    def test_full_happy_path_start_wrong_guess_hint_then_correct_guess(self):
        start = self.client.post("/attempt/start", json={"puzzle_id": 1, "player_id": "alan"})
        self.assertEqual(start.status_code, 200)
        attempt_id = start.json()["attempt_id"]

        wrong = self.client.post(
            f"/attempt/{attempt_id}/guess", json={"guess_text": "The Godfather"}
        )
        self.assertEqual(wrong.status_code, 200)
        self.assertFalse(wrong.json()["correct"])
        self.assertEqual(wrong.json()["masked_title"], "_____ _____")

        hint = self.client.post(f"/attempt/{attempt_id}/hint", json={"tier": 3})
        self.assertEqual(hint.status_code, 200)
        self.assertEqual(hint.json()["penalty_ms"], 60_000)
        self.assertIn(hint.json()["masked_title"], ("Dirty _____", "_____ Harry"))

        finish = self.client.post(f"/attempt/{attempt_id}/guess", json={"guess_text": "dirty harry!"})
        self.assertEqual(finish.status_code, 200)
        self.assertTrue(finish.json()["correct"])

        board = self.client.get("/leaderboard/1")
        self.assertEqual(board.status_code, 200)
        rows = board.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["player_id"], "alan")
        self.assertGreaterEqual(rows[0]["final_elapsed_ms"], 60_000)  # includes the hint penalty

    def test_duplicate_attempt_returns_400(self):
        self.client.post("/attempt/start", json={"puzzle_id": 1, "player_id": "alan"})

        response = self.client.post("/attempt/start", json={"puzzle_id": 1, "player_id": "alan"})

        self.assertEqual(response.status_code, 400)

    def test_guess_on_unknown_attempt_returns_400(self):
        response = self.client.post("/attempt/999/guess", json={"guess_text": "Dirty Harry"})
        self.assertEqual(response.status_code, 400)

    def test_hint_with_invalid_tier_returns_400(self):
        start = self.client.post("/attempt/start", json={"puzzle_id": 1, "player_id": "alan"})
        attempt_id = start.json()["attempt_id"]

        response = self.client.post(f"/attempt/{attempt_id}/hint", json={"tier": 7})

        self.assertEqual(response.status_code, 400)

    def test_hint_reused_returns_400(self):
        start = self.client.post("/attempt/start", json={"puzzle_id": 1, "player_id": "alan"})
        attempt_id = start.json()["attempt_id"]
        self.client.post(f"/attempt/{attempt_id}/hint", json={"tier": 1})

        response = self.client.post(f"/attempt/{attempt_id}/hint", json={"tier": 1})

        self.assertEqual(response.status_code, 400)

    def test_leaderboard_empty_when_nobody_finished(self):
        response = self.client.get("/leaderboard/1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_leaderboard_limit_is_respected(self):
        for name in ("a", "b", "c"):
            start = self.client.post("/attempt/start", json={"puzzle_id": 1, "player_id": name})
            attempt_id = start.json()["attempt_id"]
            self.client.post(f"/attempt/{attempt_id}/guess", json={"guess_text": "Dirty Harry"})

        response = self.client.get("/leaderboard/1?limit=2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)


if __name__ == "__main__":
    unittest.main()
