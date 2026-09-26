import unittest

from ask import (compute_ranges, format_history, format_reply, parse_route_lines,
                 split_used_sources, standalone_question)


class ComputeRangesTests(unittest.TestCase):
    def test_sections_run_through_the_next_start_page(self):
        # Sections start mid-page, so each one includes the page where the
        # next begins (regression: Workers' Compensation p.20 continues on
        # p.21, where the next section also starts).
        rows = [
            {"subject": "A", "start_page": "5"},
            {"subject": "B", "start_page": "8"},
            {"subject": "C", "start_page": "10"},
        ]
        sections = compute_ranges(rows, doc_page_count=20)
        self.assertEqual(
            sections,
            [
                {"subject": "A", "start": 5, "end": 8},
                {"subject": "B", "start": 8, "end": 10},
                {"subject": "C", "start": 10, "end": 20},
            ],
        )

    def test_last_section_extends_to_document_end(self):
        rows = [{"subject": "Only Section", "start_page": "1"}]
        sections = compute_ranges(rows, doc_page_count=22)
        self.assertEqual(sections[0]["end"], 22)

    def test_duplicate_start_page_is_clamped_not_inverted(self):
        # Regression test: two ToC entries on the same page (e.g. "Smoking
        # Policy" / "Staff Development/Training" both starting on page 19)
        # used to produce end < start.
        rows = [
            {"subject": "Smoking Policy", "start_page": "19"},
            {"subject": "Staff Development/Training", "start_page": "19"},
            {"subject": "Use & Abuse of Drugs and Alcohol", "start_page": "20"},
        ]
        sections = compute_ranges(rows, doc_page_count=22)
        smoking = sections[0]
        self.assertGreaterEqual(smoking["end"], smoking["start"])
        self.assertEqual(smoking, {"subject": "Smoking Policy", "start": 19, "end": 19})


class ParseRouteLinesTests(unittest.TestCase):
    def setUp(self):
        self.valid_subjects = [
            "Smoking Policy",
            "Safety",
            "Use & Abuse of Drugs and Alcohol",
            "Military Leave",
        ]

    def test_exact_match_single_subject(self):
        matched, unmatched = parse_route_lines("Smoking Policy", self.valid_subjects)
        self.assertEqual(matched, ["Smoking Policy"])
        self.assertEqual(unmatched, [])

    def test_exact_match_multiple_subjects_preserves_order(self):
        raw = "Safety\nUse & Abuse of Drugs and Alcohol"
        matched, unmatched = parse_route_lines(raw, self.valid_subjects)
        self.assertEqual(matched, ["Safety", "Use & Abuse of Drugs and Alcohol"])
        self.assertEqual(unmatched, [])

    def test_none_response_yields_no_matches(self):
        matched, unmatched = parse_route_lines("NONE", self.valid_subjects)
        self.assertEqual(matched, [])
        self.assertEqual(unmatched, [])

    def test_blank_response_yields_no_matches(self):
        matched, unmatched = parse_route_lines("   \n  ", self.valid_subjects)
        self.assertEqual(matched, [])
        self.assertEqual(unmatched, [])

    def test_paraphrased_subject_is_fuzzy_matched(self):
        # Model copied the subject with a minor wording/typo difference
        # instead of verbatim -- should still resolve via fuzzy matching.
        matched, unmatched = parse_route_lines("Smoking Policies", self.valid_subjects)
        self.assertEqual(matched, ["Smoking Policy"])
        self.assertEqual(unmatched, [])

    def test_unrelated_line_is_reported_as_unmatched(self):
        matched, unmatched = parse_route_lines("Parking Regulations", self.valid_subjects)
        self.assertEqual(matched, [])
        self.assertEqual(unmatched, ["Parking Regulations"])

    def test_duplicate_lines_are_deduplicated(self):
        matched, unmatched = parse_route_lines(
            "Safety\nSafety", self.valid_subjects
        )
        self.assertEqual(matched, ["Safety"])


class SplitUsedSourcesTests(unittest.TestCase):
    def test_strips_line_and_returns_zero_based_indexes(self):
        self.assertEqual(split_used_sources("30 feet.\n\nUSED: S2, S1", 3), ("30 feet.", [1, 0]))

    def test_strips_inline_tags_backticks_and_dedups(self):
        body, used = split_used_sources("Smoking Policy [S1] says 30 feet.\n`used: [S1], S1`", 2)
        self.assertEqual((body, used), ("Smoking Policy says 30 feet.", [0]))

    def test_none_means_no_sources(self):
        self.assertEqual(split_used_sources("Not covered.\nUSED: NONE", 3), ("Not covered.", []))

    def test_out_of_range_ids_dropped(self):
        self.assertEqual(split_used_sources("x\nUSED: S9, S1", 2)[1], [0])

    def test_missing_line_falls_back_to_all(self):
        self.assertEqual(split_used_sources("Answer only.", 3), ("Answer only.", [0, 1, 2]))


class FollowUpTests(unittest.TestCase):
    def test_history_keeps_last_turns_and_clips_long_messages(self):
        history = [{"role": "user", "content": f"q{i}"} for i in range(10)]
        history.append({"role": "assistant", "content": "a" * 50})
        self.assertEqual(format_history(history, max_turns=1, max_chars=10),
                         "User: q9\nAssistant: " + "a" * 10 + "...")

    def test_first_question_skips_the_api(self):
        # No history -> returned as-is without ever creating a client.
        self.assertEqual(standalone_question("What is FMLA?", []), "What is FMLA?")


class FormatReplyTests(unittest.TestCase):
    def test_lists_sources_only_when_present(self):
        source = {"subject": "Smoking Policy", "start": 19, "end": 19}
        self.assertEqual(format_reply({"answer": "A", "sources": [source]}),
                         "A\n\nSources:\n- Smoking Policy (pages 19-19)")
        self.assertEqual(format_reply({"answer": "A", "sources": []}), "A")


if __name__ == "__main__":
    unittest.main()
