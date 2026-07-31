# Sales Prospecting Agent — Slice 1: Search Plumbing

**Status: Slice 1 of a multi-session build.** This is the search/extraction
plumbing only — no fit scoring, no salesperson routing, no CRM export yet.
See "What's deferred" below before assuming this does more than it does.

Genericized, open-source rebuild of a real sales-prospecting/lead-routing
agent originally built in Copilot Studio. The real product it supports is
hardened protective cases — used across aerospace, defense, energy, medical,
and telecom, wherever sensitive equipment needs a rugged enclosure. The real
agent's core value: triage a large trade-show exhibitor list down to
strong-fit companies so salespeople spend limited floor time on the booths
worth visiting, instead of walking the whole show cold. All company names and
sample data here are **fictional** — generated for testing, never real
Zerocases or customer data (same approach as Project 04).

## Why this exists

Real salespeople were trained on the original tool and asked for a release
date — genuine demand, not a hypothetical. It never shipped because
executives wouldn't approve the Copilot Studio token/licensing budget for the
sales team to use it, not because the tool didn't work. This project rebuilds
the same concept from scratch as open-source Python, unblocked by that
licensing constraint.

## What this slice does

Two input modes feed the same underlying search call:

1. **Trade-show exhibitor list** — `extract_exhibitors.py` pulls company
   names out of a numbered exhibitor-list PDF (`generate_sample_data.py`
   writes a fictional one to test against).
2. **Geo-radius search** — a plain natural-language query like
   `"manufacturing businesses within 10 miles of Dallas, TX"`, no PDF
   required.

Both modes call the same `web_search_agent.search(query)` — it's one
function, not two, since a geo-radius query and a company-name lookup are
just different query text into the same Anthropic web-search tool call.

```bash
python generate_sample_data.py
python -c "from extract_exhibitors import extract_company_names; print(extract_company_names('data/sample_expo_exhibitors.pdf'))"
python -c "from web_search_agent import search; print(search('manufacturing businesses within 10 miles of Dallas, TX'))"
```

### Model and tool version

Uses `claude-haiku-4-5-20251001` (same cost-conscious choice as Projects
01/04/11) with the **basic** `web_search_20250305` tool. Haiku 4.5 isn't in
the model family that supports the newer dynamic-filtering
`web_search_20260209` variant (that needs Opus 4.8/4.7/4.6, Sonnet 5, or
Sonnet 4.6) — using the basic tool avoids a silent capability mismatch.

Server-side web search runs its own internal search loop before returning;
if it hits the internal round limit it comes back with `stop_reason:
"pause_turn"` instead of a final answer. `web_search_agent.search()` handles
this by re-sending the same question plus the paused assistant turn (capped
at `MAX_TOOL_ROUNDS` retries) — it does not append a new "continue" message,
since the trailing tool-use block is what signals the API to resume.

**Important finding from the live smoke test:** with default `tool_choice`
(auto), Haiku 4.5 answered "I don't have a tool to search for that" and
never called `web_search` at all — even with an explicit system-prompt
instruction telling it to always search. Forcing the tool
(`tool_choice={"type": "tool", "name": "web_search"}`) fixed it immediately
and returned real, cited results. `web_search_agent.py` forces the tool for
this reason — it's not a style choice, it's what makes this project's
grounding requirement (every claim traces to an actual search) actually
true rather than just requested in a prompt.

## Setup

```bash
pip install -r requirements.txt
```

Requires `ANTHROPIC_API_KEY` in a `.env` file at the repo root. `data/` is
gitignored — regenerate the sample exhibitor list anytime with
`generate_sample_data.py`.

## Tests

```bash
python -m unittest test_extract_exhibitors.py test_web_search_agent.py -v
```

`test_extract_exhibitors.py` runs against a real generated PDF (no API
calls). `test_web_search_agent.py` mocks `client.messages.create` entirely —
no live API calls or network access needed, including the `pause_turn` retry
path. To actually confirm the tool works end to end (not just that the retry
logic is correct), run the live smoke test in the Setup command above with a
real API key.

## What's deferred to later sessions

- **Fit scoring** — comparing each company against an uploadable
  `client_profile.yaml` and producing a 0–100 score with a High/Medium/Low
  band and cited evidence per claim, not just categorical judgment.
- **Salesperson routing** — matching a company's location against
  `territory_routing.csv` and assigning a salesperson/territory.
- **Agent 2 (CRM export)** — a separate step that formats leads into a CSV
  shaped for a target CRM's import feature and flags matches against an
  `existing_customers.csv` reference file. No live CRM API integration is
  planned — Alan confirmed the real version was CSV export, not an API call.

## Known limitations (this slice)

- `web_search_agent.search()` returns Claude's free-text answer only — no
  structured extraction of company websites, addresses, or per-claim source
  URLs yet. That structure is part of the fit-scoring work above, not this
  slice.
- `extract_company_names()` assumes a flat `N. Company Name` numbered list —
  it doesn't handle exhibitor lists formatted as tables, multi-column
  layouts, or booth-number-prefixed entries.
