import sqlite3
import tempfile
import unittest
from pathlib import Path

from generate_round_housing_quote_history import generate, write_to_db
from quote_lookup import HistoryEstimate, estimate_from_history, find_similar_quotes, load_quotes


class TestGenerate(unittest.TestCase):
    def test_row_count(self):
        rows = generate(num_rows=1000)
        self.assertEqual(len(rows), 1000)

    def test_deterministic_with_seed(self):
        rows_a = generate(num_rows=100, seed=7)
        rows_b = generate(num_rows=100, seed=7)
        self.assertEqual(rows_a, rows_b)

    def test_bigger_housing_trends_more_expensive(self):
        rows = generate(num_rows=1000, seed=1)
        small = [r for r in rows if r["width_in"] <= 1.0]
        big = [r for r in rows if r["width_in"] >= 8.0]
        self.assertTrue(small and big)
        avg_small = sum(r["price"] for r in small) / len(small)
        avg_big = sum(r["price"] for r in big) / len(big)
        self.assertGreater(avg_big, avg_small)

    def test_all_prices_positive(self):
        rows = generate(num_rows=300, seed=3)
        self.assertTrue(all(r["price"] > 0 for r in rows))

    def test_height_matches_fixed_max(self):
        from deep_draw_catalog import ROUND_HOUSINGS
        by_part = {b["part_no"]: b for b in ROUND_HOUSINGS}
        rows = generate(num_rows=200, seed=5)
        for r in rows:
            self.assertEqual(r["height_in"], by_part[r["part_no"]]["height_max_in"])


class TestWriteToDb(unittest.TestCase):
    def test_writes_expected_row_count(self):
        rows = generate(num_rows=50, seed=2)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            write_to_db(rows, db_path)
            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
            conn.close()
            self.assertEqual(count, 50)


class TestQuoteLookup(unittest.TestCase):
    def setUp(self):
        self.quotes = generate(num_rows=1000, seed=42)

    def test_finds_matches_for_sampled_size(self):
        # ~ZR64A (4.00" diameter) -- a real sampled catalog size.
        matches = find_similar_quotes(self.quotes, width_in=4.0, length_in=4.0, height_in=4.5)
        self.assertGreater(len(matches), 0)

    def test_no_matches_returns_none_estimate(self):
        estimate = estimate_from_history(self.quotes, width_in=999, length_in=999, height_in=999)
        self.assertIsNone(estimate)

    def test_estimate_has_positive_price_and_confidence(self):
        estimate = estimate_from_history(self.quotes, width_in=4.0, length_in=4.0, height_in=4.5)
        self.assertIsInstance(estimate, HistoryEstimate)
        self.assertGreater(estimate.avg_price, 0)
        self.assertGreaterEqual(estimate.confidence, 0.0)
        self.assertLessEqual(estimate.confidence, 1.0)

    def test_load_quotes_missing_db_returns_empty(self):
        self.assertEqual(load_quotes(Path("/nonexistent/path.db")), [])


if __name__ == "__main__":
    unittest.main()
