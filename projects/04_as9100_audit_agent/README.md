# AS9100 Audit & Document Comparison Agents

Two related tools that rebuild, as open-source Python + the Anthropic Claude
API, quality-audit-support concepts originally prototyped as no-code
Microsoft Copilot Studio agents. All source documents here are **fictional**
("Sample Aerospace Co.") — generated for testing, never real employer data.

## Why this exists

The Copilot Studio version of the document-comparison tool below is real
and already in production use, with two completed audits (33 and 37 pages)
each finishing in a couple of hours versus 2-3 days of manual document
search. It's also capped at an 8,000-character system prompt, which limited
how much rule detail and document context it could carry. This project
rebuilds the same concept in code, without that ceiling, as a portfolio
piece.

## The two tools

### 1. `audit.py` — checklist gap analysis

Checks a fixed set of audit clauses against a body of internal documents and
reports **Met / Partial / Gap** per clause, with a one-sentence rationale and
supporting source file.

Pipeline: `generate_sample_docs.py` (writes the fictional criteria PDF and
5 fictional work-instruction PDFs) → `parse_criteria.py` (extracts the 15
clauses into `data/criteria.csv`) → `audit.py` (evaluates each clause
against the full text of every work-instruction PDF via Claude, temp 0.0).

```bash
python generate_sample_docs.py
python parse_criteria.py
python audit.py
```

Sample output:

```
[Met    ] AC-4.2.3 -- Document Control
          WI-014 explicitly describes documented procedures for controlling
          quality-system documents...
          Source: WI-014_document_control.pdf
[Gap    ] AC-7.1.6 -- FOD Prevention
          None of the provided work-instruction documents contain any
          reference to a foreign-object-debris (FOD) prevention program.
          Source: NONE
...
Summary: 7 Met, 4 Partial, 4 Gap
```

### 2. `compare.py` — document-to-document comparison

This is the direct rebuild of the real Copilot Studio design: given an
**uploaded reference document** (a customer's, supplier's, or revised
internal requirement), it matches it against an internal document
**registry** (`data/document_registry.csv` — Doc_Number, Title, File_Name,
Department, Process, Keywords, Related_Z), then compares the matched pair
and reports gaps and differences.

Two important behaviors carried over directly from the original design:

- **Language discipline**: the comparison never claims compliance,
  certification, or audit signoff. It uses hedged language ("possible gap",
  "appears missing", "may need review") and explicitly avoids words like
  "compliant" or "approved" — this is a gap-identification tool, not an
  audit authority.
- **No invented matches**: both the document-matching step and the
  "Related Internal References" section are constrained to the actual
  registry contents. An earlier version of this hallucinated plausible but
  nonexistent document numbers in that section — fixed by passing the full
  registry into the comparison call's context, not just the matched row.

```bash
python generate_sample_docs.py   # also writes the fictional reference doc
python build_registry.py
python compare.py data/acme_production_requirements.pdf
```

Sample output:

```
Best match: Z3-045 -- Production Work Instructions and Nonconforming
Material Handling (confidence: approximate)
Secondary matches considered: Z2-052

Comparison Summary:
Z3-045 establishes foundational work instruction and nonconforming
material controls but appears to lack explicit FOD prevention
checkpoints, complete raw-material-to-finished-good traceability
linkage, and a defined notification protocol for nonconformances
affecting delivered product.

Possible Gaps:
- FOD prevention checkpoint not explicitly required...
- Raw-material heat-lot to finished-good serial number traceability...
...
Related Internal References:
- Z2-014 -- Document Control Procedure (for work instruction revision...)
- Z3-031 -- Calibration and Measurement Equipment Control...
- Z2-052 -- Supplier Approval and Corrective Action Procedure...
```

## Setup

```bash
pip install -r requirements.txt
```

Requires `ANTHROPIC_API_KEY` in a `.env` file at the repo root. All of
`data/` is gitignored — regenerate it any time with `generate_sample_docs.py`
and `build_registry.py`.

## Tests

`test_agents.py` covers the pure parsing logic in all three scripts —
`parse_clauses` (multi-line clause wrapping, header-line skipping),
`parse_verdict` (status/source/rationale extraction, invalid-status
fallback), and `parse_match` (best/secondary match and confidence
extraction). No API key or network access needed:

```bash
python -m unittest test_agents.py -v
```

## Known limitations

- `audit.py`'s checklist is fictional and small (15 clauses) — a real
  AS9100 audit would use the actual copyrighted standard text, which this
  project intentionally avoids reproducing.
- `compare.py`'s registry matching and comparison are two separate LLM
  calls with no shared context between them; a wrong match in step one
  can't be corrected by step two.
- Neither tool distinguishes between clause-level nuance a human auditor
  would catch (e.g., partial credit for a procedure that's *planned* but
  not yet implemented) beyond what's captured in the Met/Partial/Gap or
  gap/difference framing.
