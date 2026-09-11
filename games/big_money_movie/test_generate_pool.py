import sqlite3
import unittest
from unittest.mock import patch

from generate_pool import (
    extract_json,
    generate_category_pool,
    ground_candidates,
    propose_candidates,
)
from imdb_index import normalize_title


def make_fixture_db():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE titles (tconst TEXT PRIMARY KEY, primary_title TEXT, "
        "normalized_title TEXT, title_type TEXT, start_year INTEGER, genres TEXT)"
    )
    conn.execute(
        "INSERT INTO titles VALUES (?,?,?,?,?,?)",
        ("tt0066999", "Dirty Harry", normalize_title("Dirty Harry"), "movie", 1971, "Action,Crime,Thriller"),
    )
    conn.commit()
    return conn


class ExtractJSONTests(unittest.TestCase):
    def test_plain_json_passes_through(self):
        self.assertEqual(extract_json('[{"title": "X"}]'), '[{"title": "X"}]')

    def test_strips_json_fenced_block(self):
        raw = '```json\n[{"title": "X"}]\n```'
        self.assertEqual(extract_json(raw), '[{"title": "X"}]')

    def test_strips_bare_fenced_block(self):
        raw = '```\n[{"title": "X"}]\n```'
        self.assertEqual(extract_json(raw), '[{"title": "X"}]')

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(extract_json('\n\n  [{"title": "X"}]  \n\n'), '[{"title": "X"}]')


class GroundCandidatesTests(unittest.TestCase):
    """ground_candidates never calls Claude -- pure verification logic
    against a fixture IMDb index."""

    def setUp(self):
        self.conn = make_fixture_db()

    def test_known_title_is_grounded_with_canonical_data(self):
        raw = [{"title": "Dirty Harry", "year": 1971}]
        results = ground_candidates(raw, self.conn)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].grounded)
        self.assertEqual(results[0].imdb_id, "tt0066999")
        self.assertEqual(results[0].canonical_title, "Dirty Harry")
        self.assertEqual(results[0].genres, ["Action", "Crime", "Thriller"])
        self.assertEqual(results[0].word_count, 2)
        self.assertIsNone(results[0].rejection_reason)

    def test_hallucinated_title_is_not_grounded(self):
        raw = [{"title": "Totally Made Up Cop Movie", "year": 1975}]
        results = ground_candidates(raw, self.conn)

        self.assertFalse(results[0].grounded)
        self.assertIsNotNone(results[0].rejection_reason)
        self.assertIsNone(results[0].imdb_id)

    def test_right_title_wrong_decade_is_not_grounded(self):
        # Same title text but a proposed year far outside tolerance --
        # e.g. Claude claiming a 1971 film is from the 2020s.
        raw = [{"title": "Dirty Harry", "year": 2021}]
        results = ground_candidates(raw, self.conn)

        self.assertFalse(results[0].grounded)

    def test_mixed_batch_grounded_and_rejected(self):
        raw = [
            {"title": "Dirty Harry", "year": 1971},
            {"title": "Not A Real Movie", "year": 1975},
        ]
        results = ground_candidates(raw, self.conn)

        self.assertTrue(results[0].grounded)
        self.assertFalse(results[1].grounded)


class _FakeContentBlock:
    def __init__(self, text):
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeContentBlock(text)]


class _FakeMessages:
    def __init__(self, text):
        self._text = text

    def create(self, **kwargs):
        return _FakeResponse(self._text)


class _FakeAnthropic:
    def __init__(self, text):
        self.messages = _FakeMessages(text)


class ProposeCandidatesTests(unittest.TestCase):
    """No real Anthropic call -- a fake client stands in, same idea as
    Project 11's mocked generate_sql tests."""

    def test_parses_plain_json_response(self):
        fake = _FakeAnthropic('[{"title": "Dirty Harry", "year": 1971}]')
        result = propose_candidates("Cop Movies", 1970, 1979, count=1, client=fake)
        self.assertEqual(result, [{"title": "Dirty Harry", "year": 1971}])

    def test_parses_code_fenced_response(self):
        fake = _FakeAnthropic('```json\n[{"title": "Dirty Harry", "year": 1971}]\n```')
        result = propose_candidates("Cop Movies", 1970, 1979, count=1, client=fake)
        self.assertEqual(result, [{"title": "Dirty Harry", "year": 1971}])


class GenerateCategoryPoolTests(unittest.TestCase):
    """Mocks propose_candidates (the LLM call) and points ground_candidates
    at a fixture index, mirroring how test_run_report.py mocks generate_sql
    rather than the raw Anthropic client."""

    @patch("generate_pool.propose_candidates")
    def test_chains_propose_and_ground(self, mock_propose):
        mock_propose.return_value = [{"title": "Dirty Harry", "year": 1971}]
        conn = make_fixture_db()
        db_path = ":memory:"

        with patch("generate_pool.sqlite3.connect", return_value=conn):
            results = generate_category_pool(
                "Cop Movies", 1970, 1979, count=1, index_path=__file__  # any existing path
            )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].grounded)
        mock_propose.assert_called_once_with("Cop Movies", 1970, 1979, count=1, client=None)

    def test_missing_index_raises_readable_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            generate_category_pool(
                "Cop Movies", 1970, 1979, index_path="/nonexistent/path/imdb_index.sqlite"
            )
        self.assertIn("imdb_index.py --build", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
