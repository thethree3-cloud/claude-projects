import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import parse_resume

FAKE_PARSED = {
    "name": "Jordan Rivera",
    "summary": "IT support moving into automation.",
    "location": "Portland, OR",
    "email": "jordan.rivera@example.com",
    "phone": "503-555-0100",
    "links": ["linkedin.com/in/jrivera", "github.com/jrivera-example"],
    "skills": ["Python", "SQL", "pandas"],
    "experience": [
        {
            "title": "IT Support Analyst",
            "organization": "Cascade Precision Manufacturing",
            # fixed end date so the recomputed total is deterministic in tests
            "dates": "Feb 2021 - Feb 2024",
            "highlights": ["Built a pandas reporting pipeline."],
        }
    ],
    "education": [
        {
            "credential": "AAS, Network Administration",
            "institution": "Portland Community College",
            "year": "2019",
        }
    ],
    "certifications": [
        {"name": "CompTIA A+", "issuer": "CompTIA", "year": "2019"},
    ],
    # parse_resume recomputes this from the date ranges above (Feb 2021 → Feb
    # 2024 = 36 months = 3.0); the model's own number here is just a fallback.
    "total_years_experience": 3.0,
}


def _json_response(payload):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


class ParseResumeTests(unittest.TestCase):
    @patch("llm_client.get_client")
    def test_returns_parsed_dict(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(FAKE_PARSED)
        mock_get_client.return_value = mock_client

        result = parse_resume.parse_resume("some resume text")

        self.assertEqual(result, FAKE_PARSED)
        mock_client.messages.create.assert_called_once()

    @patch("llm_client.get_client")
    def test_resume_text_and_schema_are_sent(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(FAKE_PARSED)
        mock_get_client.return_value = mock_client

        parse_resume.parse_resume("UNIQUE-RESUME-MARKER-123")

        _, kwargs = mock_client.messages.create.call_args
        sent_prompt = kwargs["messages"][0]["content"]
        self.assertIn("UNIQUE-RESUME-MARKER-123", sent_prompt)
        schema = kwargs["output_config"]["format"]["schema"]
        self.assertIs(schema, parse_resume.RESUME_SCHEMA)

    @patch("llm_client.get_client")
    def test_total_years_is_recomputed_from_date_ranges(self, mock_get_client):
        payload = {**FAKE_PARSED, "total_years_experience": 99}  # model overshoots
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(payload)
        mock_get_client.return_value = mock_client

        result = parse_resume.parse_resume("x")
        self.assertEqual(result["total_years_experience"], 3.0)  # from the dates

    @patch("llm_client.get_client")
    def test_model_estimate_kept_when_dates_do_not_parse(self, mock_get_client):
        payload = {
            **FAKE_PARSED,
            "total_years_experience": 7,
            "experience": [{**FAKE_PARSED["experience"][0], "dates": ""}],
        }
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(payload)
        mock_get_client.return_value = mock_client

        result = parse_resume.parse_resume("x")
        self.assertEqual(result["total_years_experience"], 7)

    def test_schema_requires_every_top_level_field(self):
        # additionalProperties:False + a full required list is what makes the
        # returned dict safe to index without .get() everywhere downstream.
        self.assertFalse(parse_resume.RESUME_SCHEMA["additionalProperties"])
        self.assertEqual(
            set(parse_resume.RESUME_SCHEMA["required"]),
            set(parse_resume.RESUME_SCHEMA["properties"]),
        )


if __name__ == "__main__":
    unittest.main()
