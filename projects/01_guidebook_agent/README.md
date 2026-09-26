# HR & Policy Guidebook Lookup Agent

Answers natural-language questions about an employee handbook by routing the
question to the relevant table-of-contents section(s), then grounding the
answer strictly in that section's text — no vector database required.

## Why table-of-contents routing instead of embeddings

The handbook's ToC is short enough (37 subjects) to hand to Claude directly
as part of the prompt. Letting the model pick the relevant section(s) by
name skips the usual embedding/vector-store machinery entirely while still
giving a real retrieval step: the final answer is only ever grounded in the
1-2 pages a section actually spans, not the whole 22-page document.

## Pipeline

1. **`inspect_pdf.py`** — generic PDF inspector. Prints page count, any
   embedded outline/bookmarks (`doc.get_toc()`), and a text preview of the
   first few pages. Used once per new document to figure out whether it has
   a real embedded outline or needs its ToC hand-parsed.
2. **`build_toc.py`** — this handbook has no embedded outline, so this
   hand-parses its printed ToC page into `data/table_of_contents.csv`
   (`subject,start_page`). Bespoke to this document's layout; a different
   handbook's ToC would need its own parser (see
   `projects/benefits_pdf_practice/` for a document where `get_toc()` works
   directly instead).
3. **`ask.py`** — the agent:
   - **Rewrite** (follow-ups only): a question like "how much notice do I
     need to give?" is rewritten from the last few turns into a standalone
     question ("How much notice do I need to give for family and medical
     leave?") before routing. First questions skip this call.
   - **Route**: sends the ToC's subject list + the question to Claude,
     which returns up to 3 subject lines likely to contain the answer (or
     `NONE`).
   - **Extract**: computes each matched section's page range (from its
     `start_page` through the next section's `start_page`, since sections
     start mid-page, or end of document for the last one) and pulls that
     text with `fitz`.
   - **Answer**: sends the extracted text + question back to Claude,
     instructed to answer only from that text and say so if the answer
     isn't there. Each section is tagged `[S1]`, `[S2]`, ... and the answer
     ends with a `USED: S1, S3` line, so only the sections the answer
     actually relied on are listed as sources.
4. **`streamlit_app.py`** — chat UI with follow-up support. Each source
   opens to show the real PDF page, so an answer can be checked against
   the handbook itself.
5. **`eval_cases.py` + `run_eval.py`** — known-answer test questions run
   against the live agent (see [Evaluation](#evaluation)).

## Setup

```bash
pip install -r requirements.txt
```

Requires `ANTHROPIC_API_KEY` in a `.env` file at the repo root (see
`projects/00_python_learning/test_api_handshake.py` for the handshake this
pattern is based on). The handbook PDF itself lives in `data/` and is
gitignored — re-download it and re-run `build_toc.py` to regenerate
`table_of_contents.csv` after a fresh clone.

## Usage

Run from the repo root, with the venv activated:

```bash
source /home/t9/venv/bin/activate
python projects/01_guidebook_agent/ask.py "What is the policy on smoking?"
```

Or from inside `projects/01_guidebook_agent/` itself:

```bash
python ask.py "What is the policy on smoking?"
streamlit run streamlit_app.py
```

## Tests

`test_ask.py` covers the pure logic — page-range math in `compute_ranges`
(including the same-start-page edge case below), router-response parsing
in `parse_route_lines` (exact match, `NONE`, fuzzy-matched paraphrasing,
dedup, unmatched lines), the `USED:` line parsing, and follow-up history
formatting. `test_run_eval.py` covers the eval scoring. No API key or
network access needed:

```bash
cd projects/01_guidebook_agent
python -m unittest discover -p "test_*.py" -v
```

## Evaluation

Unit tests check the code; they can't tell you whether the agent gives the
right answer. `eval_cases.py` holds 23 questions whose answers were read
from the PDF by hand (page numbers noted in the file), and `run_eval.py`
asks each one against the live agent and checks the answer:

- 15 single-section facts ($200 gift limit, 48 hours to report an arrest,
  24 hours/week outside employment, ...)
- 2 facts on the second page of a section (see below)
- 1 grounded partial answer (military leave: no day count, points to NRS 281)
- 2 follow-ups, where the earlier question is asked for real first
- 3 questions the handbook doesn't answer, which must get no sources and a
  referral to HR instead of a guess

```bash
python run_eval.py                  # ~30 seconds, uses the API
python run_eval.py --only injury_form -v
```

Each run is saved to `data/eval_runs/` (gitignored) for comparison.

**What it caught.** The first run scored 21/23. Both failures asked about
Workers' Compensation: "What form do I fill out if I'm hurt on the job?"
got "the specific form ... is not detailed", though the handbook names the
C-1 form. The section starts mid-page 20 and continues on page 21, where
the next section also starts, and `compute_ranges` ended each section at
`next_start - 1`, so page 21 was never sent to the model. Sections now run
through the next section's start page. After the fix: 23/23 on two
consecutive runs.

## Demo

**Single-section question:**

```
$ python ask.py "What is the policy on smoking?"
According to the Smoking Policy section, smoking is prohibited in all City
owned or leased buildings, except in posted areas designated by the City
Manager or his/her designee. Smoking is also prohibited within 30 feet of
any City of Las Vegas owned or leased facility entrance and/or exit. [...]

Sources:
- Smoking Policy (pages 19-19)
```

**Multi-section question** (router pulls several sections; the answer
synthesizes across them):

```
$ python ask.py "What are the rules around workplace safety and drug use?"
According to the Safety section, it is every employee's responsibility to
work safely. [...] Employees involved in a vehicular accident while driving
a City vehicle must notify Fire & Rescue Dispatch at 229-0291 immediately.

Regarding drug use, the Use and Abuse of Drugs and Alcohol section states
that while on duty or on City premises, City employees are prohibited from
[...] The City may require employees to immediately submit to a drug test
[...] when there is reasonable suspicion [...]

Sources:
- Safety (pages 18-18)
- Use & Abuse of Drugs and Alcohol (pages 20-20)
```

**Grounded partial answer** (the handbook doesn't give a number):

```
$ python ask.py "How many days of military leave am I entitled to?"
The handbook does not specify a particular number of days of military leave
you are entitled to. Instead, it references external sources: [...] paid
military leave as provided in Nevada Revised Statutes (NRS) 281. [...]

Sources:
- Military Leave (pages 16-17)
```

**Follow-up** (rewritten before routing):

```
Q: Who is eligible for family and medical leave?
A: [...] more than one (1) year of continuous service [...] at least
   1,250 hours during the previous twelve months [...]

Q: how much notice do I need to give?
   (searched as: "How much notice do I need to give for family and
   medical leave?")
A: According to the Family & Medical Leave section, employees shall
   provide thirty (30) days advance notice, if possible [...]
```

**No match:**

```
$ python ask.py "What is the weather like in Las Vegas?"
I couldn't find a section of the handbook that covers that. For anything
else, please contact Human Resources.
```

## Known limitations

- Router output is matched against the ToC by exact string first, falling
  back to fuzzy matching (`difflib.get_close_matches`, cutoff 0.6) for minor
  paraphrasing. A subject that doesn't clear that bar is reported and
  dropped rather than guessed at.
- Follow-ups see only the last 3 question/answer pairs, clipped to 600
  characters each.
- Page ranges overlap by one page, so a section can include the start of
  the next one. That's extra context, not missing context, by design.
- PyMuPDF isn't thread-safe, so PDF access is serialized with a lock
  (Streamlit runs each session in its own thread).
- `build_toc.py` is specific to this PDF's printed ToC layout and won't
  generalize to a differently formatted handbook.
