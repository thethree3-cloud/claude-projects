import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import report

RESUME = {
    "name": "Jordan Rivera",
    "summary": "IT support moving into automation.",
    "skills": ["Python", "SQL"],
    "experience": [
        {
            "title": "IT Support Analyst",
            "organization": "Cascade Precision",
            "dates": "2021 - Present",
            "highlights": ["Built a Python pipeline."],
        }
    ],
    "education": [{"credential": "AAS", "institution": "PCC", "year": "2019"}],
    "total_years_experience": 3,
}

JOB = {
    "title": "Junior AI Engineer",
    "company": "Northwind",
    "required_skills": ["Python", "Kubernetes"],
    "preferred_skills": ["MCP"],
    "min_years_experience": 5,
    "education_requirement": "Bachelor's",
    "responsibilities": [],
}


def _comparison(required, preferred, years_met, edu_met):
    return {
        "required_skills": [
            {"skill": s, "met": m, "evidence": ""} for s, m in required
        ],
        "preferred_skills": [
            {"skill": s, "met": m, "evidence": ""} for s, m in preferred
        ],
        "years": {"required": 5, "candidate": 3, "met": years_met},
        "education": {"requirement": "Bachelor's", "met": edu_met, "note": "n/a"},
    }


def _json_response(payload):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


COMPARISON_WITH_GAPS = _comparison(
    [("Python", True), ("Kubernetes", False)],
    [("MCP", False)],
    years_met=False,
    edu_met=False,
)


class FindGapsTests(unittest.TestCase):
    def test_extracts_every_kind_of_gap(self):
        gaps = report.find_gaps(COMPARISON_WITH_GAPS)
        self.assertEqual(gaps["unmet_required_skills"], ["Kubernetes"])
        self.assertEqual(gaps["unmet_preferred_skills"], ["MCP"])
        self.assertEqual(gaps["years_short"], {"required": 5, "candidate": 3})
        self.assertTrue(gaps["education_unmet"])

    def test_no_gaps_when_everything_met(self):
        gaps = report.find_gaps(
            _comparison([("Python", True)], [("MCP", True)], True, True)
        )
        self.assertEqual(gaps["unmet_required_skills"], [])
        self.assertIsNone(gaps["years_short"])
        self.assertFalse(gaps["education_unmet"])
        self.assertEqual(report.gap_labels(gaps), [])

    def test_gap_labels_flattens_all_gaps(self):
        self.assertEqual(
            report.gap_labels(report.find_gaps(COMPARISON_WITH_GAPS)),
            ["Kubernetes", "MCP", "years of experience", "education"],
        )


class BuildReportTests(unittest.TestCase):
    @patch("llm_client.get_client")
    def test_calls_llm_and_assembles_report(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(
            {
                "suggestions": [
                    {
                        "gap": "Kubernetes",
                        "assessment": "genuine_gap",
                        "suggestion": "No container-orchestration experience shown; a home lab would help.",
                    }
                ],
                "overall": "Close on fundamentals, short on the cloud-native pieces.",
            }
        )
        mock_get_client.return_value = mock_client

        result = report.build_report(COMPARISON_WITH_GAPS, RESUME, JOB)

        self.assertEqual(result["job_title"], "Junior AI Engineer")
        self.assertEqual(result["company"], "Northwind")
        self.assertIn("score", result)
        self.assertEqual(result["gaps"]["unmet_required_skills"], ["Kubernetes"])
        self.assertEqual(len(result["suggestions"]), 1)
        self.assertEqual(result["overall"], "Close on fundamentals, short on the cloud-native pieces.")

    @patch("llm_client.get_client")
    def test_enum_is_the_gap_labels(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(
            {"suggestions": [], "overall": "x"}
        )
        mock_get_client.return_value = mock_client

        report.build_report(COMPARISON_WITH_GAPS, RESUME, JOB)

        _, kwargs = mock_client.messages.create.call_args
        schema = kwargs["output_config"]["format"]["schema"]
        enum = schema["properties"]["suggestions"]["items"]["properties"]["gap"]["enum"]
        self.assertEqual(enum, ["Kubernetes", "MCP", "years of experience", "education"])

    @patch("llm_client.get_client")
    def test_no_gaps_skips_the_llm_call(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        clean = _comparison([("Python", True)], [("MCP", True)], True, True)
        result = report.build_report(clean, RESUME, JOB)

        mock_client.messages.create.assert_not_called()
        self.assertEqual(result["suggestions"], [])
        self.assertIn("No unmet requirements", result["overall"])


class FormatReportTests(unittest.TestCase):
    def _report(self):
        return {
            "job_title": "Junior AI Engineer",
            "score": 55,
            "band": "Possible",
            "breakdown": [
                {"component": "Required skills", "points": 30.0, "max_points": 60, "detail": "1 of 2 met"},
            ],
            "gaps": report.find_gaps(COMPARISON_WITH_GAPS),
            "suggestions": [
                {"gap": "Kubernetes", "assessment": "genuine_gap", "suggestion": "Build a home lab."}
            ],
            "overall": "Close, but short on cloud-native experience.",
        }

    def test_renders_all_sections(self):
        text = report.format_report(self._report())
        self.assertIn("Junior AI Engineer — 55/100 (Possible)", text)
        self.assertIn("Required, not shown:  Kubernetes", text)
        self.assertIn("Preferred, not shown: MCP", text)
        self.assertIn("Years: 3 vs 5 required", text)
        self.assertIn("Education requirement not met", text)
        self.assertIn("[genuine_gap] Kubernetes", text)
        self.assertIn("Overall: Close, but short on cloud-native experience.", text)

    def test_clean_report_shows_no_gaps(self):
        clean = self._report()
        clean["gaps"] = report.find_gaps(
            _comparison([("Python", True)], [("MCP", True)], True, True)
        )
        clean["suggestions"] = []
        text = report.format_report(clean)
        self.assertIn("  (none)", text)


if __name__ == "__main__":
    unittest.main()
