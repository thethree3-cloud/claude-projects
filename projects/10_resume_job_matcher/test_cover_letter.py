import datetime
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cover_letter

RESUME = {
    "name": "Jordan Rivera",
    "summary": "IT support moving into automation.",
    "location": "Portland, OR",
    "email": "jordan@example.com",
    "phone": "503-555-0100",
    "links": ["github.com/jrivera"],
    "skills": ["Python", "SQL", "pandas"],
    "experience": [
        {
            "title": "IT Support Analyst",
            "organization": "Cascade Precision",
            "dates": "2021 - Present",
            "highlights": ["Built a Python + pandas reporting pipeline."],
        }
    ],
    "education": [{"credential": "AAS", "institution": "PCC", "year": "2019"}],
    "certifications": [],
    "total_years_experience": 5,
}

JOB = {
    "title": "Junior Data Analyst",
    "company": "Northwind",
    "required_skills": ["Python", "SQL"],
    "preferred_skills": ["pandas"],
    "min_years_experience": 2,
    "education_requirement": "",
    "responsibilities": ["Build reporting pipelines"],
}

COMPARISON = {
    "required_skills": [
        {"skill": "Python", "met": True, "evidence": "Built a Python + pandas reporting pipeline."},
        {"skill": "SQL", "met": False, "evidence": ""},
    ],
    "preferred_skills": [
        {"skill": "pandas", "met": True, "evidence": "Built a Python + pandas reporting pipeline."},
    ],
    "years": {"required": 2, "candidate": 5, "met": True},
    "education": {"requirement": "", "met": True, "note": "n/a"},
}

LETTER = {
    "greeting": "Dear Hiring Manager,",
    "paragraphs": [
        "I'm applying for the Junior Data Analyst role at Northwind.",
        "At Cascade Precision I built a Python and pandas reporting pipeline.",
        "I'd welcome the chance to talk.",
    ],
    "signoff": "Sincerely,",
    "claims": [
        {"claim": "Built a Python and pandas reporting pipeline", "evidence": "Built a Python + pandas reporting pipeline."},
        {"claim": "Five years supporting a manufacturing office", "evidence": "IT support moving into automation."},
    ],
}


def _json_response(payload):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


class WriteCoverLetterTests(unittest.TestCase):
    @patch("llm_client.get_client")
    def test_prompt_carries_evidence_and_gaps(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(LETTER)
        mock_get_client.return_value = mock_client

        cover_letter.write_cover_letter(RESUME, JOB, COMPARISON)

        _, kwargs = mock_client.messages.create.call_args
        prompt = kwargs["messages"][0]["content"]
        self.assertIn('Python: "Built a Python + pandas reporting pipeline."', prompt)
        self.assertIn("DOES NOT DEMONSTRATE:\nSQL", prompt)  # the unmet required skill
        self.assertIn("Jordan Rivera", prompt)

    @patch("llm_client.get_client")
    def test_returns_the_parsed_letter(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(LETTER)
        mock_get_client.return_value = mock_client
        out = cover_letter.write_cover_letter(RESUME, JOB, COMPARISON)
        self.assertEqual(out, LETTER)


class VerifyClaimsTests(unittest.TestCase):
    @patch("llm_client.get_client")
    def test_enum_covers_every_claim_index(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response({"unsupported": []})
        mock_get_client.return_value = mock_client

        cover_letter.verify_claims(LETTER, RESUME)

        _, kwargs = mock_client.messages.create.call_args
        prompt = kwargs["messages"][0]["content"]
        self.assertIn("[0] Built a Python and pandas reporting pipeline", prompt)
        enum = kwargs["output_config"]["format"]["schema"]["properties"][
            "unsupported"
        ]["items"]["properties"]["claim_index"]["enum"]
        self.assertEqual(enum, [0, 1])

    def test_no_claims_skips_the_call(self):
        out = cover_letter.verify_claims({**LETTER, "claims": []}, RESUME)
        self.assertEqual(out, {"unsupported": []})


class FlagUnsupportedTests(unittest.TestCase):
    def test_maps_indices_to_claim_text(self):
        flags = cover_letter._flag_unsupported(
            LETTER, [{"claim_index": 1, "issue": "résumé doesn't say five years"}]
        )
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["claim"], "Five years supporting a manufacturing office")
        self.assertIn("five years", flags[0]["issue"])

    def test_out_of_range_index_ignored(self):
        self.assertEqual(
            cover_letter._flag_unsupported(LETTER, [{"claim_index": 9, "issue": "x"}]),
            [],
        )


class RenderTextTests(unittest.TestCase):
    def test_assembles_header_body_signoff(self):
        text = cover_letter.render_text(
            LETTER, RESUME, JOB, today=datetime.date(2026, 8, 29)
        )
        self.assertTrue(text.startswith("Jordan Rivera\n"))
        self.assertIn("Portland, OR  |  jordan@example.com", text)
        self.assertIn("August 29, 2026", text)
        self.assertIn("Dear Hiring Manager,", text)
        self.assertIn("At Cascade Precision I built", text)
        self.assertIn("Sincerely,\nJordan Rivera\n", text)


class BuildCoverLetterTests(unittest.TestCase):
    @patch("llm_client.get_client")
    def test_two_calls_and_shape(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _json_response(LETTER),
            _json_response({"unsupported": []}),
        ]
        mock_get_client.return_value = mock_client

        out = cover_letter.build_cover_letter(COMPARISON, RESUME, JOB)

        self.assertEqual(set(out), {"text", "paragraphs", "greeting", "claims", "flags"})
        self.assertEqual(out["flags"], [])
        self.assertEqual(mock_client.messages.create.call_count, 2)

    @patch("llm_client.get_client")
    def test_verify_false_skips_audit(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(LETTER)
        mock_get_client.return_value = mock_client

        out = cover_letter.build_cover_letter(COMPARISON, RESUME, JOB, verify=False)

        self.assertEqual(mock_client.messages.create.call_count, 1)
        self.assertEqual(out["flags"], [])

    @patch("llm_client.get_client")
    def test_unsupported_claim_is_flagged_not_removed(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _json_response(LETTER),
            _json_response(
                {"unsupported": [{"claim_index": 1, "issue": "no five-year claim in résumé"}]}
            ),
        ]
        mock_get_client.return_value = mock_client

        out = cover_letter.build_cover_letter(COMPARISON, RESUME, JOB)

        self.assertEqual(len(out["flags"]), 1)
        # prose is untouched — all three paragraphs still there
        self.assertEqual(len(out["paragraphs"]), 3)


if __name__ == "__main__":
    unittest.main()
