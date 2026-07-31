import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from score_fit import compute_band, compute_score, score_fit

FLAT_SIGNALS = [
    {"industry": "Aerospace & Defense", "term": "MIL-STD-810", "weight": 25},
    {"industry": "Aerospace & Defense", "term": "avionics", "weight": 20},
    {"industry": "Medical Devices", "term": "ISO 13485", "weight": 15},
]

PROFILE = {
    "industries": [
        {
            "name": "Aerospace & Defense",
            "signals": [
                {"term": "MIL-STD-810", "weight": 25},
                {"term": "avionics", "weight": 20},
            ],
        },
        {
            "name": "Medical Devices",
            "signals": [{"term": "ISO 13485", "weight": 15}],
        },
    ]
}


class ComputeScoreTests(unittest.TestCase):
    def test_sums_matched_weights(self):
        self.assertEqual(compute_score(["MIL-STD-810", "avionics"], FLAT_SIGNALS), 45)

    def test_unknown_term_is_ignored(self):
        self.assertEqual(compute_score(["MIL-STD-810", "not-a-real-term"], FLAT_SIGNALS), 25)

    def test_score_caps_at_100(self):
        heavy_signals = [
            {"industry": "X", "term": "a", "weight": 60},
            {"industry": "X", "term": "b", "weight": 60},
        ]
        self.assertEqual(compute_score(["a", "b"], heavy_signals), 100)

    def test_no_matches_scores_zero(self):
        self.assertEqual(compute_score([], FLAT_SIGNALS), 0)


class ComputeBandTests(unittest.TestCase):
    def test_high_band(self):
        self.assertEqual(compute_band(70, False), "High")
        self.assertEqual(compute_band(100, False), "High")

    def test_medium_band(self):
        self.assertEqual(compute_band(40, False), "Medium")
        self.assertEqual(compute_band(69, False), "Medium")

    def test_low_band(self):
        self.assertEqual(compute_band(0, False), "Low")
        self.assertEqual(compute_band(39, False), "Low")

    def test_insufficient_information_overrides_score_to_unknown(self):
        self.assertEqual(compute_band(90, True), "Unknown")


class ScoreFitTests(unittest.TestCase):
    @patch("score_fit.get_client")
    def test_end_to_end_parses_matches_into_scored_result(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=json.dumps(
                        {
                            "matches": [
                                {"term": "MIL-STD-810", "evidence": "rated to MIL-STD-810G"},
                                {"term": "avionics", "evidence": "builds avionics components"},
                            ],
                            "insufficient_information": False,
                        }
                    )
                )
            ]
        )
        mock_get_client.return_value = mock_client

        result = score_fit("Test Co", "some research text", PROFILE)

        self.assertEqual(result["company_name"], "Test Co")
        self.assertEqual(result["score"], 45)
        self.assertEqual(result["band"], "Medium")
        self.assertEqual(len(result["matched_signals"]), 2)
        self.assertIn("MIL-STD-810", result["fit_reason"])

    @patch("score_fit.get_client")
    def test_insufficient_information_yields_unknown_band(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=json.dumps({"matches": [], "insufficient_information": True})
                )
            ]
        )
        mock_get_client.return_value = mock_client

        result = score_fit("Test Co", "vague text", PROFILE)

        self.assertEqual(result["band"], "Unknown")
        self.assertEqual(result["fit_reason"], "Not enough information gathered to judge fit.")


if __name__ == "__main__":
    unittest.main()
