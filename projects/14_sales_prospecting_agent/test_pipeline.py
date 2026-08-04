import unittest
from unittest.mock import patch

from extract_exhibitor_profiles import build_profile_lookup
from generate_sample_data import (
    DATA_DIR,
    write_sample_client_profile,
    write_sample_territory_routing,
)
from pipeline import WEB_SEARCH_SOURCE, evaluate_lead


class EvaluateLeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        write_sample_client_profile()
        write_sample_territory_routing()
        cls.client_profile_path = DATA_DIR / "sample_client_profile.yaml"
        cls.territory_routing_path = DATA_DIR / "sample_territory_routing.csv"

    def _fake_fit_result(self, company_name, research_text, profile):
        return {"company_name": company_name, "score": 50, "band": "Medium"}

    def _fake_location(self, research_text):
        return {"state": None, "country": None, "insufficient_information": True}

    def _fake_routing(self, location, territory_rows):
        return {"salesperson_name": "Needs Review", "email": None, "territory": None, "assignment_reason": "test"}

    @patch("pipeline.search")
    @patch("pipeline.route_salesperson")
    @patch("pipeline.extract_location")
    @patch("pipeline.score_fit")
    def test_matched_profile_used_as_research_text_instead_of_search(
        self, mock_score_fit, mock_extract_location, mock_route_salesperson, mock_search
    ):
        mock_score_fit.side_effect = self._fake_fit_result
        mock_extract_location.side_effect = self._fake_location
        mock_route_salesperson.side_effect = self._fake_routing

        profiles = [
            {
                "name": "Acme Mills Company",
                "description": "Acme Mills is a textile maker.",
                "website": "https://www.acmemills.example/",
                "booth": "2013",
                "source": "expo.pdf page 5",
            }
        ]
        lookup = build_profile_lookup(profiles)

        result = evaluate_lead(
            "Acme Mills Company",
            self.client_profile_path,
            self.territory_routing_path,
            exhibitor_profiles=lookup,
        )

        mock_search.assert_not_called()
        self.assertEqual(result["source"], "expo.pdf page 5")
        research_text_used = mock_score_fit.call_args[0][1]
        self.assertIn("Acme Mills is a textile maker.", research_text_used)
        self.assertIn("https://www.acmemills.example/", research_text_used)

    @patch("pipeline.search")
    @patch("pipeline.route_salesperson")
    @patch("pipeline.extract_location")
    @patch("pipeline.score_fit")
    def test_unmatched_company_falls_back_to_web_search(
        self, mock_score_fit, mock_extract_location, mock_route_salesperson, mock_search
    ):
        mock_search.return_value = "Some live search result text."
        mock_score_fit.side_effect = self._fake_fit_result
        mock_extract_location.side_effect = self._fake_location
        mock_route_salesperson.side_effect = self._fake_routing

        result = evaluate_lead(
            "Some Other Company",
            self.client_profile_path,
            self.territory_routing_path,
            exhibitor_profiles={},
        )

        mock_search.assert_called_once_with("Some Other Company")
        self.assertEqual(result["source"], WEB_SEARCH_SOURCE)
        research_text_used = mock_score_fit.call_args[0][1]
        self.assertEqual(research_text_used, "Some live search result text.")

    @patch("pipeline.search")
    @patch("pipeline.route_salesperson")
    @patch("pipeline.extract_location")
    @patch("pipeline.score_fit")
    def test_no_exhibitor_profiles_argument_defaults_to_search(
        self, mock_score_fit, mock_extract_location, mock_route_salesperson, mock_search
    ):
        mock_search.return_value = "Some live search result text."
        mock_score_fit.side_effect = self._fake_fit_result
        mock_extract_location.side_effect = self._fake_location
        mock_route_salesperson.side_effect = self._fake_routing

        result = evaluate_lead(
            "Any Company", self.client_profile_path, self.territory_routing_path
        )

        mock_search.assert_called_once_with("Any Company")
        self.assertEqual(result["source"], WEB_SEARCH_SOURCE)


if __name__ == "__main__":
    unittest.main()
