import unittest

from audit import parse_verdict
from compare import parse_match
from parse_criteria import parse_clauses


class ParseClausesTests(unittest.TestCase):
    def test_single_line_clause(self):
        lines = ["AC-6.2 | Competence & Training | Training records are maintained."]
        clauses = parse_clauses(lines)
        self.assertEqual(
            clauses,
            [{"id": "AC-6.2", "title": "Competence & Training", "requirement": "Training records are maintained."}],
        )

    def test_wrapped_continuation_lines_are_appended(self):
        lines = [
            "AC-4.2.3 | Document Control | Documented procedures exist for controlling",
            "quality-system documents, including approval, revision, and distribution.",
        ]
        clauses = parse_clauses(lines)
        self.assertEqual(len(clauses), 1)
        self.assertEqual(
            clauses[0]["requirement"],
            "Documented procedures exist for controlling quality-system documents, "
            "including approval, revision, and distribution.",
        )

    def test_multiple_clauses_split_correctly(self):
        lines = [
            "AC-6.2 | Competence & Training | Training records are maintained.",
            "AC-7.1.5 | Calibration Control | Equipment is calibrated on schedule.",
        ]
        clauses = parse_clauses(lines)
        self.assertEqual([c["id"] for c in clauses], ["AC-6.2", "AC-7.1.5"])

    def test_header_lines_before_first_clause_are_ignored(self):
        lines = [
            "Sample Aerospace Co. -- Internal Quality Audit Checklist",
            "(Fictional sample criteria for portfolio testing only.)",
            "AC-6.2 | Competence & Training | Training records are maintained.",
        ]
        clauses = parse_clauses(lines)
        self.assertEqual(len(clauses), 1)


class ParseVerdictTests(unittest.TestCase):
    def test_full_response_parses_all_fields(self):
        raw = "STATUS: Met\nSOURCE: WI-014_document_control.pdf\nRATIONALE: Fully documented."
        status, source, rationale = parse_verdict(raw)
        self.assertEqual(status, "Met")
        self.assertEqual(source, "WI-014_document_control.pdf")
        self.assertEqual(rationale, "Fully documented.")

    def test_invalid_status_defaults_to_gap(self):
        raw = "STATUS: Compliant\nSOURCE: NONE\nRATIONALE: N/A"
        status, _, _ = parse_verdict(raw)
        self.assertEqual(status, "Gap")

    def test_missing_fields_default_to_gap_with_blanks(self):
        status, source, rationale = parse_verdict("some unrelated text")
        self.assertEqual(status, "Gap")
        self.assertEqual(source, "")
        self.assertEqual(rationale, "")

    def test_partial_status_recognized(self):
        raw = "STATUS: Partial\nSOURCE: WI-045.pdf\nRATIONALE: Covers most but not all."
        status, _, _ = parse_verdict(raw)
        self.assertEqual(status, "Partial")


class ParseMatchTests(unittest.TestCase):
    def test_full_response_parses_all_fields(self):
        raw = "BEST_MATCH: Z3-045\nSECONDARY_MATCHES: Z2-052\nCONFIDENCE: approximate"
        best, secondary, confidence = parse_match(raw)
        self.assertEqual(best, "Z3-045")
        self.assertEqual(secondary, "Z2-052")
        self.assertEqual(confidence, "approximate")

    def test_none_match(self):
        raw = "BEST_MATCH: NONE\nSECONDARY_MATCHES: NONE\nCONFIDENCE: none"
        best, secondary, confidence = parse_match(raw)
        self.assertEqual(best, "NONE")
        self.assertEqual(secondary, "NONE")
        self.assertEqual(confidence, "none")

    def test_missing_fields_default_to_none(self):
        best, secondary, confidence = parse_match("unrelated text")
        self.assertEqual(best, "NONE")
        self.assertEqual(secondary, "NONE")
        self.assertEqual(confidence, "none")


if __name__ == "__main__":
    unittest.main()
