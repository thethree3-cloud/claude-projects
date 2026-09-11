import sqlite3
import unittest

from imdb_index import lookup, normalize_title


def make_fixture_db():
    """In-memory SQLite matching build_index()'s schema, seeded with a
    handful of hand-picked rows -- no need for the real multi-GB IMDb
    download to test the matching logic."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE titles (tconst TEXT PRIMARY KEY, primary_title TEXT, "
        "normalized_title TEXT, title_type TEXT, start_year INTEGER, genres TEXT)"
    )
    rows = [
        ("tt0066999", "Dirty Harry", normalize_title("Dirty Harry"), "movie", 1971, "Action,Crime,Thriller"),
        # Fictional same-titled entry from a different year, to exercise
        # the closest-year-within-tolerance matching.
        ("tt9999991", "Dirty Harry", normalize_title("Dirty Harry"), "movie", 1978, "Action,Crime"),
        ("tt0070735", "The French Connection", normalize_title("The French Connection"), "movie", 1971, "Action,Crime,Drama"),
        ("tt0110912", "Pulp Fiction", normalize_title("Pulp Fiction"), "movie", 1994, None),
    ]
    conn.executemany("INSERT INTO titles VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return conn


class NormalizeTitleTests(unittest.TestCase):
    def test_lowercases_and_strips_punctuation(self):
        self.assertEqual(normalize_title("Dirty Harry!"), "dirty harry")

    def test_collapses_whitespace(self):
        self.assertEqual(normalize_title("  The   French Connection "), "the french connection")

    def test_ampersand_canonicalizes_to_and(self):
        # Found via live testing: IMDb has the 1975 series as "Starsky and
        # Hutch", Claude proposed "Starsky & Hutch" -- without this the two
        # spellings never matched.
        self.assertEqual(normalize_title("Starsky & Hutch"), normalize_title("Starsky and Hutch"))
        self.assertEqual(normalize_title("Starsky & Hutch"), "starsky and hutch")

    def test_apostrophes_and_hyphens_become_spaces(self):
        self.assertEqual(normalize_title("Ocean's Eleven"), "ocean s eleven")


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_fixture_db()

    def test_finds_exact_year_match(self):
        result = lookup(self.conn, "Dirty Harry", expected_year=1971)
        self.assertIsNotNone(result)
        self.assertEqual(result.tconst, "tt0066999")
        self.assertEqual(result.start_year, 1971)
        self.assertEqual(result.genres, ["Action", "Crime", "Thriller"])

    def test_prefers_closest_year_within_tolerance(self):
        result = lookup(self.conn, "Dirty Harry", expected_year=1979, year_tolerance=2)
        self.assertIsNotNone(result)
        self.assertEqual(result.tconst, "tt9999991")  # 1978 entry, closer than 1971

    def test_rejects_match_outside_year_tolerance(self):
        result = lookup(self.conn, "Dirty Harry", expected_year=2020, year_tolerance=2)
        self.assertIsNone(result)

    def test_ignores_case_and_punctuation_when_matching(self):
        result = lookup(self.conn, "the FRENCH connection!!", expected_year=1971)
        self.assertIsNotNone(result)
        self.assertEqual(result.tconst, "tt0070735")

    def test_returns_none_for_unknown_title(self):
        result = lookup(self.conn, "Some Movie That Does Not Exist", expected_year=1975)
        self.assertIsNone(result)

    def test_missing_genres_returns_empty_list_not_none(self):
        result = lookup(self.conn, "Pulp Fiction", expected_year=1994)
        self.assertEqual(result.genres, [])

    def test_no_expected_year_returns_first_match(self):
        result = lookup(self.conn, "Dirty Harry")
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
