# Scripture Study Agent (Project 17 — personal track)

A personal, Latter-day Saint–focused scripture study companion. You give it
a reference (e.g. `Isaiah 1:1`) and it assembles the verse text plus every
study help it can retrieve — footnotes, cross-references, Topical Guide /
Bible Dictionary entries, Joseph Smith Translation — into one organized,
**fully-sourced** study view.

This is a personal-use tool, not a portfolio showcase (same category as
Project 10). It is numbered for tracking continuity only.

## Design rule: one web dependency

The **[Open Scripture API](https://openscriptureapi.org)** is the *only*
thing this agent talks to over the network. It is free, public, read-only,
no API key. Everything else the finished agent uses — a converted corpus of
personal PDFs/EPUBs (including Joseph Smith Papers volumes for D&C
historical context, and a Dead Sea Scrolls translation for Isaiah textual
contrast) and a verse→passage index over it — lives locally. No web search,
no live fetching of anything else.

Hard grounding requirement: the agent never emits a verse quotation or a
reference that did not come back from an actual tool call.

## What's built so far

### Slice 1 — API connection (this slice)

- **`scripture_api.py`** — a thin Python client over the Open Scripture
  REST API. One function per documented endpoint; each returns parsed JSON
  and does no interpretation. Covers:
  - `resolve_reference` — parse/validate a reference string (the validation
    gate)
  - `find_references_in_text` — detect every scripture reference in a block
    of free text (used at corpus-build time to tag pages with the verses
    they discuss)
  - `get_chapter`, `get_verse`, `get_cross_references`, `search_scripture`
  - `get_footnotes` — a verse's footnotes **as printed**: letter marker →
    the word/phrase it anchors to → the raw footnote text. This is the
    complete list; `get_cross_references` (the parsed/resolved view) can
    silently drop a footnote — see the caveat below. A full study view
    shows both.
  - `section_heading` — pulls the "introduction" augmentation off a
    chapter; for D&C sections this is the paragraph naming the **date and
    place** the revelation was received (the match key for Joseph Smith
    Papers documents later)
  - `list_study_help_types`, `list_study_help_entries`,
    `get_study_help_entry` — Topical Guide, Bible Dictionary, Triple
    Combination Index, JST
  - `get_topical_guide` / `get_bible_dictionary` / `get_study_help_by_subject`
    — fetch an entry by **subject name** rather than id
    (`"Honoring Father and Mother"` → `tg-honoring-father-and-mother`), via
    `study_help_slug`
  - `study_help_entries_by_letter` — every entry of a type whose title
    starts with a given letter (pages the list and filters client-side; the
    API's `q` is a substring match, not a prefix)
  - `list_conferences`, `get_latest_conference`, `get_conference`,
    `get_talk` — General Conference, 1971–present. **The client wraps these
    for completeness, but the agent does not use them: General Conference
    is out of scope for now** (the naive "which talks cite this verse" scan
    was weak; revisit later). The agent points the user to the living
    prophets and official resources instead of quoting talks.
- **`.mcp.json`** (repo root) — registers the hosted Open Scripture MCP
  server (`https://openscriptureapi.org/api/mcp`) for Claude Code. Run
  `claude` once and approve it. This is the connection used when the agent
  *is* Claude (Claude Code now, the Claude app via a tunnel later); the
  Python client above is for build-time scripts and any future
  Python-driven agent loop.
- **`test_scripture_api.py`** — 26 offline tests (the `requests` session is
  stubbed): URL construction, parameter passing, the error-handling
  contract, footnote marker/anchor extraction, slug building, and the
  by-letter pagination/early-stop. No network needed.

Live smoke check:

```bash
python scripture_api.py "Isaiah 1:1"
```

### Not yet built

- Corpus conversion pipeline (PDF via PyMuPDF; JSP EPUBs via `ebooklib`,
  parsed into per-document records keyed by date and bracketed `[D&C N]`).
- The verse→passage index (built by running converted pages through
  `find_references_in_text`).
- The "reference in → assembled sourced study view out" agent flow.
- Dead Sea Scrolls comparison material.
- Wrapping the local corpus as an MCP server + `cloudflared` tunnel for
  iPad use.

## Known grounding caveats (Open Scripture API)

**1. `resolve_reference` is a forgiving trie matcher.** Good at typos
(`Isiah 1:1` → `Isaiah 1:1`) but it will also **silently mis-resolve**
non-scripture input: `The Silmarillion 1:1` comes back `valid: true` as
`Revelation 1:1`. The agent must not blindly trust it — check that the
returned `prettyString` matches what the user asked for, and confirm when
the input was ambiguous. Genuine garbage (`xyzzy 99:99`, empty string)
does raise an error.

**2. `get_cross_references` can drop a footnote.** The parsed
`crossReferences` view omits footnotes its parser doesn't recognise —
confirmed on **Alma 32:21**, whose footnote *a* (`John 20:29; Heb. 11:1
(1–40)`) is missing from `crossReferences` but present in `get_footnotes`.
Treat the printed footnote list (`get_footnotes` / `get_chapter`) as
authoritative; use `get_cross_references` to enrich it with resolved
target text, and re-resolve any missing footnote from its own text with
`resolve_reference` / `find_references_in_text`.

## Setup

```bash
pip install -r ../../requirements.txt   # adds: requests
python -m unittest test_scripture_api.py -v
```
