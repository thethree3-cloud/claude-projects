"""
MCP tool server wrapping the already-built, already-tested agent logic
from Project 01 (HR handbook Q&A) and Project 04 (AS9100 audit and
document comparison) as MCP tools.

This exists to learn the MCP protocol itself -- tool registration,
schemas, stdio transport -- on top of business logic that's already
validated, rather than learning both at once.

IMPORTANT: stdio transport uses stdout for JSON-RPC framing, so none of
the wrapped functions here may print to stdout. That's why ask.py,
audit.py, and compare.py were each split into a pure "compute" function
(no printing) and a CLI entry point (prints) -- the tools below call
only the pure functions.
"""

import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

PROJECTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECTS_DIR / "01_guidebook_agent"))
sys.path.insert(0, str(PROJECTS_DIR / "04_as9100_audit_agent"))

from ask import answer_question  # noqa: E402  (Project 01)
from audit import compute_audit_results  # noqa: E402  (Project 04)
from compare import compute_comparison  # noqa: E402  (Project 04)

mcp = FastMCP("portfolio-agent-tools")


@mcp.tool()
def ask_handbook(question: str) -> str:
    """Answer a question about the Las Vegas employee handbook.

    Routes the question to the relevant table-of-contents section(s) and
    answers strictly from that extracted text, or says so if the answer
    isn't in the handbook.
    """
    return answer_question(question)


@mcp.tool()
def run_as9100_audit() -> str:
    """Check the fictional AS9100-style checklist against internal work
    instructions and return a Met/Partial/Gap report for every clause.
    """
    results, counts = compute_audit_results()
    lines = [
        f"[{r['status']:7}] {r['id']} -- {r['title']}: {r['rationale']}"
        + (f" (Source: {r['source']})" if r["source"] else "")
        for r in results
    ]
    summary = f"Summary: {counts['Met']} Met, {counts['Partial']} Partial, {counts['Gap']} Gap"
    return "\n".join(lines) + "\n\n" + summary


@mcp.tool()
def compare_reference_document(reference_pdf_path: str) -> str:
    """Compare an uploaded reference document (customer/supplier/internal
    revision PDF) against the closest-matching internal document, and
    report gaps and differences using cautious, non-certifying language.

    Args:
        reference_pdf_path: absolute path to the reference PDF to compare.
    """
    result = compute_comparison(reference_pdf_path)
    if "error" in result:
        return result["error"]

    header = f"Best match: {result['best_match']} -- {result['best_match_title']} (confidence: {result['confidence']})"
    if result["secondary"] != "NONE":
        header += f"\nSecondary matches considered: {result['secondary']}"
    return f"{header}\n\n{result['comparison']}"


if __name__ == "__main__":
    mcp.run()
