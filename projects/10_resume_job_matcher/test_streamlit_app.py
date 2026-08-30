import unittest

from streamlit.testing.v1 import AppTest

COMPARISON = {
    "required_skills": [
        {"skill": "Python", "met": True, "evidence": "Built a Python pipeline."},
        {"skill": "Kubernetes", "met": False, "evidence": ""},
    ],
    "preferred_skills": [
        {"skill": "pandas", "met": True, "evidence": "pandas reporting pipeline"},
    ],
    "years": {"required": 2, "candidate": 5, "met": True},
    "education": {"requirement": "Bachelor's", "met": True, "note": "Equivalent experience."},
}

REPORT = {
    "job_title": "Junior AI Engineer",
    "company": "Northwind",
    "score": 74,
    "band": "Possible",
    "breakdown": [
        {"component": "Required skills", "points": 30.0, "max_points": 60, "detail": "1 of 2 met"},
        {"component": "Years of experience", "points": 20, "max_points": 20, "detail": "5 yrs vs 2 required"},
        {"component": "Preferred skills", "points": 15.0, "max_points": 15, "detail": "1 of 1 met"},
        {"component": "Education", "points": 5, "max_points": 5, "detail": "Equivalent experience."},
    ],
    "gaps": {
        "unmet_required_skills": ["Kubernetes"],
        "unmet_preferred_skills": [],
        "years_short": None,
        "education_unmet": False,
    },
    "suggestions": [
        {
            "gap": "Kubernetes",
            "assessment": "genuine_gap",
            "suggestion": "No container-orchestration experience shown; a home lab would help.",
        }
    ],
    "overall": "Strong fundamentals, short on the cloud-native pieces.",
}


