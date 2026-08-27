# Project 10 — Resume & Job Matcher

A personal job-search tool: parse a resume and a job listing into structured
data, match them requirement-by-requirement, and score the fit with an
explainable, evidence-backed rubric.

Same architecture as Projects 04 / 11 / 14: **the LLM does judgment, Python
does the deterministic work.** Claude reads free text (parsing) and detects
evidence (matching); Python owns every schema, every comparison, and all the
scoring arithmetic.

## Status — Slice 3: gap report

Full chain: `parse_resume` / `parse_job` → `match.match_requirements` →
`report.build_report` → `report.format_report`.

| File | What it does |
| --- | --- |
| `match.py` | `match_requirements(resume, job)` → a "comparison" dict: per required/preferred skill `{skill, met, evidence}`, a years check, an education check. One enum-constrained Claude call does skill evidence-detection + the education judgment; the years check is pure Python. |
| `score.py` | `score_comparison(comparison)` → `{score, band, breakdown}`. Pure arithmetic, no LLM. Weights: required 60 / years 20 / preferred 15 / education 5 (sum 100). Bands: Strong ≥ 75, Possible ≥ 45, Weak below. `breakdown` shows each component's points/max/detail. |
| `report.py` | `find_gaps(comparison)` (pure) → unmet skills, years shortfall, education. `build_report(comparison, resume, job)` adds the score and one LLM call for suggestions. `format_report(report)` renders it to text (pure). |
| `test_match.py` (6) / `test_score.py` (8) / `test_report.py` (8) | `test_score.py` and the `find_gaps`/`format_report` tests are pure; the rest mock the client. |

**Grounding** (same as every slice and Project 14): `match.py` gives Claude no
tools — a skill is "met" only if it can be quoted from the résumé.
`report.py`'s suggestion prompt goes further: it classifies each gap as
`surface_it_better` / `adjacent_experience` / `genuine_gap` and is **forbidden
from suggesting the candidate claim anything the résumé doesn't support** — the
goal is a stronger honest résumé, not a padded one.

**Known limitation carried over from Project 14:** the evidence quote is only
guaranteed to come from the résumé, not to be a *strong* quote — a skill
simply listed in a "Skills:" line matches with that line as its evidence.

Live smoke test (sample data): `Jordan Rivera` vs `Junior AI Engineer` →
**~88–91 / Strong**; report flags the LLM-API skills as genuine gaps (with
"build a small public project" advice, not "claim it") and the manufacturing
background as adjacent experience worth reframing.

```python
from pathlib import Path
from parse_resume import parse_resume
from parse_job import parse_job
from match import match_requirements
from report import build_report, format_report

resume = parse_resume(Path("data/sample_resume.txt").read_text())
job = parse_job(Path("data/sample_job.txt").read_text())
report = build_report(match_requirements(resume, job), resume, job)
print(format_report(report))
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
python -m unittest discover     # 29 tests, offline
```

Model: `claude-haiku-4-5-20251001`, matching the rest of the portfolio.
Needs `ANTHROPIC_API_KEY` in the repo-root `.env`.

Your real resume can go in `data/` — that directory is gitignored and never
committed. The sample data is fully fictional (invented people, companies,
dates).

## Deferred to later slices

- **`pipeline.py`** — wire parse → match → report into one call, plus a small
  CLI/driver that runs one résumé against a folder of job listings and ranks
  them.
