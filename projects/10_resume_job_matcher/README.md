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

Slice 5 reuses that chain two ways: `pipeline.tailor_fit()` →
`tailor_resume.build_tailored_resume` → a résumé **reframed** for the listing,
and `pipeline.cover_letter_fit()` → `cover_letter.build_cover_letter` → a
**grounded cover letter**. Both run a second Claude call that audits the
output against the résumé.

Résumé input is a file upload (PDF / DOCX / txt, via `resume_source.py`) or a
paste; `parse_resume` now also captures contact details and certifications.
The tailored résumé downloads as Markdown, **PDF, or Word** (`resume_export.py`).

| File | What it does |
| --- | --- |
| `parse_resume.py` / `parse_job.py` | Free text → structured dict, JSON-schema-constrained Claude call. `parse_resume` captures contact (email/phone/links) and certifications alongside skills/experience/education, then **recomputes `total_years_experience` in Python** (`tenure.py`) from the extracted date ranges. `parse_job` splits `required_skills` vs `preferred_skills` by framing language. |
| `tenure.py` | `total_years(experience)` (pure) — parses each role's `dates` string ("Feb 2021 - Present", "2019 – 2021", "03/2020 - 06/2020", …) and sums the ranges, merging overlaps so concurrent roles aren't double-counted. Returns `None` when too few ranges parse, and `parse_resume` keeps the model's estimate. |
| `resume_source.py` | `extract_text(data, filename)` — résumé file → plain text for `parse_resume`. PDF via PyMuPDF; `.docx` via python-docx when installed, else a small built-in `word/document.xml` reader (no extra dependency); `.txt`/`.md` decoded. |
| `resume_export.py` | `to_pdf(resume)` / `to_docx(resume)` — an assembled résumé dict → downloadable bytes. PDF via fpdf2 (Latin-1, punctuation sanitised); DOCX written directly as WordprocessingML in a zip (no python-docx). Both are ATS-plain: one column, standard fonts, real headings, no tables. |
| `match.py` | `match_requirements(resume, job)` → a "comparison" dict: per required/preferred skill `{skill, met, evidence}`, a years check, an education check. One enum-constrained Claude call does skill evidence-detection + the education judgment; the years check is pure Python. |
| `score.py` | `score_comparison(comparison)` → `{score, band, breakdown}`. Pure arithmetic, no LLM. Weights: required 60 / years 20 / preferred 15 / education 5 (sum 100). Bands: Strong ≥ 75, Possible ≥ 45, Weak below. `breakdown` shows each component's points/max/detail. `projected(comparison)` → `{current, if_all_closed, per_gap}` — what the score becomes if each gap is closed, one at a time and all together. |
| `report.py` | `find_gaps(comparison)` (pure) → unmet skills, years shortfall, education. `build_report(comparison, resume, job)` adds the score, the `projection`, and one LLM call for suggestions. `format_report(report)` renders it to text (pure). |
| `pipeline.py` | `evaluate_fit()` — raw text → finished report. `tailor_fit()` — raw text → a résumé reframed for the listing (`{resume, markdown, changes, flags, diff}`). `cover_letter_fit()` — raw text → a grounded cover letter (`{text, paragraphs, greeting, claims, flags}`). `rank_fits(reports)` — pure, orders a batch best-first. |
| `tailor_resume.py` | `build_tailored_resume(comparison, resume, job)` → `{resume, markdown, changes, flags, diff}`. One enum-constrained Claude call rewrites the summary, reorders skills + roles job-relevant-first, and re-words existing bullets; a second call — `verify_bullets()` — audits each rewritten bullet against its source role and any that overreach are dropped into `flags`. `assemble()` (pure) locks each role's title/org/dates to the real source role (by index), re-appends any dropped role, and filters any skill not in the résumé. `build_diff()` / `render_markdown()` are pure. |
| `cover_letter.py` | `build_cover_letter(comparison, resume, job)` → `{text, paragraphs, greeting, claims, flags}`. `write_cover_letter()` drafts three grounded paragraphs and lists every claim it makes about the candidate with the résumé phrase behind it; `verify_claims()` (second call) flags any claim that goes beyond the résumé (invented skill, or overstated scope/seniority/duration). Prose isn't auto-edited — flags are surfaced for the candidate to fix. `render_text()` is pure. |
| `job_sites.py` | The curated list of ~30 job boards `job_search` searches, grouped (aggregators / tech / AI-ML / remote / government / ATS). `FETCHABLE` = the subset that fetches cleanly. `LOCAL_PRESETS` adds region-specific boards + a default location/radius (Salt Lake City ships as one). |
| `job_search.py` | `search_jobs(keywords, location, radius_miles, count)` → live postings via Claude's `web_search` (restricted to `job_sites`) + `web_fetch` (full posting text). Returns `{title, company, location, url, description, grounding}`; `grounding` is `"full posting"` or `"search snippet"`. `description` is what you feed to `evaluate_fit`. |
| `run_job_folder.py` | Driver (not tested): runs one résumé against a folder of `.txt` listings, prints a ranked table + each full report. |
| `run_job_search.py` | Driver (not tested): `search_jobs` for postings near a location (default: the résumé's own), scores each, prints ranked with the posting URL + grounding. |
| `eval_cases.py` / `run_evals.py` | Live eval harness — fictional `(résumé, job)` cases (fit / tailor / cover) with **tolerant** expectations (score ranges, band sets, "a genuine_gap suggestion", "flagged bullets never survive", "no clichés"). `run_evals.py` runs the real chain and exits non-zero on a miss. `test_evals.py` checks the fixtures are well-formed, offline. |
| `applications.py` | A local SQLite log of applications (`data/applications.db`, gitignored). `add_/update_/delete_/list_applications`, and `agenda()` — open applications with a next-action date, grouped Overdue / This week / Later. No LLM; the whole module is pure data. |
| `streamlit_app.py` | UI, three modes. **Score one listing:** upload a résumé (PDF/DOCX/txt) or paste it, + a job listing → score, breakdown, gaps, projected score ("close this gap → 88"), suggestions, skill-by-skill evidence, text download; a **Build tailored résumé** button → Markdown preview, "what changed", dropped-bullet warnings, before/after diff, Markdown / PDF / Word downloads; a **Write cover letter** button → the letter, flagged claims, a "every claim + its résumé line" expander, text download. **Search live jobs:** résumé + keywords + location (or a preset) → ranked results table; row-select for the full report, a link to the posting, and **Tailor résumé / Write cover letter for that posting** (same output as the Score-one-listing buttons). **Applications:** an agenda of what's due, a table of everything logged (row-select to update status / next action / notes), an add form, and one-click "Log this application" from the listing you just scored. |
| `test_*.py` (144 total) | `test_score.py`, `test_pipeline.py`'s `rank_fits` tests, the `find_gaps`/`format_report`/`job_sites` tests, `test_tailor_resume.py`'s `assemble`/`_apply_verification`/`build_diff`/`render_markdown` tests, `test_cover_letter.py`'s `render_text`/`_flag_unsupported` tests, `test_tenure.py`, `test_applications.py`, `test_resume_source.py`, `test_resume_export.py`, `test_evals.py`, and `test_streamlit_app.py` (via `AppTest`) are pure; the rest mock the client. `run_evals.py` is the separate *live* harness. |

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
for flag in out["flags"]:       # bullets the verification pass dropped
    print("dropped:", flag["bullet"], "—", flag["issue"])
# out["diff"] — per role, original bullets next to the final ones

from resume_export import to_pdf, to_docx
Path("tailored.pdf").write_bytes(to_pdf(out["resume"]))
Path("tailored.docx").write_bytes(to_docx(out["resume"]))
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
- *Verification pass* (`verify_bullets`, a second Claude call) — audits every
  rewritten bullet against its source role's original bullets. A bullet that
  adds a number, a technology, a scope, or an outcome the source doesn't
  support is **dropped** (falling back to the untouched source bullets if that
  empties a role) and reported in `flags`. `build_diff()` gives the UI a
  before/after view so every surviving edit is visible too.

**Known limitations:**

- The tailored résumé carries only what `parse_resume` extracts. Contact
  details and certifications now survive; anything the parser doesn't model
  (a portfolio blurb, awards) still needs adding back by hand.
- The verification pass is itself an LLM call — it catches added numbers /
  tech / scope well, but a subtle tone inflation inside otherwise-supported
  wording can still slip through. The before/after diff is there so you can
  read every edit yourself.
- The PDF export (`resume_export.to_pdf`) uses fpdf2's Latin-1 core fonts —
  common punctuation is mapped (`—`→`-`, curly quotes→straight) and anything
  else outside Latin-1 (e.g. a CJK name) degrades to `?`. The Word export has
  no such limit; use it if the PDF mangles a character.

## Cover letter

`cover_letter_fit(resume_text, job_text)` (or the **Write cover letter** button)
drafts a letter under the same rule — it may only say what the résumé shows.

```python
from pipeline import cover_letter_fit

out = cover_letter_fit(resume_text, job_text)
print(out["text"])                       # the assembled letter
for flag in out["flags"]:                # claims the résumé doesn't support
    print("check:", flag["claim"], "—", flag["issue"])
# out["claims"] — every claim the letter makes, each with its résumé quote
```

- `write_cover_letter()` is handed the fit comparison, so it's told which
  skills are **demonstrated** (cite freely) and which the job wants but the
  résumé doesn't show (**never claim; fine to name as a growth area**). It
  returns three paragraphs *and* a `claims` list — every substantive statement
  about the candidate, each with the résumé phrase behind it.
- `verify_claims()` (second call) audits that list: a claim is flagged if it
  names something the résumé never mentions, or overstates scope / seniority /
  duration. Prose can't be surgically trimmed like a résumé bullet, so flagged
  claims are **surfaced, not auto-removed** — you fix or cut them.
- Clichés ("I am passionate", "team player", "hit the ground running") are
  banned in the prompt and checked in the eval harness.

## Application tracker

The Streamlit **Applications** tab keeps a local log of what you sent where
(`applications.py` → `data/applications.db`, gitignored, never leaves your
machine).

- Each row: company, role, date applied, which résumé you used, status
  (`applied` → `screening` → `interview` → `offer`, or `rejected` /
  `withdrawn`), a next action + its date, a link, and notes.
- **Agenda** (`agenda()`): open applications with a next-action date, grouped
  **Overdue / This week / Later** — the "what do I need to do today" view.
- One-click **"Log this application"** from the listing you just scored fills
  in the company, role, and whether you used the tailored résumé.
- Row-select opens an editor to move the status along, reschedule the next
  action, or add notes.

No LLM anywhere in this module — it's plain SQLite, unit-tested without mocks.

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
python -m unittest discover   # 144 tests, offline
python run_evals.py           # live eval harness — run after touching a prompt/schema
python run_job_folder.py data/sample_resume.txt data/sample_jobs/   # live CLI, needs API key
streamlit run streamlit_app.py                                      # live UI, needs API key
```

## Evals

`python -m unittest discover` proves the plumbing offline; `run_evals.py` is
the other half — it runs the real chain against a real model and checks the
*judgement* still lands. Run it after any prompt, schema, or rubric change.

```
$ python run_evals.py
PASS  [fit] career-changer vs junior AI engineer
      ok  band in ('Strong',)
      ok  score in [72, 100]
      ok  <= 1 unmet required skill(s)
...
PASS  [tailor] reframe for data analyst
      ok  every role kept
      ok  no invented skills
      ok  flagged bullets never survive into the résumé
6/6 cases passed, 22/22 checks
```

Checks are tolerant — score *ranges*, band *sets*, directional properties —
because the model moves between runs. A failure is "go look", not "the build
is red". `--case <substr>` filters, `--list` lists, `-v` prints each full
report. The suite already paid for itself once: it caught the reframe prompt
*repurposing* bullets (a PowerShell account-provisioning line rewritten as
"data integration"), which led to the "re-word, don't repurpose" rule.

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
- **The LLM/Python split:** the judgment calls are all Claude (parse résumé,
  parse job, detect skill evidence, suggest improvements, reframe the résumé +
  verify its bullets, write the cover letter + verify its claims). Everything
  else — required-vs-preferred bucketing, **total-years-of-experience computed
  from the date ranges**, all scoring arithmetic including the "close this gap
  → new score" projection, gap extraction, ranking, locking the tailored
  résumé's roles/skills to the source, dropping the flagged bullets, building
  the diff, the cover-letter assembly, the PDF/Word export, and the whole
  application tracker — is pure Python, unit-tested without mocks.
