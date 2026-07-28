"""Execute a validated SELECT against AdventureWorks via the read-only login.

This is the third safety-relevant step: even though the caller (run_report,
step 7) should already have validated the query, execute_query() re-runs
validate_select() itself right before running anything. The boundary where
a query actually touches the database is the right place to enforce the
rule, not just the step that happens to run before it.
"""
from db import get_connection
from validate_sql import validate_select

QUERY_TIMEOUT_SECONDS = 15
MAX_ROWS = 200


class QueryExecutionError(Exception):
    pass


def execute_query(sql):
    """Validate, run, and return (columns, rows, truncated) for a SELECT."""
    safe_sql = validate_select(sql)

    conn = get_connection()
    try:
        conn.timeout = QUERY_TIMEOUT_SECONDS
        cur = conn.cursor()
        try:
            cur.execute(safe_sql)
        except Exception as e:
            raise QueryExecutionError(str(e)) from e

        columns = [col[0] for col in cur.description]
        rows = cur.fetchmany(MAX_ROWS)
        truncated = cur.fetchone() is not None
        return columns, [tuple(row) for row in rows], truncated
    finally:
        conn.close()


def main():
    import sys
    if len(sys.argv) < 2:
        print(f"Usage: python {__file__} \"<sql>\"")
        sys.exit(1)
    columns, rows, truncated = execute_query(" ".join(sys.argv[1:]))
    print(columns)
    for row in rows:
        print(row)
    if truncated:
        print(f"... truncated at {MAX_ROWS} rows")


if __name__ == "__main__":
    main()
