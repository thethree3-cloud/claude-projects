import unittest
from unittest.mock import patch

from execute_sql import QueryExecutionError
from run_report import run_report
from validate_sql import SQLValidationError


class RunReportTests(unittest.TestCase):
    """These mock generate_sql/execute_query/summarize rather than hitting the
    real LLM/DB -- run_report's own job is chaining those three steps and
    translating failures into readable messages, which is what's under test
    here. Each piece it calls already has its own coverage (or was verified
    live end-to-end while building it) elsewhere.
    """

    @patch("run_report.summarize")
    @patch("run_report.execute_query")
    @patch("run_report.generate_sql")
    def test_happy_path_chains_all_three_steps(self, mock_generate, mock_execute, mock_summarize):
        mock_generate.return_value = "SELECT 1"
        mock_execute.return_value = (["Col"], [(1,)], False)
        mock_summarize.return_value = "The answer is 1."

        result = run_report("how many?")

        self.assertEqual(result, "The answer is 1.")
        mock_generate.assert_called_once_with("how many?")
        mock_execute.assert_called_once_with("SELECT 1")
        mock_summarize.assert_called_once_with("how many?", ["Col"], [(1,)], False, sql="SELECT 1")

    @patch("run_report.generate_sql")
    def test_generation_failure_returns_readable_message(self, mock_generate):
        mock_generate.side_effect = RuntimeError("ANTHROPIC_API_KEY not found")

        result = run_report("how many?")

        self.assertIn("Couldn't turn that question into a query", result)
        self.assertIn("ANTHROPIC_API_KEY not found", result)

    @patch("run_report.execute_query")
    @patch("run_report.generate_sql")
    def test_validation_rejection_returns_readable_message(self, mock_generate, mock_execute):
        mock_generate.return_value = "DROP TABLE Production.Product"
        mock_execute.side_effect = SQLValidationError("Forbidden keyword 'DROP' is not allowed.")

        result = run_report("delete everything")

        self.assertIn("rejected for safety reasons", result)
        self.assertIn("DROP", result)

    @patch("run_report.execute_query")
    @patch("run_report.generate_sql")
    def test_execution_failure_returns_readable_message(self, mock_generate, mock_execute):
        mock_generate.return_value = "SELECT NotARealColumn FROM Production.Product"
        mock_execute.side_effect = QueryExecutionError("Invalid column name 'NotARealColumn'.")

        result = run_report("bad question")

        self.assertIn("query failed to run", result)
        self.assertIn("NotARealColumn", result)


if __name__ == "__main__":
    unittest.main()
