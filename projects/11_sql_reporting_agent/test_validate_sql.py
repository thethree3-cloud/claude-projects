import unittest

from validate_sql import SQLValidationError, validate_select


class ValidateSelectTests(unittest.TestCase):
    def test_plain_select_passes(self):
        sql = "SELECT TOP 5 Name FROM Production.Product ORDER BY Name"
        self.assertEqual(validate_select(sql), sql)

    def test_cte_select_passes(self):
        sql = "WITH Totals AS (SELECT ProductID, SUM(OrderQty) AS Qty FROM Sales.SalesOrderDetail GROUP BY ProductID) SELECT * FROM Totals"
        self.assertEqual(validate_select(sql), sql)

    def test_trailing_semicolon_is_stripped(self):
        self.assertEqual(validate_select("SELECT 1;"), "SELECT 1")

    def test_string_literal_containing_forbidden_word_is_not_rejected(self):
        sql = "SELECT Name FROM Production.Product WHERE Name LIKE '%update%'"
        self.assertEqual(validate_select(sql), sql)

    def test_delete_is_rejected(self):
        with self.assertRaises(SQLValidationError):
            validate_select("DELETE FROM Production.Product")

    def test_drop_is_rejected(self):
        with self.assertRaises(SQLValidationError):
            validate_select("DROP TABLE Production.Product")

    def test_insert_is_rejected(self):
        with self.assertRaises(SQLValidationError):
            validate_select("INSERT INTO Production.Product (Name) VALUES ('x')")

    def test_update_is_rejected(self):
        with self.assertRaises(SQLValidationError):
            validate_select("UPDATE Production.Product SET Name = 'x'")

    def test_chained_statement_is_rejected(self):
        with self.assertRaises(SQLValidationError):
            validate_select("SELECT 1; DROP TABLE Production.Product")

    def test_comment_smuggled_statement_is_rejected(self):
        sql = "SELECT 1 -- harmless\n; DROP TABLE Production.Product"
        with self.assertRaises(SQLValidationError):
            validate_select(sql)

    def test_select_into_is_rejected(self):
        with self.assertRaises(SQLValidationError):
            validate_select("SELECT * INTO NewTable FROM Production.Product")

    def test_bare_stored_proc_call_is_rejected(self):
        with self.assertRaises(SQLValidationError):
            validate_select("xp_cmdshell 'dir'")

    def test_exec_is_rejected(self):
        with self.assertRaises(SQLValidationError):
            validate_select("EXEC sp_who")

    def test_empty_query_is_rejected(self):
        with self.assertRaises(SQLValidationError):
            validate_select("   ")

    def test_non_select_start_is_rejected(self):
        with self.assertRaises(SQLValidationError):
            validate_select("Production.Product SELECT *")


if __name__ == "__main__":
    unittest.main()
