# AI Agent Portfolio

Open-source LLM agents built with Python and the Anthropic Claude API — a
self-directed portfolio moving from enterprise IT into AI engineering.

Every project follows the same principle: **the LLM does judgment, Python does
the deterministic work**, and every factual claim is grounded in a real source
the caller can check. Each folder is a standalone project with its own README,
tests, and setup notes.

**Stack:** Python · Anthropic Claude API · Model Context Protocol (MCP) ·
retrieval-augmented generation · structured outputs / tool use · SQL Server ·
Docker · Streamlit · GitHub Actions CI

---

## Projects

### [11 — Natural-Language SQL Reporting Agent](projects/11_sql_reporting_agent)
Answers plain-English reporting questions against a real SQL Server database:
generates SQL with Claude, runs it read-only, and summarizes the result in
plain language. **Safety is the point** — two independent write-prevention
layers: a `db_datareader`-only login that physically cannot write, plus a
separate SELECT-only validator checked immediately before execution. Packaged
as an MCP server. GitHub Actions CI, 30 tests.
`Python · SQL Server · pyodbc · Docker · MCP`

### [14 — Sales Prospecting & Lead-Routing Agent](projects/14_sales_prospecting_agent)
Triages a trade-show exhibitor list into scored, territory-routed sales leads,
grounding every fact in a cited source (a specific PDF page or a web search).
Live HubSpot CRM integration (companies, deals, contacts, notes), driven by an
HMAC-verified inbound webhook so it reacts to new records on its own. Streamlit
lead-triage dashboard. 11 build slices, 130+ tests.
`Python · Claude API · HubSpot REST API · Flask webhooks · PyMuPDF · Streamlit`

### [10 — Résumé & Job Matcher](projects/10_resume_job_matcher)
Parses a résumé and a job posting into structured data, scores fit against a
weighted rubric where every matched skill must be quoted from the résumé, and
writes an honest gap analysis that never suggests claiming an unearned skill.
Searches ~30 job boards live via Claude's web-search and web-fetch tools, with
regional presets. CLI + Streamlit UI, 50 tests.
`Python · Claude API · web search + fetch tools · Streamlit`

### [04 — AS9100 Audit & Document-Comparison Agents](projects/04_as9100_audit_agent)
Two quality-audit-support tools. One checks internal documents against a
clause checklist; the other matches an uploaded reference document to an
internal registry and reports gaps in hedged, non-certifying language
(missing step → execution risk; missing control → consistency risk; …).
A from-scratch rebuild of a production Copilot Studio design, on fictional data.
`Python · Claude API · structured outputs`

### [06 — MCP Agent Tool Server](projects/06_mcp_agent_server)
Exposes the tested agent logic from Projects 01 and 04 as MCP tools any client
(Claude Code, Claude Desktop, …) can call directly — no terminal, no UI.
Verified against a real MCP client over stdio.
`Python · Model Context Protocol`

### [01 — HR & Policy Guidebook Lookup Agent](projects/01_guidebook_agent)
Answers natural-language questions about an employee handbook by routing the
question to the relevant table-of-contents section(s), then grounding the
answer strictly in that section's text — a lightweight retrieval design with
no vector database. Streamlit chat UI.
`Python · Claude API · retrieval · Streamlit`

---

## Running a project

Each project has its own README with setup steps. In general:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Projects that call the Claude API read `ANTHROPIC_API_KEY` from a `.env` file
at the repo root. Test suites run offline (mocked API) unless a README says
otherwise:

```bash
cd projects/<project> && python -m unittest discover
```

---

*Also in this repo: `projects/00_python_learning`, `python_fundamentals`, and
`benefits_pdf_practice` are early practice exercises, kept for reference.*
