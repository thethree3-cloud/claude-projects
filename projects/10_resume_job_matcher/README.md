# Project 10 — Resume & Job Matcher

A personal job-search tool: parse a resume and a job listing into structured
data, then (later slices) match them and score the fit with an explainable,
evidence-backed rubric.

Same architecture as Projects 04 / 11 / 14: **the LLM does judgment, Python
does the deterministic work.** Here in Slice 1 that means Claude reads free
text and returns structured data whose *shape* is guaranteed by a JSON schema
— the calling code always gets a plain dict and never touches the API.

## Status — Slice 1: parsing plumbing

Built and tested:

| File | What it does |
| --- | --- |
| `llm_client.py` | Shared lazy Anthropic client + `extract_json(prompt, schema)` — one schema-constrained Claude call, returns a parsed dict. |
| `parse_resume.py` | `parse_resume(text)` → `{name, summary, skills, experience[], education[], total_years_experience}`. |
| `parse_job.py` | `parse_job(text)` → `{title, company, required_skills[], preferred_skills[], min_years_experience, education_requirement, responsibilities[]}`. |
| `sample_data.py` | Writes a fictional sample resume + job listing into `data/`. |
| `test_parse_resume.py`, `test_parse_job.py` | 7 offline tests (mocked client, no API key needed). |

**Grounding discipline** (the same principle as Project 14): both prompts tell
Claude to extract *only what's on the page* — no inferring skills from a job
title, no guessing dates from seniority. A later matching slice scores the
resume against the job, so it must not be scoring against skills the candidate
never actually claimed.

**The one real judgment call in Slice 1:** `parse_job.py` splits requirements
into `required_skills` vs. `preferred_skills` based on how the listing frames
them ("must have" / "X+ years" vs. "nice to have" / "bonus"). A later scoring
slice weights those buckets differently, so the split matters. Ambiguous items
default to required.

### Run it

```bash
python sample_data.py          # writes data/sample_resume.txt + data/sample_job.txt
python -m unittest discover     # 7 tests, offline
```

```python
from pathlib import Path
from parse_resume import parse_resume
from parse_job import parse_job

resume = parse_resume(Path("data/sample_resume.txt").read_text())
job = parse_job(Path("data/sample_job.txt").read_text())
```

Model: `claude-haiku-4-5-20251001`, matching the rest of the portfolio.
Needs `ANTHROPIC_API_KEY` in the repo-root `.env`.

Your real resume can go in `data/` — that directory is gitignored and never
committed. The sample data is fully fictional (invented people, companies,
dates).

## Deferred to later slices

- **`match.py`** — per job requirement, is it evidenced in the resume? One
  evidence-detection call per requirement, returning a supporting quote (same
  enum-constrained pattern as Project 14's `score_fit.py`).
- **`score.py`** — Python only: weight required vs. preferred matches, compute
  a 0–100 fit score and a band (Strong / Possible / Weak). Arithmetic stays
  out of the LLM call.
- **`report.py`** — the gap list: unmet requirements + suggested resume edits.
- **`pipeline.py`** — wire parse → match → score → report into one call.
