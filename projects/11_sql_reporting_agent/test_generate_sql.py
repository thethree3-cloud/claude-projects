import unittest

from generate_sql import extract_sql


class ExtractSQLTests(unittest.TestCase):
    def test_plain_sql_passes_through(self):
        self.assertEqual(extract_sql("SELECT 1"), "SELECT 1")

    def test_strips_sql_fenced_block(self):
        raw = "```sql\nSELECT 1 FROM Production.Product\n```"
        self.assertEqual(extract_sql(raw), "SELECT 1 FROM Production.Product")

    def test_strips_bare_fenced_block(self):
        raw = "```\nSELECT 1\n```"
        self.assertEqual(extract_sql(raw), "SELECT 1")

    def test_strips_trailing_semicolon(self):
        self.assertEqual(extract_sql("SELECT 1;"), "SELECT 1")

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(extract_sql("\n\n  SELECT 1  \n\n"), "SELECT 1")

    def test_fenced_block_with_surrounding_prose_extracts_only_sql(self):
        raw = "Here is the query:\n```sql\nSELECT 1\n```\nLet me know if you need changes."
        self.assertEqual(extract_sql(raw), "SELECT 1")


if __name__ == "__main__":
    unittest.main()
