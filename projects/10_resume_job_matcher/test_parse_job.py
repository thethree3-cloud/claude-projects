import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import parse_job

FAKE_PARSED = {
    "title": "Junior AI Engineer",
    "company": "Northwind Analytics",
    "required_skills": ["Python", "SQL", "REST APIs"],
    "preferred_skills": ["Anthropic API", "MCP", "pandas"],
    "min_years_experience": 2,
    "education_requirement": "Bachelor's in a technical field or equivalent experience",
    "responsibilities": ["Build LLM-backed features", "Structure messy documents"],
}


def _json_response(payload):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


class ParseJobTests(unittest.TestCase):
    @patch("llm_client.get_client")
    def test_returns_parsed_dict(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(FAKE_PARSED)
        mock_get_client.return_value = mock_client

        result = parse_job.parse_job("some job text")

        self.assertEqual(result, FAKE_PARSED)
        mock_client.messages.create.assert_called_once()

    @patch("llm_client.get_client")
    def test_job_text_and_schema_are_sent(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(FAKE_PARSED)
        mock_get_client.return_value = mock_client

        parse_job.parse_job("UNIQUE-JOB-MARKER-456")

        _, kwargs = mock_client.messages.create.call_args
        sent_prompt = kwargs["messages"][0]["content"]
        self.assertIn("UNIQUE-JOB-MARKER-456", sent_prompt)
        self.assertIs(
            kwargs["output_config"]["format"]["schema"], parse_job.JOB_SCHEMA
        )

    def test_schema_separates_required_from_preferred_skills(self):
        props = parse_job.JOB_SCHEMA["properties"]
        self.assertIn("required_skills", props)
        self.assertIn("preferred_skills", props)

    def test_schema_requires_every_top_level_field(self):
        self.assertFalse(parse_job.JOB_SCHEMA["additionalProperties"])
        self.assertEqual(
            set(parse_job.JOB_SCHEMA["required"]),
            set(parse_job.JOB_SCHEMA["properties"]),
        )


if __name__ == "__main__":
    unittest.main()
