import sqlite3
import unittest
from unittest.mock import patch

from attempts import start_attempt, submit_guess
from db import init_schema
from hints import HintError, apply_hint


def make_test_db(title="Dirty Harry", word_count=2):
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    conn.execute(
        "INSERT INTO categories (id, name, era, active_date) VALUES "
        "(1, 'Cop Movies', '1970s', '2026-09-11')"
    )
    conn.execute(
        "INSERT INTO category_pool (movie_id, category_id, imdb_id, title, year, "
        "subgenre_tags, word_count) VALUES (1, 1, 'tt0066999', ?, 1971, 'Action,Crime', ?)",
        (title, word_count),
    )
    conn.execute(
        "INSERT INTO puzzles (id, category_id, date, answer_movie_id) VALUES "
        "(1, 1, '2026-09-11', 1)"
    )
    conn.commit()
    return conn


class Tier1VowelTests(unittest.TestCase):
    @patch("hints.random.choice", return_value="a")
    def test_reveals_chosen_vowel_and_charges_penalty(self, mock_choice):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")

        result = apply_hint(conn, attempt_id, tier=1)

        self.assertEqual(result["masked_title"], "_____ _a___")
        self.assertEqual(result["penalty_ms"], 15_000)
        self.assertEqual(result["total_penalty_ms"], 15_000)
        row = conn.execute(
            "SELECT hint1_used, hint1_letter, total_penalty_ms FROM attempts WHERE id = ?",
            (attempt_id,),
        ).fetchone()
        self.assertEqual(row, (1, "a", 15_000))

    def test_only_offers_vowels_actually_in_the_title(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")
        with patch("hints.random.choice") as mock_choice:
            mock_choice.side_effect = lambda candidates: candidates[0]
            apply_hint(conn, attempt_id, tier=1)
        # "Dirty Harry"'s only vowels are i and a.
        mock_choice.assert_called_once()
        (candidates_arg,), _ = mock_choice.call_args
        self.assertEqual(set(candidates_arg), {"i", "a"})

    def test_tier1_reused_raises(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")
        with patch("hints.random.choice", return_value="a"):
            apply_hint(conn, attempt_id, tier=1)
            with self.assertRaises(HintError):
                apply_hint(conn, attempt_id, tier=1)

    def test_no_vowel_in_title_raises_readable_error(self):
        conn = make_test_db(title="Pfft", word_count=1)
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")
        with self.assertRaises(HintError):
            apply_hint(conn, attempt_id, tier=1)


class Tier2ConsonantTests(unittest.TestCase):
    @patch("hints.random.choice", return_value="h")
    def test_reveals_chosen_consonant_and_charges_penalty(self, mock_choice):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")

        result = apply_hint(conn, attempt_id, tier=2)

        self.assertEqual(result["masked_title"], "_____ H____")
        self.assertEqual(result["penalty_ms"], 30_000)
        self.assertEqual(result["total_penalty_ms"], 30_000)

    def test_tier2_reused_raises(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")
        with patch("hints.random.choice", return_value="h"):
            apply_hint(conn, attempt_id, tier=2)
            with self.assertRaises(HintError):
                apply_hint(conn, attempt_id, tier=2)


class Tier3WordTests(unittest.TestCase):
    @patch("hints.random.randrange", return_value=0)
    def test_multiword_title_reveals_whole_word_and_charges_penalty(self, mock_randrange):
        conn = make_test_db()  # "Dirty Harry", word_count=2
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")

        result = apply_hint(conn, attempt_id, tier=3)

        self.assertEqual(result["masked_title"], "Dirty _____")
        self.assertEqual(result["penalty_ms"], 60_000)
        row = conn.execute(
            "SELECT hint3_used, hint3_word_index FROM attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
        self.assertEqual(row, (1, 0))

    def test_single_word_title_falls_back_to_partial_letter_reveal(self):
        conn = make_test_db(title="Chinatown", word_count=1)
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")

        result = apply_hint(conn, attempt_id, tier=3)

        self.assertEqual(result["masked_title"], "China____")
        row = conn.execute(
            "SELECT hint3_used, hint3_word_index FROM attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
        self.assertEqual(row, (1, None))

    def test_tier3_reused_raises(self):
        conn = make_test_db(title="Chinatown", word_count=1)
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")
        apply_hint(conn, attempt_id, tier=3)
        with self.assertRaises(HintError):
            apply_hint(conn, attempt_id, tier=3)


class GeneralHintTests(unittest.TestCase):
    def test_invalid_tier_raises(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")
        with self.assertRaises(HintError):
            apply_hint(conn, attempt_id, tier=4)

    def test_hint_on_unknown_attempt_raises(self):
        conn = make_test_db()
        with self.assertRaises(HintError):
            apply_hint(conn, 999, tier=1)

    def test_hint_on_finished_attempt_raises(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")
        submit_guess(conn, attempt_id, "Dirty Harry")
        with self.assertRaises(HintError):
            apply_hint(conn, attempt_id, tier=1)

    def test_multiple_tiers_accumulate_penalty_and_reveals(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")

        with patch("hints.random.choice", side_effect=["a", "h"]):
            apply_hint(conn, attempt_id, tier=1)
            result = apply_hint(conn, attempt_id, tier=2)

        self.assertEqual(result["total_penalty_ms"], 45_000)
        self.assertEqual(result["masked_title"], "_____ Ha___")

    def test_hint_reveal_persists_across_a_subsequent_wrong_guess(self):
        # Regression coverage: submit_guess's wrong-guess masked_title
        # must reflect hints already used, not reset to a blank mask.
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")
        with patch("hints.random.choice", return_value="a"):
            apply_hint(conn, attempt_id, tier=1)

        result = submit_guess(conn, attempt_id, "The Godfather")

        self.assertFalse(result["correct"])
        self.assertEqual(result["masked_title"], "_____ _a___")

    def test_penalty_folds_into_final_elapsed_ms_via_real_hint_call(self):
        conn = make_test_db()
        attempt_id = start_attempt(conn, puzzle_id=1, player_id="alan")
        with patch("hints.random.choice", return_value="a"):
            apply_hint(conn, attempt_id, tier=1)

        submit_guess(conn, attempt_id, "Dirty Harry")

        final_elapsed_ms, total_penalty_ms = conn.execute(
            "SELECT final_elapsed_ms, total_penalty_ms FROM attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
        self.assertEqual(total_penalty_ms, 15_000)
        self.assertGreaterEqual(final_elapsed_ms, 15_000)


if __name__ == "__main__":
    unittest.main()
