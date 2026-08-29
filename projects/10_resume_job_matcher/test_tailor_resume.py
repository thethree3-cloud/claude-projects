import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import tailor_resume

RESUME = {
    "name": "Jordan Rivera",
    "summary": "IT support moving into automation.",
    "location": "Portland, OR",
    "email": "jordan.rivera@example.com",
    "phone": "503-555-0100",
    "links": ["github.com/jrivera-example"],
    "skills": ["Python", "SQL", "pandas", "Excel"],
    "experience": [
        {
            "title": "IT Support Analyst",
            "organization": "Cascade Precision",
            "dates": "2021 - Present",
            "highlights": ["Built a pandas reporting pipeline.", "Ran the help desk."],
        },
        {
            "title": "Bookkeeper",
            "organization": "Rose City Coffee",
            "dates": "2018 - 2021",
            "highlights": ["Reconciled monthly accounts in Excel."],
        },
    ],
    "education": [
        {"credential": "AAS, Network Administration", "institution": "PCC", "year": "2019"}
    ],
    "certifications": [
        {"name": "CompTIA A+", "issuer": "CompTIA", "year": "2019"},
        {"name": "Azure Fundamentals", "issuer": "Microsoft", "year": "2022"},
    ],
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
        {"skill": "Python", "met": True, "evidence": "Built a pandas reporting pipeline."},
        {"skill": "SQL", "met": False, "evidence": ""},
    ],
    "preferred_skills": [
        {"skill": "pandas", "met": True, "evidence": "Built a pandas reporting pipeline."},
    ],
    "years": {"required": 2, "candidate": 5, "met": True},
    "education": {"requirement": "", "met": True, "note": "n/a"},
}

TAILORED = {
    "summary": "Analyst who builds Python reporting pipelines.",
    "skills": ["Python", "pandas", "SQL", "Excel"],
    "experience": [
        {"source_index": 0, "highlights": ["Built Python/pandas reporting pipelines."]},
        {"source_index": 1, "highlights": ["Reconciled monthly accounts."]},
    ],
    "changes": ["Rewrote the summary.", "Led with the analyst role."],
}


def _json_response(payload):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


