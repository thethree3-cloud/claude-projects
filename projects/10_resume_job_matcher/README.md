# Project 10 — Resume & Job Matcher

A personal job-search tool: parse a resume and a job listing into structured
data, match them requirement-by-requirement, and score the fit with an
explainable, evidence-backed rubric.

Same architecture as Projects 04 / 11 / 14: **the LLM does judgment, Python
does the deterministic work.** Claude reads free text (parsing) and detects
evidence (matching); Python owns every schema, every comparison, and all the
scoring arithmetic.

## Status — 4 slices + a résumé builder

Full chain: `pipeline.evaluate_fit(resume_text, job_text)` →
`parse_resume` / `parse_job` → `match.match_requirements` →
`report.build_report`.

Slice 5 reuses that chain: `pipeline.tailor_fit(resume_text, job_text)` →
`tailor_resume.build_tailored_resume` → a résumé **reframed** for the listing
(Markdown out, plus a "what changed" list).

| File | What it does |
| --- | --- |
| `parse_resume.py` / `parse_job.py` | Free text → structured dict, JSON-schema-constrained Claude call. `parse_job` splits `required_skills` vs `preferred_skills` by framing language. |
| `match.py` | `match_requirements(resume, job)` → a "comparison" dict: per required/preferred skill `{skill, met, evidence}`, a years check, an education check. One enum-constrained Claude call does skill evidence-detection + the education judgment; the years check is pure Python. |
| `score.py` | `score_comparison(comparison)` → `{score, band, breakdown}`. Pure arithmetic, no LLM. Weights: required 60 / years 20 / preferred 15 / education 5 (sum 100). Bands: Strong ≥ 75, Possible ≥ 45, Weak below. `breakdown` shows each component's points/max/detail. |
| `report.py` | `find_gaps(comparison)` (pure) → unmet skills, years shortfall, education. `build_report(comparison, resume, job)` adds the score and one LLM call for suggestions. `format_report(report)` renders it to text (pure). |
| `pipeline.py` | `evaluate_fit(resume_text, job_text)` — raw text → finished report in one call. `tailor_fit(resume_text, job_text)` — raw text → a résumé reframed for the listing. `rank_fits(reports)` — pure, orders a batch best-first. |
| `tailor_resume.py` | `build_tailored_resume(comparison, resume, job)` → `{resume, markdown, changes}`. One enum-constrained Claude call rewrites the summary, reorders skills + roles job-relevant-first, and re-words existing bullets. `assemble()` (pure) then locks each role's title/org/dates to the real source role (by index), re-appends any role the model dropped, and filters any skill not in the résumé. `render_markdown()` is pure. |
| `job_sites.py` | The curated list of ~30 job boards `job_search` searches, grouped (aggregators / tech / AI-ML / remote / government / ATS). `FETCHABLE` = the subset that fetches cleanly. `LOCAL_PRESETS` adds region-specific boards + a default location/radius (Salt Lake City ships as one). |
| `job_search.py` | `search_jobs(keywords, location, radius_miles, count)` → live postings via Claude's `web_search` (restricted to `job_sites`) + `web_fetch` (full posting text). Returns `{title, company, location, url, description, grounding}`; `grounding` is `"full posting"` or `"search snippet"`. `description` is what you feed to `evaluate_fit`. |
| `run_job_folder.py` | Driver (not tested): runs one résumé against a folder of `.txt` listings, prints a ranked table + each full report. |
| `run_job_search.py` | Driver (not tested): `search_jobs` for postings near a location (default: the résumé's own), scores each, prints ranked with the posting URL + grounding. |
| `streamlit_app.py` | UI, two modes. **Score one listing:** paste a résumé + a job listing → score, breakdown, gaps (badges), suggestions (labelled), skill-by-skill evidence, text download — plus a **Build tailored résumé** button → Markdown preview, a "what changed" list, and a `.md` download. **Search live jobs:** paste a résumé + keywords + location (or a "Search area" preset like Salt Lake City) → ranked results table, row-select for the full report + a link to the posting. |
| `test_*.py` (63 total) | `test_score.py`, `test_pipeline.py`'s `rank_fits` tests, the `find_gaps`/`format_report`/`job_sites` tests, `test_tailor_resume.py`'s `assemble`/`render_markdown` tests, and `test_streamlit_app.py` (via `AppTest`) are pure; the rest mock the client. |

**Grounding** (same as every slice and Project 14): `match.py` gives Claude no
tools — a skill is "met" only if it can be quoted from the résumé.
`report.py`'s suggestion prompt goes further: it classifies each gap as
`surface_it_better` / `adjacent_experience` / `genuine_gap` and is **forbidden
from suggesting the candidate claim anything the résumé doesn't support** — the
goal is a stronger honest résumé, not a padded one.

**Known limitation carried over from Project 14:** the evidence quote is only
guaranteed to come from the résumé, not to be a *strong* quote — a skill
simply listed in a "Skills:" line matches with that line as its evidence.

Live driver run (sample data, `Jordan Rivera` résumé vs `data/sample_jobs/`):
Junior AI Engineer **88/Strong**, Data Analyst **88/Strong**, Senior ML
Research Scientist **20/Weak** (PhD + publications + PyTorch = genuine gaps).
Suggestions stay honest — "build a public project," "take a short course," "be
direct in interviews that you're transitioning."

```python
from pathlib import Path
from pipeline import evaluate_fit
from report import format_report

resume_text = Path("data/sample_resume.txt").read_text()
job_text = Path("data/sample_job.txt").read_text()
print(format_report(evaluate_fit(resume_text, job_text)))
```

```bash
python run_job_folder.py data/sample_resume.txt data/sample_jobs/
```

## Tailored résumé builder (slice 5)

`tailor_fit(resume_text, job_text)` (or the **Build tailored résumé** button in
the Streamlit "Score one listing" mode) reframes the résumé for one listing:

```python
from pathlib import Path
from pipeline import tailor_fit

out = tailor_fit(Path("data/sample_resume.txt").read_text(),
                 Path("data/sample_job.txt").read_text())
print(out["markdown"])          # the reframed résumé
for change in out["changes"]:   # a plain-language audit list
    print("-", change)
```

**It reframes, it does not fabricate.** It rewrites the summary, reorders
skills and roles so the job-relevant material leads, and re-words existing
bullets in the listing's vocabulary. The LLM/Python split carries the promise:

- *Schema* — each tailored role references a real source role **by index**
  (`source_index`), and skills are **enum-constrained** to the résumé's own
  list, so the model can only reorder and re-word.
- *`assemble()` (pure Python)* — title / organisation / dates are copied from
  the source role by that index (the model can't drift them); any role the
  model dropped is re-appended untouched (no job silently lost); any "skill"
  not in the résumé is filtered out.
- *Prompt* — forbids adding a metric or accomplishment not already in the
  bullet text, and asks for every change to be logged in `changes`.

**Known limitations:**

- The tailored résumé carries only what `parse_resume` extracts — **no email,
  phone, links, or certifications**. Paste those back before sending.
- Re-worded bullet *text* is the model's; the structural guarantees above
  don't police a bullet that's been over-polished. The `changes` list is there
  so you can check every edit.

## Live job search

`job_search.search_jobs(keywords, location, radius_miles, count)` finds real
postings so you don't have to paste them in one at a time:

```python
from job_search import search_jobs

jobs = search_jobs("junior AI engineer or Python developer", "Portland, Oregon",
                   radius_miles=30, count=10)
# -> [{title, company, location, url, description, grounding}, ...]
# feed each job["description"] to pipeline.evaluate_fit
```

```bash
# search + score in one shot (location defaults to the résumé's own)
python run_job_search.py data/sample_resume.txt "Python developer or data analyst" --radius 30 --count 8

# a regional preset adds local boards + its own default location/radius
python run_job_search.py data/sample_resume.txt "compliance analyst" --preset "Salt Lake City"
```

`parse_resume` extracts a `location` field so the résumé's own city/state is
the default search area.

**Regional presets** (`job_sites.LOCAL_PRESETS`) bolt a set of local boards
onto `ALL_JOB_SITES` and set a default location + radius. **Salt Lake City**
adds `jobs.utah.gov` + `statejobs.utah.gov` (state), `governmentjobs.com` +
`careers-slco.icims.com` (county/city), `jobs.ksl.com` + `classifieds.ksl.com`
(KSL), `siliconslopes.com` + `siliconslopesjobs.com` (tech), and `utah.edu`,
at a 25-mile radius. The Streamlit search mode has a "Search area" dropdown for
the same thing. Add a region by extending the dict.

Two Claude calls, the same split as Project 14 (`web_search_agent.search` →
`score_fit`): (1) an agentic search — `web_search` restricted via
`allowed_domains` to `job_sites.py`, then `web_fetch` on the promising results —
that writes its findings as plain text; (2) a plain call, no tools, that
structures that text against the JSON schema. Combining structured output with
the server tools in one call proved to throw intermittent `400`s, so they're
separated. Forced-first-tool discipline as in Project 14 (`tool_choice: any` on
turn 1, since Haiku won't reliably search on its own).

**Why not the Indeed / LinkedIn API:** Indeed closed its job-search API to new
partners in 2023 and LinkedIn never had one; scraping either breaks constantly
behind bot protection. Web search reaches their *listings* when they surface in
results, and this project won't scrape.

**Known limitations** (flagged, not hidden — same spirit as Project 14):

- **Fetch reliability varies by site.** ATS pages (Greenhouse, Lever, Ashby…)
  and `usajobs.gov` fetch cleanly with the whole posting. Aggregators fight
  automated fetches; those fall back to the shorter search snippet and are
  marked `grounding: "search snippet"` — treat their fit scores as directional.
- **The URL isn't always canonical.** For an aggregator result the model
  sometimes returns the search-results page rather than the specific posting's
  permalink.
- **`grounding: "full posting"` is the model's own call** and can be optimistic
  when a fetched page was itself a truncated preview.
- **Snippet postings carry only requirements text**, no title/company/location
  header. The drivers prepend the search result's own title/company/location
  before `parse_job` and trust those over what `parse_job` infers.

Live run (`"junior AI engineer or Python developer"`, Portland OR, count 6):
6 real postings in ~70s from dice.com / glassdoor.com / indeed.com, most with
full descriptions.

## Run it

```bash
python sample_data.py        # writes data/sample_resume.txt, data/sample_job.txt, data/sample_jobs/
python -m unittest discover   # 63 tests, offline
python run_job_folder.py data/sample_resume.txt data/sample_jobs/   # live CLI, needs API key
streamlit run streamlit_app.py                                      # live UI, needs API key
```

Model: `claude-haiku-4-5-20251001`, matching the rest of the portfolio.
Needs `ANTHROPIC_API_KEY` in the repo-root `.env`.

Your real résumé and real job listings go in `data/` — that directory is
gitignored and never committed. The sample data is fully fictional (invented
people, companies, dates).

## Design notes

- **`llm_client.extract_json(prompt, schema)`** is the single API surface —
  one schema-constrained call, returns a parsed dict. Every other module is a
  schema + a prompt + a thin wrapper.
- **Grounding runs through the whole pipeline.** Parsing extracts only what's
  on the page (no inferring skills from a job title). Matching only marks a
  skill met if it can quote the résumé. The report never suggests claiming
  something unsupported.
- **The LLM/Python split:** five Claude calls do judgment (parse résumé, parse
  job, detect skill evidence, suggest improvements, reframe the résumé).
  Everything else — required-vs-preferred bucketing, the years comparison, all
  scoring arithmetic, gap extraction, ranking, and locking the tailored
  résumé's roles/skills to the source — is pure Python, unit-tested without
  mocks.
