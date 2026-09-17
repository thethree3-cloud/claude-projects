import sqlite3
import tempfile
import unittest
from pathlib import Path

from generate_quote_history import generate, write_to_db
from quote_lookup import (
    HistoryEstimate,
    estimate_from_history,
    find_similar_quotes,
    load_quotes,
)


class TestGenerate(unittest.TestCase):
    def test_row_count(self):
        rows = generate(num_rows=2000)
        self.assertEqual(len(rows), 2000)

    def test_deterministic_with_seed(self):
        rows_a = generate(num_rows=100, seed=7)
        rows_b = generate(num_rows=100, seed=7)
        self.assertEqual(rows_a, rows_b)

    def test_bigger_case_trends_more_expensive(self):
        # Real catalog dimensions span width 4-28.25", length 6-37.25" --
        # these thresholds pick out the small end (AA/AD/AG/AK-ish) and the
        # large end (LN/LV/LY/MB/ME-ish) of that real range.
        rows = generate(num_rows=2000, seed=1)
        small = [r for r in rows if r["width_in"] <= 7 and r["height_in"] <= 9]
        big = [r for r in rows if r["width_in"] >= 20 and r["height_in"] >= 26]
        self.assertTrue(small and big)
        avg_small = sum(r["price"] for r in small) / len(small)
        avg_big = sum(r["price"] for r in big) / len(big)
        self.assertGreater(avg_big, avg_small)

    def test_all_prices_positive(self):
        rows = generate(num_rows=500, seed=3)
        self.assertTrue(all(r["price"] > 0 for r in rows))


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
        self.quotes = generate(num_rows=2000, seed=42)

    def test_finds_matches_for_common_size(self):
        # ~JP case (12x12, 5 draws) -- a real, mid-range catalog size.
        matches = find_similar_quotes(
            self.quotes, width_in=12, height_in=12, depth_in=6, num_draws=5,
        )
        self.assertGreater(len(matches), 0)

    def test_no_matches_returns_none_estimate(self):
        estimate = estimate_from_history(
            self.quotes, width_in=999, height_in=999, depth_in=999, num_draws=6,
        )
        self.assertIsNone(estimate)

    def test_estimate_has_positive_price_and_confidence(self):
        estimate = estimate_from_history(
            self.quotes, width_in=12, height_in=12, depth_in=6, num_draws=5,
        )
        self.assertIsInstance(estimate, HistoryEstimate)
        self.assertGreater(estimate.avg_price, 0)
        self.assertGreaterEqual(estimate.confidence, 0.0)
        self.assertLessEqual(estimate.confidence, 1.0)
        self.assertLessEqual(estimate.min_price, estimate.avg_price)
        self.assertGreaterEqual(estimate.max_price, estimate.avg_price)

    def test_more_matches_gives_higher_confidence(self):
        # The real catalog clusters many sizes in the 7-15" range but only
        # a handful (LA/LV/LY/MB/ME) near the largest end (~27-37").
        sparse = estimate_from_history(
            self.quotes, width_in=27.25, height_in=37.25, depth_in=8, num_draws=12,
        )
        dense = estimate_from_history(
            self.quotes, width_in=9, height_in=9, depth_in=6, num_draws=5,
        )
        self.assertIsNotNone(sparse)
        self.assertIsNotNone(dense)
        self.assertGreaterEqual(dense.confidence, sparse.confidence)

    def test_load_quotes_missing_db_returns_empty(self):
        self.assertEqual(load_quotes(Path("/nonexistent/path.db")), [])


if __name__ == "__main__":
    unittest.main()
