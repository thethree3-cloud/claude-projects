import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pipeline

RESUME_JSON = {
    "name": "Jordan Rivera",
    "summary": "IT support moving into automation.",
    "location": "Portland, OR",
    "email": "jordan@example.com",
    "phone": "",
    "links": ["github.com/jrivera"],
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
    "certifications": [{"name": "CompTIA A+", "issuer": "CompTIA", "year": "2019"}],
    "total_years_experience": 5,
}

JOB_JSON = {
    "title": "Junior AI Engineer",
    "company": "Northwind",
    "required_skills": ["Python", "Kubernetes"],
    "preferred_skills": ["MCP"],
    "min_years_experience": 2,
    "education_requirement": "Bachelor's",
    "responsibilities": [],
}

SKILL_EVIDENCE_JSON = {
    "skill_matches": [{"skill": "Python", "evidence": "Built a Python pipeline."}],
    "education_met": True,
    "education_note": "Equivalent experience.",
}

SUGGESTIONS_JSON = {
    "suggestions": [
        {
            "gap": "Kubernetes",
            "assessment": "genuine_gap",
            "suggestion": "No container experience shown; try a home lab.",
        }
    ],
    "overall": "Strong fundamentals, missing cloud-native depth.",
}


def _json_response(payload):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


class EvaluateFitTests(unittest.TestCase):
    @patch("llm_client.get_client")
    def test_chains_parse_match_report_into_one_report(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _json_response(RESUME_JSON),
            _json_response(JOB_JSON),
            _json_response(SKILL_EVIDENCE_JSON),
            _json_response(SUGGESTIONS_JSON),
        ]
        mock_get_client.return_value = mock_client

        report = pipeline.evaluate_fit("résumé text", "job text")

        self.assertEqual(mock_client.messages.create.call_count, 4)
        self.assertEqual(report["job_title"], "Junior AI Engineer")
        self.assertEqual(report["company"], "Northwind")
        self.assertEqual(report["gaps"]["unmet_required_skills"], ["Kubernetes"])
        self.assertEqual(len(report["suggestions"]), 1)
        self.assertEqual(report["overall"], "Strong fundamentals, missing cloud-native depth.")

    @patch("llm_client.get_client")
    def test_score_reflects_the_single_matched_required_skill(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _json_response(RESUME_JSON),
            _json_response(JOB_JSON),
            _json_response(SKILL_EVIDENCE_JSON),
            _json_response(SUGGESTIONS_JSON),
        ]
        mock_get_client.return_value = mock_client

        report = pipeline.evaluate_fit("r", "j")

        # required 1/2 -> 30, years met -> 20, preferred 0/1 -> 0, education -> 5
        self.assertEqual(report["score"], 55)
        self.assertEqual(report["band"], "Possible")


class RankFitsTests(unittest.TestCase):
    def test_orders_by_score_descending(self):
        reports = [{"score": 40, "n": "a"}, {"score": 90, "n": "b"}, {"score": 65, "n": "c"}]
        self.assertEqual([r["n"] for r in pipeline.rank_fits(reports)], ["b", "c", "a"])

    def test_is_stable_on_ties(self):
        reports = [{"score": 50, "n": "a"}, {"score": 50, "n": "b"}, {"score": 50, "n": "c"}]
        self.assertEqual([r["n"] for r in pipeline.rank_fits(reports)], ["a", "b", "c"])

    def test_does_not_mutate_input(self):
        reports = [{"score": 10}, {"score": 20}]
        pipeline.rank_fits(reports)
        self.assertEqual([r["score"] for r in reports], [10, 20])


if __name__ == "__main__":
    unittest.main()
