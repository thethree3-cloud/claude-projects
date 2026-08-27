# Project 10 — Resume & Job Matcher

A personal job-search tool: parse a resume and a job listing into structured
data, match them requirement-by-requirement, and score the fit with an
explainable, evidence-backed rubric.

Same architecture as Projects 04 / 11 / 14: **the LLM does judgment, Python
does the deterministic work.** Claude reads free text (parsing) and detects
evidence (matching); Python owns every schema, every comparison, and all the
scoring arithmetic.

## Status — Slice 2: matching + scoring

`parse_resume` / `parse_job` → `match.match_requirements(resume, job)` →
`score.score_comparison(comparison)`.

| File | What it does |
| --- | --- |
| `match.py` | `match_requirements(resume, job)` → a "comparison" dict: per required/preferred skill `{skill, met, evidence}`, a years-of-experience check, an education check. One enum-constrained Claude call does skill evidence-detection + the education judgment; the years check is pure Python. |
| `score.py` | `score_comparison(comparison)` → `{score, band, breakdown}`. Pure arithmetic, no LLM. Weights: required skills 60, years 20, preferred skills 15, education 5 (sum 100). Bands: Strong ≥ 75, Possible ≥ 45, Weak below. `breakdown` shows each component's points/max/detail so a score is never opaque. |
| `test_match.py` (6) / `test_score.py` (8) | `test_score.py` is pure (zero mocks); `test_match.py` mocks the client. |

**Grounding** (same as Slice 1 and Project 14): `match.py` gives Claude no
tools — it can only mark a skill "met" if it can quote the résumé for it.
A skill that's merely plausible for the candidate's background doesn't count.
Absence of evidence = not met.

**Known limitation carried over from Project 14:** the evidence quote is only
guaranteed to come from the résumé, not to be a *strong* quote — a skill
that's simply listed in a "Skills:" line will match with that line as its
evidence. A stricter version would weight "named in a bullet with context"
above "appears in a skills list."

Live smoke test (sample data): `Jordan Rivera` vs `Junior AI Engineer` →
**91 / Strong** (4/4 required skills, 5 yrs vs 2 required, 2/5 preferred,
education met via "equivalent experience").

```python
from pathlib import Path
from parse_resume import parse_resume
from parse_job import parse_job
from match import match_requirements
from score import score_comparison

resume = parse_resume(Path("data/sample_resume.txt").read_text())
job = parse_job(Path("data/sample_job.txt").read_text())
result = score_comparison(match_requirements(resume, job))
```

## Slice 1: parsing plumbing

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
python -m unittest discover     # 21 tests, offline
```

Model: `claude-haiku-4-5-20251001`, matching the rest of the portfolio.
Needs `ANTHROPIC_API_KEY` in the repo-root `.env`.

Your real resume can go in `data/` — that directory is gitignored and never
committed. The sample data is fully fictional (invented people, companies,
dates).

## Deferred to later slices

- **`report.py`** — turn a low/borderline `score_comparison` result into a gap
  list: which required skills are unmet, and suggested résumé edits.
- **`pipeline.py`** — wire parse → match → score → report into one call, plus a
  small CLI/driver over a folder of job listings.
