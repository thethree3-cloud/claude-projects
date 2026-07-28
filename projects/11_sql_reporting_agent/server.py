"""
MCP tool server wrapping Project 11's natural-language SQL reporting agent
as MCP tools, following the same pattern Project 06 used for Projects 01
and 04: the business logic was already built and tested standalone
(steps 1-7) before this file existed -- this is purely the protocol
wrapper on top of it.

IMPORTANT: stdio transport uses stdout for JSON-RPC framing, so nothing
wrapped here may print to stdout. run_report() and list_schema() are
already print-free for exactly this reason (see run_report.py, schema.py).
"""
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from run_report import run_report  # noqa: E402
from schema import SCHEMA_CONTEXT_PATH, list_schema  # noqa: E402

mcp = FastMCP("sql-reporting-agent")


@mcp.tool()
def run_sql_report(question: str) -> str:
    """Answer a natural-language reporting question against the
    AdventureWorks database.

    Generates a single read-only SQL SELECT from the question, validates
    it (rejects anything that isn't a clean single SELECT), executes it
    through a read-only database login, and returns a plain-language
    answer grounded in the actual query result.
    """
    return run_report(question)


@mcp.tool()
def list_database_schema() -> str:
    """Return the AdventureWorks table/column/foreign-key schema this
    agent can query -- useful for knowing what questions are answerable.
    """
    if SCHEMA_CONTEXT_PATH.exists():
        return SCHEMA_CONTEXT_PATH.read_text()
    return list_schema()


if __name__ == "__main__":
    mcp.run()
