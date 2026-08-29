import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from extract_contact import extract_contact


class ExtractContactTests(unittest.TestCase):
    @patch("extract_contact.get_client")
    def test_parses_named_contact_from_response(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=json.dumps(
                        {
                            "name": "Jordan Reyes",
                            "title": "VP of Sales",
                            "email": "jordan.reyes@example.com",
                            "insufficient_information": False,
                        }
                    )
                )
            ]
        )
        mock_get_client.return_value = mock_client

        result = extract_contact("Contact Jordan Reyes, VP of Sales, at jordan.reyes@example.com.")

        self.assertEqual(result["name"], "Jordan Reyes")
        self.assertEqual(result["title"], "VP of Sales")
        self.assertEqual(result["email"], "jordan.reyes@example.com")
        self.assertFalse(result["insufficient_information"])

    @patch("extract_contact.get_client")
    def test_insufficient_information_when_no_person_named(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=json.dumps(
                        {"name": None, "title": None, "email": None, "insufficient_information": True}
                    )
                )
            ]
        )
        mock_get_client.return_value = mock_client

        result = extract_contact("A company that makes rugged protective cases.")

        self.assertIsNone(result["name"])
        self.assertIsNone(result["title"])
        self.assertIsNone(result["email"])
        self.assertTrue(result["insufficient_information"])


if __name__ == "__main__":
    unittest.main()