class TailorResumeCallTests(unittest.TestCase):
    @patch("llm_client.get_client")
    def test_sends_numbered_resume_and_schema(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(TAILORED)
        mock_get_client.return_value = mock_client

        tailor_resume.tailor_resume(RESUME, JOB, COMPARISON)

        _, kwargs = mock_client.messages.create.call_args
        prompt = kwargs["messages"][0]["content"]
        self.assertIn("[0] IT Support Analyst — Cascade Precision", prompt)
        self.assertIn("[1] Bookkeeper — Rose City Coffee", prompt)
        # the evidence quote for a met skill is handed to the model
        self.assertIn('Python: "Built a pandas reporting pipeline."', prompt)
        # contact + certs are visible to the model (it won't change them, but
        # it shouldn't drop them either)
        self.assertIn("jordan.rivera@example.com", prompt)
        self.assertIn("CompTIA A+ — CompTIA (2019)", prompt)

        schema = kwargs["output_config"]["format"]["schema"]
        self.assertEqual(
            schema["properties"]["skills"]["items"]["enum"],
            ["Python", "SQL", "pandas", "Excel"],
        )
        self.assertEqual(
            schema["properties"]["experience"]["items"]["properties"]["source_index"][
                "enum"
            ],
            [0, 1],
        )

    @patch("llm_client.get_client")
    def test_empty_skills_still_makes_a_valid_enum(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(TAILORED)
        mock_get_client.return_value = mock_client

        no_skills = {**RESUME, "skills": []}
        tailor_resume.tailor_resume(no_skills, JOB, COMPARISON)

        _, kwargs = mock_client.messages.create.call_args
        enum = kwargs["output_config"]["format"]["schema"]["properties"]["skills"][
            "items"
        ]["enum"]
        self.assertTrue(enum)  # never an empty enum (invalid JSON schema)


class AssembleTests(unittest.TestCase):
    def test_locks_title_org_dates_to_source_role(self):
        tampered = {
            **TAILORED,
            "experience": [
                {
                    "source_index": 0,
                    "highlights": ["Reworded bullet."],
                }
            ],
        }
        out = tailor_resume.assemble(tampered, RESUME)
        role = out["experience"][0]
        self.assertEqual(role["title"], "IT Support Analyst")
        self.assertEqual(role["organization"], "Cascade Precision")
        self.assertEqual(role["dates"], "2021 - Present")
        self.assertEqual(role["highlights"], ["Reworded bullet."])

    def test_dropped_role_is_reappended_untouched(self):
        only_first = {
            **TAILORED,
            "experience": [{"source_index": 0, "highlights": ["x"]}],
        }
        out = tailor_resume.assemble(only_first, RESUME)
        self.assertEqual(len(out["experience"]), 2)
        self.assertEqual(out["experience"][1]["organization"], "Rose City Coffee")
        self.assertEqual(
            out["experience"][1]["highlights"],
            ["Reconciled monthly accounts in Excel."],
        )

    def test_reorders_roles(self):
        reordered = {
            **TAILORED,
            "experience": [
                {"source_index": 1, "highlights": ["a"]},
                {"source_index": 0, "highlights": ["b"]},
            ],
        }
        out = tailor_resume.assemble(reordered, RESUME)
        self.assertEqual(
            [r["organization"] for r in out["experience"]],
            ["Rose City Coffee", "Cascade Precision"],
        )

    def test_invented_skill_is_filtered_out(self):
        invented = {**TAILORED, "skills": ["Python", "Kubernetes", "SQL"]}
        out = tailor_resume.assemble(invented, RESUME)
        self.assertNotIn("Kubernetes", out["skills"])
        # every original skill still present
        self.assertEqual(set(out["skills"]), set(RESUME["skills"]))

    def test_out_of_range_and_duplicate_indices_ignored(self):
        messy = {
            **TAILORED,
            "experience": [
                {"source_index": 0, "highlights": ["a"]},
                {"source_index": 0, "highlights": ["dup"]},
                {"source_index": 9, "highlights": ["oob"]},
            ],
        }
        out = tailor_resume.assemble(messy, RESUME)
        self.assertEqual(len(out["experience"]), 2)
        self.assertEqual(out["experience"][0]["highlights"], ["a"])

    def test_empty_summary_falls_back_to_original(self):
        out = tailor_resume.assemble({**TAILORED, "summary": ""}, RESUME)
        self.assertEqual(out["summary"], RESUME["summary"])

    def test_contact_and_certifications_pass_through_untouched(self):
        out = tailor_resume.assemble(TAILORED, RESUME)
        self.assertEqual(out["email"], RESUME["email"])
        self.assertEqual(out["phone"], RESUME["phone"])
        self.assertEqual(out["links"], RESUME["links"])
        self.assertEqual(out["certifications"], RESUME["certifications"])

    def test_empty_highlights_fall_back_to_source_bullets(self):
        out = tailor_resume.assemble(
            {**TAILORED, "experience": [{"source_index": 0, "highlights": []}]},
            RESUME,
        )
        self.assertEqual(
            out["experience"][0]["highlights"],
            ["Built a pandas reporting pipeline.", "Ran the help desk."],
        )


class RenderMarkdownTests(unittest.TestCase):
    def test_renders_every_section(self):
        md = tailor_resume.render_markdown(tailor_resume.assemble(TAILORED, RESUME))
        self.assertIn("# Jordan Rivera", md)
        self.assertIn(
            "jordan.rivera@example.com · 503-555-0100 · github.com/jrivera-example", md
        )
        self.assertIn("## Summary", md)
        self.assertIn("Analyst who builds Python reporting pipelines.", md)
        self.assertIn("## Skills", md)
        self.assertIn("### IT Support Analyst — Cascade Precision", md)
        self.assertIn("*2021 - Present*", md)
        self.assertIn("- Built Python/pandas reporting pipelines.", md)
        self.assertIn("## Education", md)
        self.assertIn("- AAS, Network Administration, PCC (2019)", md)
        self.assertIn("## Certifications", md)
        self.assertIn("- CompTIA A+ (CompTIA, 2019)", md)

    def test_role_without_dates_omits_the_italic_line(self):
        resume = {
            "name": "A",
            "location": "",
            "email": "",
            "phone": "",
            "links": [],
            "summary": "",
            "skills": [],
            "experience": [
                {"title": "T", "organization": "O", "dates": "", "highlights": ["h"]}
            ],
            "education": [],
            "certifications": [],
        }
        md = tailor_resume.render_markdown(resume)
        self.assertNotIn("**", md)
        self.assertIn("### T — O", md)
        self.assertIn("- h", md)


class VerifyBulletsTests(unittest.TestCase):
    @patch("llm_client.get_client")
    def test_prompt_pairs_original_and_rewritten_and_enums_positions(
        self, mock_get_client
    ):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response({"unsupported": []})
        mock_get_client.return_value = mock_client

        tailor_resume.verify_bullets(TAILORED, RESUME)

        _, kwargs = mock_client.messages.create.call_args
        prompt = kwargs["messages"][0]["content"]
        self.assertIn("ORIGINAL:", prompt)
        self.assertIn("Reconciled monthly accounts in Excel.", prompt)  # source
        self.assertIn("[0] Built Python/pandas reporting pipelines.", prompt)  # rewritten
        enum = kwargs["output_config"]["format"]["schema"]["properties"][
            "unsupported"
        ]["items"]["properties"]["experience_position"]["enum"]
        self.assertEqual(enum, [0, 1])

    def test_no_experience_skips_the_call(self):
        # no client patched -> a real call would raise; it must not happen
        out = tailor_resume.verify_bullets({**TAILORED, "experience": []}, RESUME)
        self.assertEqual(out, {"unsupported": []})


class ApplyVerificationTests(unittest.TestCase):
    def test_drops_flagged_bullet_and_records_it(self):
        tailored = {
            **TAILORED,
            "experience": [
                {
                    "source_index": 0,
                    "highlights": ["Real reworded bullet.", "Invented 40% metric."],
                }
            ],
        }
        clean, flags = tailor_resume._apply_verification(
            tailored,
            [{"experience_position": 0, "bullet_index": 1, "issue": "no 40% anywhere"}],
            RESUME,
        )
        self.assertEqual(clean["experience"][0]["highlights"], ["Real reworded bullet."])
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["bullet"], "Invented 40% metric.")
        self.assertIn("IT Support Analyst", flags[0]["role"])

    def test_role_emptied_by_flags_falls_back_to_source_bullets(self):
        tailored = {
            **TAILORED,
            "experience": [{"source_index": 0, "highlights": ["bad one"]}],
        }
        clean, flags = tailor_resume._apply_verification(
            tailored,
            [{"experience_position": 0, "bullet_index": 0, "issue": "unsupported"}],
            RESUME,
        )
        self.assertEqual(
            clean["experience"][0]["highlights"],
            RESUME["experience"][0]["highlights"],
        )
        self.assertEqual(len(flags), 1)

    def test_nothing_flagged_is_a_passthrough(self):
        clean, flags = tailor_resume._apply_verification(TAILORED, [], RESUME)
        self.assertEqual(flags, [])
        self.assertEqual(
            clean["experience"], TAILORED["experience"]
        )


class BuildDiffTests(unittest.TestCase):
    def test_pairs_each_role_original_vs_tailored_after_reorder(self):
        assembled = tailor_resume.assemble(
            {
                **TAILORED,
                "experience": [
                    {"source_index": 1, "highlights": ["Reconciled accounts."]},
                    {"source_index": 0, "highlights": ["Built pipelines."]},
                ],
            },
            RESUME,
        )
        diff = tailor_resume.build_diff(RESUME, assembled)
        self.assertEqual(diff[0]["organization"], "Rose City Coffee")
        self.assertEqual(diff[0]["original"], ["Reconciled monthly accounts in Excel."])
        self.assertEqual(diff[0]["tailored"], ["Reconciled accounts."])
        self.assertEqual(diff[1]["organization"], "Cascade Precision")


class BuildTailoredResumeTests(unittest.TestCase):
    @patch("llm_client.get_client")
    def test_end_to_end_shape_with_verification(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _json_response(TAILORED),
            _json_response({"unsupported": []}),
        ]
        mock_get_client.return_value = mock_client

        out = tailor_resume.build_tailored_resume(COMPARISON, RESUME, JOB)

        self.assertEqual(set(out), {"resume", "markdown", "changes", "flags", "diff"})
        self.assertEqual(out["changes"], TAILORED["changes"])
        self.assertEqual(out["flags"], [])
        self.assertEqual(len(out["diff"]), 2)
        self.assertIn("# Jordan Rivera", out["markdown"])
        self.assertEqual(mock_client.messages.create.call_count, 2)

    @patch("llm_client.get_client")
    def test_verify_false_skips_the_audit_call(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _json_response(TAILORED)
        mock_get_client.return_value = mock_client

        out = tailor_resume.build_tailored_resume(
            COMPARISON, RESUME, JOB, verify=False
        )

        self.assertEqual(mock_client.messages.create.call_count, 1)
        self.assertEqual(out["flags"], [])

    @patch("llm_client.get_client")
    def test_flagged_bullet_is_dropped_end_to_end(self, mock_get_client):
        tailored = {
            **TAILORED,
            "experience": [
                {
                    "source_index": 0,
                    "highlights": ["Kept bullet.", "Overreaching bullet."],
                },
                {"source_index": 1, "highlights": ["Reconciled accounts."]},
            ],
        }
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _json_response(tailored),
            _json_response(
                {
                    "unsupported": [
                        {
                            "experience_position": 0,
                            "bullet_index": 1,
                            "issue": "claims a scope the source never states",
                        }
                    ]
                }
            ),
        ]
        mock_get_client.return_value = mock_client

        out = tailor_resume.build_tailored_resume(COMPARISON, RESUME, JOB)

        self.assertEqual(len(out["flags"]), 1)
        self.assertNotIn("Overreaching bullet.", out["markdown"])
        self.assertIn("Kept bullet.", out["markdown"])


if __name__ == "__main__":
    unittest.main()
