import unittest

from ask import compute_ranges, parse_route_lines


class ComputeRangesTests(unittest.TestCase):
    def test_normal_sections_span_up_to_next_start(self):
        rows = [
            {"subject": "A", "start_page": "5"},
            {"subject": "B", "start_page": "8"},
            {"subject": "C", "start_page": "10"},
        ]
        sections = compute_ranges(rows, doc_page_count=20)
        self.assertEqual(
            sections,
            [
                {"subject": "A", "start": 5, "end": 7},
                {"subject": "B", "start": 8, "end": 9},
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


if __name__ == "__main__":
    unittest.main()
