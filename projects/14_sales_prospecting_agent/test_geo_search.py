import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from geo_search import extract_company_names_from_text, find_companies_near


def _mock_companies_response(mock_get_client, companies):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(text=json.dumps({"companies": companies}))]
    )
    mock_get_client.return_value = mock_client
    return mock_client


class ExtractCompanyNamesFromTextTests(unittest.TestCase):
    @patch("geo_search.get_client")
    def test_parses_names_from_structured_response(self, mock_get_client):
        _mock_companies_response(
            mock_get_client,
            [
                {"name": "Acme Metal Works", "is_real_prospect_business": True},
                {"name": "Dallas Fab Co", "is_real_prospect_business": True},
            ],
        )

        names = extract_company_names_from_text("some search result text")

        self.assertEqual(names, ["Acme Metal Works", "Dallas Fab Co"])

    @patch("geo_search.get_client")
    def test_dedupes_repeated_names(self, mock_get_client):
        _mock_companies_response(
            mock_get_client,
            [
                {"name": "Acme Metal Works", "is_real_prospect_business": True},
                {"name": "Acme Metal Works", "is_real_prospect_business": True},
            ],
        )

        names = extract_company_names_from_text("some search result text")

        self.assertEqual(names, ["Acme Metal Works"])

    @patch("geo_search.get_client")
    def test_no_names_found_returns_empty_list(self, mock_get_client):
        _mock_companies_response(mock_get_client, [])

        self.assertEqual(extract_company_names_from_text("no companies here"), [])

    @patch("geo_search.get_client")
    def test_non_prospect_entities_are_filtered_out(self, mock_get_client):
        # Regression test: a live run against Dallas, TX returned "Yelp" and
        # "Dallas Chamber of Commerce" as if they were leads -- real names
        # in the search text, but a review site and a trade association,
        # not actual prospect businesses.
        _mock_companies_response(
            mock_get_client,
            [
                {"name": "Acme Metal Works", "is_real_prospect_business": True},
                {"name": "Yelp", "is_real_prospect_business": False},
                {"name": "Dallas Chamber of Commerce", "is_real_prospect_business": False},
            ],
        )

        names = extract_company_names_from_text("some search result text")

        self.assertEqual(names, ["Acme Metal Works"])


class FindCompaniesNearTests(unittest.TestCase):
    @patch("geo_search.extract_company_names_from_text")
    @patch("geo_search.search")
    def test_searches_then_extracts(self, mock_search, mock_extract):
        mock_search.return_value = "raw search result text"
        mock_extract.return_value = ["Acme Metal Works"]

        names = find_companies_near("manufacturing businesses within 10 miles of Dallas, TX")

        mock_search.assert_called_once_with(
            "manufacturing businesses within 10 miles of Dallas, TX"
        )
        mock_extract.assert_called_once_with("raw search result text")
        self.assertEqual(names, ["Acme Metal Works"])


if __name__ == "__main__":
    unittest.main()
