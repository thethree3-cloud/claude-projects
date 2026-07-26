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
   - **Route**: sends the ToC's subject list + the question to Claude,
     which returns up to 3 subject lines likely to contain the answer (or
     `NONE`).
   - **Extract**: computes each matched section's page range (from its
     `start_page` to the next section's `start_page - 1`, or end of
     document for the last one) and pulls that text with `fitz`.
   - **Answer**: sends the extracted text + question back to Claude,
     instructed to answer only from that text and say so if the answer
     isn't there.

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
```

## Tests

`test_ask.py` covers the pure logic — page-range math in `compute_ranges`
(including the same-start-page edge case below) and router-response parsing
in `parse_route_lines` (exact match, `NONE`, fuzzy-matched paraphrasing,
dedup, unmatched lines). No API key or network access needed:

```bash
cd projects/01_guidebook_agent
python -m unittest test_ask.py -v
```

## Demo

**Single-section question:**

```
$ python ask.py "What is the policy on smoking?"
Routed to section: Smoking Policy (pages 19-19)

According to the Smoking Policy section:
- Smoking is prohibited in all City owned or leased buildings, except in
  posted areas designated by the City Manager or his/her designee.
- Smoking is prohibited within 30 feet of any City of Las Vegas owned or
  leased facility entrance and/or exit.
- Smoking is not allowed in City owned or leased vehicles.
```

**Multi-section question** (router pulls three sections and synthesizes
across them):

```
$ python ask.py "What are the rules around workplace safety and drug use?"
Routed to section: Safety (pages 18-18)
Routed to section: Use & Abuse of Drugs and Alcohol (pages 20-20)
Routed to section: Workplace Violence Policy (pages 21-22)

## Workplace Safety
- Seat belt requirement while riding or driving in a City vehicle.
- Vehicular accidents must be reported to Fire & Rescue Dispatch immediately.

## Drug and Alcohol Use
- Prohibited: possessing, using, selling, or distributing alcohol, illegal
  drugs, or non-prescribed controlled substances while on duty or on
  City premises.
- The City may require a drug test given "reasonable suspicion."
```

**Grounded refusal** (question the handbook doesn't actually answer):

```
$ python ask.py "How many days of military leave am I entitled to?"
Routed to section: Military Leave (pages 16-16)

The specific number of days isn't stated in this handbook excerpt — it
references NRS 281 and your collective bargaining agreement instead.
```

**No match:**

```
$ python ask.py "What is the weather like in Las Vegas?"
No matching section found in the table of contents.
```

## Known limitations

- Router output is matched against the ToC by exact string first, falling
  back to fuzzy matching (`difflib.get_close_matches`, cutoff 0.6) for minor
  paraphrasing. A subject that doesn't clear that bar is reported and
  dropped rather than guessed at.
- No conversation memory — each question is answered independently.
- `build_toc.py` is specific to this PDF's printed ToC layout and won't
  generalize to a differently formatted handbook.
