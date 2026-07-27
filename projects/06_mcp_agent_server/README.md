# MCP Agent Tool Server (Project 06)

An MCP (Model Context Protocol) server that exposes the already-built,
already-tested agent logic from [Project 01](../01_guidebook_agent) and
[Project 04](../04_as9100_audit_agent) as tools any MCP client (Claude Code,
Claude Desktop, or any other MCP-compatible app) can call directly — no
terminal, no Streamlit UI, just the tools themselves.

## Why this exists

This is the entry point for learning MCP itself. The business logic (PDF
routing, grounded Q&A, checklist gap analysis, document comparison) was
already built and validated in Projects 01 and 04 — this project is purely
about the protocol: tool registration, request/response schemas, and the
stdio transport MCP clients use to talk to a local server.

## Tools exposed

- **`ask_handbook(question)`** — wraps Project 01's `ask.py`. Routes a
  question to the relevant handbook section(s) and answers grounded in that
  text.
- **`run_as9100_audit()`** — wraps Project 04's `audit.py`. Returns the
  Met/Partial/Gap report for every clause in the fictional AS9100-style
  checklist.
- **`compare_reference_document(reference_pdf_path)`** — wraps Project 04's
  `compare.py`. Compares an uploaded reference PDF against the closest
  matching internal document and reports gaps/differences.

## A design constraint worth knowing

MCP's stdio transport uses **stdout** for the actual JSON-RPC protocol
messages. Any stray `print()` inside a wrapped tool would corrupt that
stream and break the connection. Because of this, `ask.py`, `audit.py`, and
`compare.py` were each split into a pure "compute" function (no printing:
`answer_question`, `compute_audit_results`, `compute_comparison`) and a
separate CLI entry point that prints. The MCP tools here call only the pure
functions.

## Setup

```bash
pip install -r ../../requirements.txt
```

Requires `ANTHROPIC_API_KEY` in a `.env` file at the repo root (same as
Projects 01 and 04).

## Running it

As a standalone server (mostly useful for manual protocol-level testing):

```bash
python server.py
```

To register it with Claude Code so you can call these tools directly from
a Claude Code session:

```bash
claude mcp add guidebook-agent -- python /home/t9/claude-projects/projects/06_mcp_agent_server/server.py
```

(Run `claude mcp add --help` if the flags above don't match your installed
version.) Claude Desktop and other MCP clients use a similar
command+args registration in their own config file.

## Verifying it works

This was verified end-to-end with a real MCP client speaking the actual
protocol over stdio (not just a direct Python import test) — connecting,
listing tools, and calling `ask_handbook` and `run_as9100_audit`
successfully, confirming the stdout-safety split above actually holds up
under the real transport.

## Known limitations

- `compare_reference_document` takes an absolute file path rather than
  accepting an uploaded file's bytes directly — fine for local testing,
  but a real deployment would need the MCP client to pass file content
  rather than a path.
- All three tools share one Anthropic client and one `.env` — there's no
  per-tool auth or rate-limiting story here yet.
