"""Full NL-to-SQL reporting pipeline: a plain-English question in, a plain-
English answer out. Wires together the standalone pieces built in steps
3-6: generate_sql -> execute_query (validates internally) -> summarize.
"""
from execute_sql import execute_query, QueryExecutionError
from generate_sql import generate_sql
from summarize import summarize
from validate_sql import SQLValidationError


def run_report(question):
    """Pure (no printing) entry point -- safe to call from an MCP server,
    same convention as Project 01's answer_question() (see Project 06).
    """
    try:
        sql = generate_sql(question)
    except Exception as e:
        return f"Couldn't turn that question into a query: {e}"

    try:
        columns, rows, truncated = execute_query(sql)
    except SQLValidationError as e:
        return f"Generated query was rejected for safety reasons: {e}"
    except QueryExecutionError as e:
        return f"The query failed to run: {e}"

    return summarize(question, columns, rows, truncated, sql=sql)


def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python run_report.py \"<question>\"")
        sys.exit(1)
    print(run_report(" ".join(sys.argv[1:])))


if __name__ == "__main__":
    main()
