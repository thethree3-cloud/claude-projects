# SQL Server / AdventureWorks Natural-Language Reporting Agent

An MCP agent that answers plain-English reporting questions ("what's the
top-selling item?") against a real SQL Server database by generating SQL
with Claude, executing it, and summarizing the result back in plain
language. Runs against Microsoft's free **AdventureWorks2022** sample
database in a local Docker container.

## Why this exists

Every other project in this portfolio follows the same shape: route or
match a question, then answer from retrieved text. This one is
deliberately different — it generates and executes code (SQL) from a
natural-language question, which is a fundamentally different (and
riskier) pattern than retrieval. That risk is the actual point of the
project: it's a concrete, working demonstration of how to let an LLM
touch a real database safely, not just a NL-to-SQL demo.

## Safety design — two independent layers

The core design decision, made before any code was written: the agent
must be **structurally incapable** of writing to the database, not just
instructed not to.

1. **Database-enforced (`setup_readonly_login.py`)** — the agent
   connects through a dedicated SQL Server login (`nlreport_reader`)
   with only the built-in `db_datareader` role: SELECT everywhere,
   nothing else. Verified live by attempting a real `INSERT` through
   that login and confirming SQL Server itself rejects it. This holds
   even if every other layer below has a bug.
2. **Validation-enforced (`validate_sql.py`)** — every generated query is
   independently checked before it's allowed to run: must start with
   `SELECT`/`WITH`, exactly one statement (no chained `;`), no
   `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/EXEC/…` keywords, no
   `sp_`/`xp_` stored-procedure calls, no `SELECT ... INTO` (which would
   create a table). String literals are blanked out before scanning so
   legitimate text like `WHERE Name LIKE '%update%'` isn't falsely
   rejected. Re-run again inside `execute_sql.py` immediately before
   execution, so the check happens at the actual point of risk, not just
   upstream.

Prompt-level instructions to the SQL-generation model ("only write a
SELECT") are a *third*, non-authoritative layer — worth having, but
never trusted as the actual control. Testing this live surfaced a good
example: asking to "delete all products that haven't sold anything" made
the model decline the delete on its own and return a safe SELECT/COUNT
instead — encouraging, but not something the design relies on.

## Pipeline

```
question
  │
  ▼
generate_sql.py   -- Claude call #1: question + schema context → candidate SQL
  │
  ▼
execute_sql.py    -- re-validates (validate_sql.py), runs via read-only login,
  │                  caps at 200 rows, 15s query timeout
  ▼
summarize.py      -- Claude call #2: result set (+ SQL for grounding) → plain-
  │                  language answer
  ▼
run_report.py     -- run_report(question): wires the above into one call,
                      translates every failure mode into a readable message
```

`schema.py` runs separately, ahead of time (not per-question) — it
introspects `INFORMATION_SCHEMA` + `sys.foreign_keys` once and writes
`data/schema_context.txt`, which `generate_sql.py` reads on every call.
The foreign-key relationships in that file are what let the model
generate correct joins (e.g. `SalesOrderHeader` → `Person`) without
guessing at column names.

`server.py` wraps `run_report()` and `list_schema()` as MCP tools,
following the same wrapping pattern Project 06 used for Projects 01 and
04 — the business logic was fully built and tested standalone first;
the MCP layer adds nothing but the protocol wrapper.

## Infrastructure

- **SQL Server 2022 (Developer Edition)** running in Docker, container
  `adventureworks-sql`, with a persistent named volume
  (`adventureworks-data`) and `--restart unless-stopped` — survives
  container restarts, daemon restarts, and reboots. Data is only lost by
  explicitly deleting the volume.
- **AdventureWorks2022** restored from Microsoft's official `.bak`
  release (71 tables, 744 columns across `dbo`, `HumanResources`,
  `Person`, `Production`, `Purchasing`, `Sales`).
- Connection details (`sa` password, read-only login, host/port/database)
  live in the gitignored root `.env`, loaded the same way every other
  project in this portfolio loads `ANTHROPIC_API_KEY`.

## Setup

Assumes Docker, the SQL Server container, and AdventureWorks are already
running (see infrastructure above).

```bash
pip install -r ../../requirements.txt
python setup_readonly_login.py   # one-time: creates the read-only login, idempotent
python schema.py                 # builds data/schema_context.txt
```

## Running it

CLI, one question at a time:

```bash
python run_report.py "What are the top 5 best-selling products by quantity?"
```

As an MCP server, registered with Claude Code the same way as Project 06:

```bash
claude mcp add sql-reporting-agent -- <path-to-venv-python> <path-to-server.py>
```

Then, from a Claude Code session started inside this repo, just ask a
question naturally — Claude calls `run_sql_report` (and `list_database_schema`
if it needs to check what's queryable first).

## Tests

```bash
python -m unittest discover -p "test_*.py" -v
```

30 tests, all pure/mocked — no API key, database, or network access
needed, same convention as Project 04's `test_agents.py`:

- `test_validate_sql.py` — the SELECT-only validator, including that
  legitimate string literals containing forbidden words aren't falsely
  rejected, and that chained/comment-smuggled statements are caught.
- `test_generate_sql.py` — markdown-fence stripping and semicolon
  trimming on the model's raw SQL output.
- `test_summarize.py` — result-table formatting (empty results, `None`
  values, non-string types like `Decimal`).
- `test_run_report.py` — the full pipeline's error-translation logic,
  with `generate_sql`/`execute_query`/`summarize` mocked out so the
  chaining and message-formatting logic is what's actually under test.

## Known limitations

- **Category vs. subcategory confusion**: AdventureWorks splits products
  into `ProductCategory` (e.g. "Bikes") and `ProductSubcategory` (e.g.
  "Mountain Bikes"). Asking about the "Bikes subcategory" generates SQL
  that correctly queries `ProductSubcategory.Name = 'Bikes'`, matches
  zero rows (because "Bikes" is a category, not a subcategory), and the
  agent honestly reports no data rather than guessing — but it doesn't
  recognize the user probably meant the category. A richer schema
  context (e.g. listing actual category/subcategory values) would fix
  this; not implemented, to keep schema.py's scope to structure rather
  than data-value awareness.
- **No self-correction loop**: if `generate_sql` produces SQL that fails
  at execution (bad column name, syntax error), `run_report` reports the
  failure rather than feeding the error back for a retry. A production
  version would likely add one bounded retry with the error as context.
- **Summarization only sees the capped result set**: for questions
  matching more than 200 rows, `summarize()` knows results were
  truncated but not the true total — it reports "more than 200" rather
  than an exact count, even when an exact count would need a second,
  differently-shaped query (e.g. `COUNT(*)`) to get honestly.
- **Two Claude calls per question**, same as Project 01/04's pattern —
  latency is a few seconds, not instant.
