import sqlite3
import tempfile
import unittest
from pathlib import Path

from generate_mini_quote_history import generate, write_to_db
from quote_lookup import HistoryEstimate, estimate_from_history, find_similar_quotes, load_quotes


class TestGenerate(unittest.TestCase):
    def test_row_count(self):
        rows = generate(num_rows=1000)
        self.assertEqual(len(rows), 1000)

    def test_deterministic_with_seed(self):
        rows_a = generate(num_rows=100, seed=7)
        rows_b = generate(num_rows=100, seed=7)
        self.assertEqual(rows_a, rows_b)

    def test_more_draws_trends_more_expensive(self):
        # Unlike the main series, mini-series width/length don't reliably
        # predict price: some very narrow rows have a disproportionately
        # deep max_depth_in, so estimate_num_draws() (deeper relative to
        # opening width = more draw passes) drives labor cost far more
        # than raw size does here. Confirmed on generated data: draws vs.
        # price correlates ~0.85, width*length*height vs. price only ~0.15.
        rows = generate(num_rows=1000, seed=1)
        few_draws = [r for r in rows if r["num_draws"] <= 1]
        many_draws = [r for r in rows if r["num_draws"] >= 5]
        self.assertTrue(few_draws and many_draws)
        avg_few = sum(r["price"] for r in few_draws) / len(few_draws)
        avg_many = sum(r["price"] for r in many_draws) / len(many_draws)
        self.assertGreater(avg_many, avg_few)

    def test_all_prices_positive(self):
        rows = generate(num_rows=300, seed=3)
        self.assertTrue(all(r["price"] > 0 for r in rows))

    def test_height_matches_fixed_max_depth(self):
        # Mini-series has no height range -- every row's height is exactly
        # its own max_depth_in, never randomized.
        from deep_draw_catalog import ZMS_BOXES, ZMR_BOXES
        by_part = {b["part_no"]: b for b in ZMS_BOXES + ZMR_BOXES}
        rows = generate(num_rows=200, seed=5)
        for r in rows:
            self.assertEqual(r["height_in"], by_part[r["part_no"]]["max_depth_in"])


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
        # ~ZMS-100 (1.00 x 1.00) -- a real sampled catalog size.
        matches = find_similar_quotes(self.quotes, width_in=1.0, length_in=1.0, height_in=2.1)
        self.assertGreater(len(matches), 0)

    def test_no_matches_returns_none_estimate(self):
        estimate = estimate_from_history(self.quotes, width_in=999, length_in=999, height_in=999)
        self.assertIsNone(estimate)

    def test_estimate_has_positive_price_and_confidence(self):
        estimate = estimate_from_history(self.quotes, width_in=1.0, length_in=1.0, height_in=2.1)
        self.assertIsInstance(estimate, HistoryEstimate)
        self.assertGreater(estimate.avg_price, 0)
        self.assertGreaterEqual(estimate.confidence, 0.0)
        self.assertLessEqual(estimate.confidence, 1.0)

    def test_load_quotes_missing_db_returns_empty(self):
        self.assertEqual(load_quotes(Path("/nonexistent/path.db")), [])


if __name__ == "__main__":
    unittest.main()
