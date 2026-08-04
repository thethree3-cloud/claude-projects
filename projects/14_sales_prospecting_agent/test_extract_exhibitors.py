import unittest

from extract_exhibitors import (
    NUMERIC_LABEL_PATTERN,
    _extract_numbered_list,
    _is_letter_spaced_caption,
    _parse_index_rows,
    _row_name_and_booth,
    _strip_exhibitors_header,
    extract_company_names,
)
from generate_sample_data import DATA_DIR, EXHIBITORS, write_exhibitor_list_pdf


def _span(y0, x0, text):
    return (y0, x0, text)


class ExtractCompanyNamesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        write_exhibitor_list_pdf()
        cls.pdf_path = DATA_DIR / "sample_expo_exhibitors.pdf"

    def test_extracts_all_known_exhibitors_in_order(self):
        names = extract_company_names(self.pdf_path)
        self.assertEqual(names, EXHIBITORS)


class RowNameAndBoothTests(unittest.TestCase):
    def test_name_and_booth_spans_on_one_row(self):
        row = [_span(135.1, 36.0, "Acme Mills Company\t"), _span(135.1, 190.2, "2013")]
        self.assertEqual(_row_name_and_booth(row), ("Acme Mills Company", "2013"))

    def test_three_spans_name_gap_booth_same_row(self):
        # Mirrors a real layout variant found live: name, a lone space
        # span, then the booth number, all on one visual row.
        row = [
            _span(638.2, 220.5, "Michigan Manufacturing Technology Center\t"),
            _span(638.2, 370.3, " "),
            _span(638.2, 373.2, "8020"),
        ]
        self.assertEqual(
            _row_name_and_booth(row), ("Michigan Manufacturing Technology Center", "8020")
        )

    def test_name_only_row_has_no_booth(self):
        row = [_span(728.5, 36.0, "and Assembly, LLC\t")]
        self.assertEqual(_row_name_and_booth(row), ("and Assembly, LLC", None))


class ParseIndexRowsTests(unittest.TestCase):
    def test_simple_single_line_entries(self):
        rows = [
            [_span(135.1, 36.0, "313 Industries, Inc.\t"), _span(135.1, 190.2, "3015")],
            [_span(146.2, 36.0, "Ace Electronics Defense Systems\t"), _span(146.2, 190.2, "8013")],
        ]
        self.assertEqual(
            _parse_index_rows(rows),
            [("313 Industries, Inc.", "3015"), ("Ace Electronics Defense Systems", "8013")],
        )

    def test_wrapped_name_with_booth_on_first_row_merges_correctly(self):
        # This is the real case found live: "Diversified Manufacturing"
        # (row 1, carrying the booth number) wraps to "and Assembly, LLC"
        # (row 2, no booth of its own) before the next real entry
        # ("DornerWorks") begins. Geometry -- the booth's row shares y0
        # with the name's first line -- is what makes merging these two
        # rows into one entry possible, unlike a plain-text line scan.
        rows = [
            [_span(709.1, 36.0, "Diversified Manufacturing \t"), _span(709.1, 188.8, "6022")],
            [_span(717.4, 36.0, "and Assembly, LLC\t")],
            [_span(728.5, 36.0, "DornerWorks\t"), _span(728.5, 190.0, "6027")],
        ]
        self.assertEqual(
            _parse_index_rows(rows),
            [
                ("Diversified Manufacturing and Assembly, LLC", "6022"),
                ("DornerWorks", "6027"),
            ],
        )

    def test_wrapped_name_at_end_of_column_with_no_following_row(self):
        rows = [
            [_span(709.1, 36.0, "Diversified Manufacturing \t"), _span(709.1, 188.8, "6022")],
            [_span(717.4, 36.0, "and Assembly, LLC\t")],
        ]
        self.assertEqual(
            _parse_index_rows(rows),
            [("Diversified Manufacturing and Assembly, LLC", "6022")],
        )

    def test_leading_row_with_no_booth_never_closes(self):
        # Mirrors the real "Exhibitors" section header -- a name-only row
        # with nothing to close it until a booth-carrying row appears.
        rows = [
            [_span(94.0, 36.0, "Exhibitors")],
            [_span(135.1, 36.0, "313 Industries, Inc.\t"), _span(135.1, 190.2, "3015")],
        ]
        self.assertEqual(
            _parse_index_rows(rows), [("Exhibitors 313 Industries, Inc.", "3015")]
        )


class NoiseFilterTests(unittest.TestCase):
    def test_detects_letter_spaced_caption(self):
        self.assertTrue(
            _is_letter_spaced_caption("A p r e m i e r d o d b u y e r e v e n t")
        )

    def test_real_company_name_is_not_flagged(self):
        self.assertFalse(_is_letter_spaced_caption("Ace Electronics Defense Systems"))

    def test_strips_leading_exhibitors_header(self):
        self.assertEqual(
            _strip_exhibitors_header("Exhibitors 313 Industries, Inc."),
            "313 Industries, Inc.",
        )

    def test_leaves_unrelated_name_unchanged(self):
        self.assertEqual(_strip_exhibitors_header("Acme Mills Company"), "Acme Mills Company")

    def test_numeric_label_is_flagged(self):
        # A dashboard/chart-mockup label found live on a non-index page
        # ("Active Requests ... 500 / 1.0K / 273") -- these must never be
        # mistaken for a company name.
        for label in ("1.0K", "500", "273", "42%", "1,200"):
            self.assertTrue(NUMERIC_LABEL_PATTERN.match(label), label)

    def test_real_company_name_is_not_a_numeric_label(self):
        for name in ("313 Industries, Inc.", "ADS, Inc.", "3M Company"):
            self.assertFalse(NUMERIC_LABEL_PATTERN.match(name), name)


class NumberedListFalsePositiveTests(unittest.TestCase):
    def test_single_coincidental_numbered_match_falls_back_to_tab_booth(self):
        # A real multi-page program can contain an unrelated figure that
        # happens to match "N. text" (confirmed live: a "$70.0K"-shaped
        # number) -- a single such match must not be trusted as "this PDF
        # uses the fictional numbered-list format" and short-circuit before
        # the real tab+booth parser ever runs.
        text = "70.0K in funding\nAcme Mills Company\t\n2013\n"
        self.assertEqual(len(_extract_numbered_list(text)), 1)


if __name__ == "__main__":
    unittest.main()