class StreamlitAppTests(unittest.TestCase):
    def test_cold_load_has_no_exception(self):
        at = AppTest.from_file("streamlit_app.py").run()
        self.assertEqual(list(at.exception), [])

    def test_renders_single_report_from_session_state(self):
        at = AppTest.from_file("streamlit_app.py")
        at.session_state["single"] = {"comparison": COMPARISON, "report": REPORT}
        at.run()

        self.assertEqual(list(at.exception), [])
        self.assertIn("74 / 100", [m.value for m in at.metric])
        self.assertTrue(any("cloud-native" in info.value for info in at.info))

    _RESUME_DICT = {
        "name": "Jordan Rivera",
        "location": "Portland, OR",
        "email": "jordan@example.com",
        "phone": "",
        "links": ["github.com/jrivera"],
        "summary": "Reframed for the role.",
        "skills": ["Python", "pandas"],
        "experience": [
            {
                "title": "IT Support Analyst",
                "organization": "Cascade Precision",
                "dates": "2021 - Present",
                "highlights": ["Built a Python + pandas reporting pipeline."],
            }
        ],
        "education": [],
        "certifications": [],
    }

    def test_renders_tailored_resume_from_session_state(self):
        at = AppTest.from_file("streamlit_app.py")
        at.session_state["single"] = {"comparison": COMPARISON, "report": REPORT}
        at.session_state["tailored"] = {
            "resume": self._RESUME_DICT,
            "markdown": "# Jordan Rivera\n\n## Summary\n\nReframed for the role.\n",
            "changes": ["Rewrote the summary.", "Led with the analyst role."],
            "flags": [],
            "diff": [
                {
                    "title": "IT Support Analyst",
                    "organization": "Cascade Precision",
                    "original": ["Built a Python pipeline."],
                    "tailored": ["Built a Python + pandas reporting pipeline."],
                }
            ],
        }
        at.run()

        self.assertEqual(list(at.exception), [])
        labels = {b.label for b in at.download_button}
        self.assertTrue({"PDF", "Word", "Markdown"} <= labels)
        self.assertTrue(any("Reframed for the role." in m.value for m in at.markdown))

    def test_export_buttons_hidden_when_resume_dict_missing(self):
        at = AppTest.from_file("streamlit_app.py")
        at.session_state["single"] = {"comparison": COMPARISON, "report": REPORT}
        at.session_state["tailored"] = {
            "resume": {},
            "markdown": "# Jordan Rivera\n",
            "changes": [],
            "flags": [],
            "diff": [],
        }
        at.run()
        self.assertEqual(list(at.exception), [])
        labels = {b.label for b in at.download_button}
        self.assertIn("Markdown", labels)
        self.assertNotIn("PDF", labels)
        self.assertNotIn("Word", labels)

    def test_tailored_resume_flags_overreaching_bullets(self):
        at = AppTest.from_file("streamlit_app.py")
        at.session_state["single"] = {"comparison": COMPARISON, "report": REPORT}
        at.session_state["tailored"] = {
            "resume": {},
            "markdown": "# Jordan Rivera\n",
            "changes": [],
            "flags": [
                {
                    "role": "IT Support Analyst — Cascade Precision",
                    "bullet": "Cut cloud spend 40%.",
                    "issue": "no 40% figure in the source",
                }
            ],
            "diff": [],
        }
        at.run()

        self.assertEqual(list(at.exception), [])
        self.assertTrue(any("Dropped 1 bullet" in w.value for w in at.warning))

    def test_renders_cover_letter_with_flags_from_session_state(self):
        at = AppTest.from_file("streamlit_app.py")
        at.session_state["single"] = {"comparison": COMPARISON, "report": REPORT}
        at.session_state["cover"] = {
            "text": "Jordan Rivera\n\nDear Hiring Manager,\n\nBody.\n\nSincerely,\nJordan Rivera\n",
            "paragraphs": ["Body."],
            "greeting": "Dear Hiring Manager,",
            "claims": [{"claim": "Built a pipeline", "evidence": "Built a Python pipeline."}],
            "flags": [{"claim": "Ten years of leadership", "issue": "résumé shows no leadership role"}],
        }
        at.run()

        self.assertEqual(list(at.exception), [])
        self.assertTrue(any("1 claim" in w.value for w in at.warning))
        self.assertTrue(
            any(b.label == "Download cover letter" for b in at.download_button)
        )

    def test_resume_file_uploader_is_present(self):
        at = AppTest.from_file("streamlit_app.py").run()
        self.assertEqual(list(at.exception), [])
        self.assertEqual(len(at.get("file_uploader")), 1)

    def test_missing_inputs_warn_on_submit(self):
        at = AppTest.from_file("streamlit_app.py").run()
        submit = next(b for b in at.button if b.label == "Evaluate fit")
        submit.click().run()
        self.assertEqual(list(at.exception), [])
        self.assertTrue(any("Paste both" in w.value for w in at.warning))

    def test_search_mode_renders_ranked_results_from_session_state(self):
        at = AppTest.from_file("streamlit_app.py")
        at.session_state["mode"] = "Search live jobs"
        at.session_state["search"] = [
            {
                "report": {**REPORT, "score": 88, "band": "Strong"},
                "comparison": COMPARISON,
                "url": "https://jobs.lever.co/x/1",
                "grounding": "full posting",
            },
            {
                "report": {**REPORT, "job_title": "Data Analyst", "score": 40, "band": "Weak"},
                "comparison": COMPARISON,
                "url": "https://indeed.com/x",
                "grounding": "search snippet",
            },
        ]
        at.run()

        self.assertEqual(list(at.exception), [])
        self.assertTrue(any("2 postings" in c.value for c in at.caption))

    def test_salt_lake_city_preset_shows_local_boards_note(self):
        at = AppTest.from_file("streamlit_app.py")
        at.session_state["mode"] = "Search live jobs"
        at.run()
        at.selectbox[0].set_value("Salt Lake City").run()
        self.assertEqual(list(at.exception), [])
        self.assertTrue(any("Utah/SLC" in c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()
