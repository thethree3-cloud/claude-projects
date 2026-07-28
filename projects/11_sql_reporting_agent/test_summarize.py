import unittest
from decimal import Decimal

from summarize import format_result_table


class FormatResultTableTests(unittest.TestCase):
    def test_empty_rows_returns_placeholder(self):
        self.assertEqual(format_result_table(["Name"], []), "(no rows returned)")

    def test_single_row_formats_header_and_values(self):
        table = format_result_table(["FirstName", "LastName"], [("Linda", "Mitchell")])
        self.assertEqual(table, "FirstName | LastName\nLinda | Mitchell")

    def test_multiple_rows_each_on_own_line(self):
        table = format_result_table(["Name"], [("A",), ("B",), ("C",)])
        self.assertEqual(table, "Name\nA\nB\nC")

    def test_non_string_values_are_stringified(self):
        table = format_result_table(
            ["Territory", "Total"], [("Southwest", Decimal("10510853.8739"))]
        )
        self.assertEqual(table, "Territory | Total\nSouthwest | 10510853.8739")

    def test_none_values_render_as_none(self):
        table = format_result_table(["Name", "MiddleName"], [("Ken", None)])
        self.assertEqual(table, "Name | MiddleName\nKen | None")


if __name__ == "__main__":
    unittest.main()
