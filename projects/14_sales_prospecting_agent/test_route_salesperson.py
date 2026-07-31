import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from route_salesperson import extract_location


class ExtractLocationTests(unittest.TestCase):
    @patch("route_salesperson.get_client")
    def test_parses_state_and_country_from_response(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=json.dumps(
                        {
                            "state": "TX",
                            "country": "United States",
                            "insufficient_information": False,
                        }
                    )
                )
            ]
        )
        mock_get_client.return_value = mock_client

        result = extract_location("Based in Richardson, Texas, United States.")

        self.assertEqual(result["state"], "TX")
        self.assertEqual(result["country"], "United States")
        self.assertFalse(result["insufficient_information"])

    @patch("route_salesperson.get_client")
    def test_insufficient_information_when_text_has_no_location(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=json.dumps(
                        {"state": None, "country": None, "insufficient_information": True}
                    )
                )
            ]
        )
        mock_get_client.return_value = mock_client

        result = extract_location("A company that makes displays.")

        self.assertIsNone(result["state"])
        self.assertIsNone(result["country"])
        self.assertTrue(result["insufficient_information"])


if __name__ == "__main__":
    unittest.main()
