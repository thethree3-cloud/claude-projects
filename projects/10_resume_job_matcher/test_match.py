import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import match

RESUME = {
    "name": "Jordan Rivera",
    "summary": "IT support moving into automation.",
    "location": "Portland, OR",
    "email": "jordan@example.com",
    "phone": "",
    "links": [],
    "skills": ["Python", "SQL", "pandas"],
    "experience": [
        {
            "title": "IT Support Analyst",
            "organization": "Cascade Precision",
            "dates": "2021 - Present",
            "highlights": ["Built a Python + pandas reporting pipeline."],
        }
    ],
    "education": [
        {"credential": "AAS Network Admin", "institution": "PCC", "year": "2019"}
    ],
    "certifications": [
        {"name": "AWS Certified Cloud Practitioner", "issuer": "AWS", "year": "2023"}
    ],
    "total_years_experience": 5,
}

JOB = {
    "title": "Junior AI Engineer",
    "company": "Northwind",
    "required_skills": ["Python", "SQL", "Kubernetes"],
    "preferred_skills": ["pandas", "MCP"],
    "min_years_experience": 2,
    "education_requirement": "Bachelor's or equivalent experience",
    "responsibilities": [],
}


def _json_response(payload):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


class BuildResumeTextTests(unittest.TestCase):
    def test_includes_skills_and_highlights(self):
        text = match.build_resume_text(RESUME)
        self.assertIn("Skills: Python, SQL, pandas", text)
        self.assertIn("- Built a Python + pandas reporting pipeline.", text)
        self.assertIn("IT Support Analyst — Cascade Precision (2021 - Present)", text)

    def test_certifications_are_included_as_evidence(self):
        # a cert names a technology the bullets never mention -> it should still
        # reach the evidence-detection prompt
        text = match.build_resume_text(RESUME)
        self.assertIn("Certifications: AWS Certified Cloud Practitioner", text)


class MatchRequirementsTests(unittest.TestCase):
    def _run(self, mock_get_client, detected):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(detected)
        mock_get_client.return_value = mock_client
        return match.match_requirements(RESUME, JOB)

    @patch("llm_client.get_client")
    def test_met_and_unmet_skill_rows(self, mock_get_client):
        result = self._run(
            mock_get_client,
            {
                "skill_matches": [
                    {"skill": "Python", "evidence": "Built a Python pipeline"},
                    {"skill": "pandas", "evidence": "pandas reporting pipeline"},
                ],
                "education_met": True,
                "education_note": "Associate's + 5 yrs experience counts as equivalent.",
            },
        )

        required = {r["skill"]: r for r in result["required_skills"]}
        self.assertTrue(required["Python"]["met"])
        self.assertEqual(required["Python"]["evidence"], "Built a Python pipeline")
        self.assertFalse(required["SQL"]["met"])
        self.assertFalse(required["Kubernetes"]["met"])

        preferred = {r["skill"]: r for r in result["preferred_skills"]}
        self.assertTrue(preferred["pandas"]["met"])
        self.assertFalse(preferred["MCP"]["met"])

    @patch("llm_client.get_client")
    def test_years_comparison_is_pure_python(self, mock_get_client):
        result = self._run(
            mock_get_client,
            {"skill_matches": [], "education_met": False, "education_note": "no"},
        )
        self.assertEqual(result["years"], {"required": 2, "candidate": 5, "met": True})

    @patch("llm_client.get_client")
    def test_education_passthrough_from_llm(self, mock_get_client):
        result = self._run(
            mock_get_client,
            {"skill_matches": [], "education_met": True, "education_note": "equivalent exp"},
        )
        self.assertTrue(result["education"]["met"])
        self.assertEqual(result["education"]["note"], "equivalent exp")

    @patch("llm_client.get_client")
    def test_enum_is_the_full_job_skill_list(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(
            {"skill_matches": [], "education_met": True, "education_note": "x"}
        )
        mock_get_client.return_value = mock_client

        match.match_requirements(RESUME, JOB)

        _, kwargs = mock_client.messages.create.call_args
        schema = kwargs["output_config"]["format"]["schema"]
        enum = schema["properties"]["skill_matches"]["items"]["properties"]["skill"]["enum"]
        self.assertEqual(enum, ["Python", "SQL", "Kubernetes", "pandas", "MCP"])

    @patch("llm_client.get_client")
    def test_no_named_skills_skips_the_llm_call(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        job = {**JOB, "required_skills": [], "preferred_skills": [], "education_requirement": ""}
        result = match.match_requirements(RESUME, job)

        mock_client.messages.create.assert_not_called()
        self.assertEqual(result["required_skills"], [])
        self.assertTrue(result["education"]["met"])


if __name__ == "__main__":
    unittest.main()
