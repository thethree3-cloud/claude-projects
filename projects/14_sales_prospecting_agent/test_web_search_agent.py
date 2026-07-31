import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import web_search_agent


def _text_response(text, stop_reason="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
    )


class SearchTests(unittest.TestCase):
    @patch("web_search_agent.get_client")
    def test_returns_text_from_single_response(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _text_response("Found 3 companies.")
        mock_get_client.return_value = mock_client

        result = web_search_agent.search(
            "manufacturing businesses within 10 miles of Dallas, TX"
        )

        self.assertEqual(result, "Found 3 companies.")
        mock_client.messages.create.assert_called_once()

    @patch("web_search_agent.get_client")
    def test_resends_on_pause_turn_until_end_turn(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _text_response("still searching", stop_reason="pause_turn"),
            _text_response("Final answer.", stop_reason="end_turn"),
        ]
        mock_get_client.return_value = mock_client

        result = web_search_agent.search("Ironclad Avionics Systems")

        self.assertEqual(result, "Final answer.")
        self.assertEqual(mock_client.messages.create.call_count, 2)

    @patch("web_search_agent.get_client")
    def test_stops_after_max_rounds_even_if_still_paused(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _text_response(
            "still going", stop_reason="pause_turn"
        )
        mock_get_client.return_value = mock_client

        result = web_search_agent.search("query")

        self.assertEqual(result, "still going")
        self.assertEqual(
            mock_client.messages.create.call_count, web_search_agent.MAX_TOOL_ROUNDS + 1
        )


if __name__ == "__main__":
    unittest.main()
