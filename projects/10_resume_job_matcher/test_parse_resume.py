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
            "dates": "Feb 2021 - Present",
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
    "total_years_experience": 5,
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
