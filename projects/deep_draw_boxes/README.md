# Deep-draw box configurator

A separate tool from `../case_configurator/` — kept apart deliberately,
per the decision to treat each catalog/product line as its own agent
rather than merging them.

This one covers Zero Manufacturing's **Deep Drawn** catalog: raw,
open-top deep-drawn aluminum shells (bottom + 4 sides, no lid), sold
independently of covers and nutplates, which are separate modular
add-ons in the real catalog. This is structurally different from
`case_configurator`'s VAL-AN data, which models complete, finished
MIL-spec cases (latches, hinges, valve, inner lid).

## Data: the full Rectangular Boxes table, main series only

`deep_draw_catalog.py` holds every row (906) from the real catalog's
Rectangular Boxes size table (pages 8-29) that has a direct part number,
gauge, and R1/R2 inline on that table — read by rendering each page as
an image (PyMuPDF, no poppler/tesseract needed) and transcribing it
directly, since the source PDF has no extractable text layer. Almost
every row is 6061-0 aluminum except one (ZT19-75, which is 3003-0), so
`alloy` is a per-row field.

Most rows in the 0.3"-2" width range on those same pages don't carry
their own gauge/radii and instead say "See page 56/57/58," pointing to
the ZMR/ZMS mini-series tables below.

## Data: ZMR/ZMS mini-series (119 sizes)

`ZMS_BOXES` (20 sizes, square, .531"-2.00" wide, catalog page 55) and
`ZMR_BOXES` (99 sizes, rectangular, .218"-3.938" wide, catalog pages
56-58) are the full mini-series tables the main table's "See page
55/56/57/58" notes point to — same transcription method, every row with
a part number.

Different schema from the main series:
- **One fixed max depth per size, no range** — the catalog publishes no
  minimum, so the app doesn't offer a height slider for these; height is
  fixed at the printed max.
- **A material thickness code (A/B/C), not a direct gauge** — the actual
  gauge depends which of 4 materials it's drawn in. `mini_series_pricing.py`
  has the code→gauge table and real sourced pricing for all four:
  aluminum (reuses the main series' $4.00/lb), steel (A1008 CR, $1.50/lb),
  brass (C260, $16.70/lb — an actual distributor price point, not just a
  market range: verified from two different sheet sizes at Alcobra Metals
  that both back out to the same $/lb), and Monel 400 ($20.00/lb). See
  that module's docstring for the full sourcing and the handful of
  special-gauge/ambiguous-code rows it doesn't try to resolve.
- **Usually one combined R1/R2 radius**, though 5 of the 119 rows publish
  two distinct values and are transcribed that way.
- **No cover or nutplate options modeled** for this series yet.
- **Its own "similar past quotes" history**, in a separate database
  (`data/mini_quote_history.db`) from the main series' — the two size
  ranges overlap a little at the boundary (mini tops out at ~4" wide,
  main starts at ~0.5"), so keeping them apart avoids a mini box ever
  matching against a main-series quote. Height isn't varied when
  generating this history (there's no range to vary), only material and
  finish. One thing this data surfaced: price here tracks estimated draw
  count much more than it tracks raw size (draws-vs-price correlation
  ~0.85, size-vs-price only ~0.15) — some very narrow rows have a
  disproportionately deep max_depth_in, so they need many more draw
  passes despite being small overall. Documented in
  `test_mini_quote_history.py`.

In the app, "Catalog series" in the sidebar switches between the main
flow and this one.

## On "number of draws"

Confirmed directly from the catalog text: wall thickness "is dependent
on depth of draw, number of draws and net blank thickness," but the
catalog does **not** publish a per-part draw count — it's an internal
engineering variable Zero's process engineers determine, not something
customers see or order. `deep_draw_pricing.estimate_num_draws()` is
therefore an **engineering approximation** (deeper cavities relative to
their opening width need more successive draw passes), not a catalog
figure — documented clearly in that module's docstring.

## Files

| File | What it does |
| --- | --- |
| `deep_draw_catalog.py` | The full Rectangular Boxes dataset (906 real sizes), the ZMS/ZMR mini-series datasets (119 real sizes), plus the catalog's cover types (CF/CI/COG/COL/COT), nutplate patterns (AA-JJ), and finish types (mill/anodized/powder coat). |
| `deep_draw_pricing.py` | `compute_box_quote()` for the main series — material (area × gauge × 6061 density × $/lb) + labor (area + estimated draw count × shop rate) + optional cover + optional nutplates, then markup. Sources and every placeholder/judgment-call figure are documented in the module docstring. |
| `mini_series_pricing.py` | `compute_mini_box_quote()` for ZMR/ZMS — same material+labor+finish shape as above, but resolves gauge from a material code and prices across 4 materials (aluminum/steel/brass/Monel), each with its own sourced $/lb and density. |
| `generate_quote_history.py` | Builds a 1,000-row synthetic "historical quote" database (`data/quote_history.db`, gitignored) by sampling from the main series' real catalog sizes plus random noise. Verified: every cover type raises the average price over "none." With 906 possible sizes and only 1,000 rows, most individual sizes get 0-2 quotes — `quote_lookup.py` matches on nearby sizes, not just exact ones, so this is expected. |
| `generate_mini_quote_history.py` | Same idea for ZMR/ZMS — a 1,000-row synthetic history (`data/mini_quote_history.db`, gitignored) sampling real mini-series sizes, material, and finish (height is fixed, not sampled). Its own database, kept separate from the main series' — see limitations below. |
| `quote_lookup.py` | Finds similar historical quotes for a given size and reports an average + confidence score. Shared by both series (each passes its own database path). |
| `streamlit_app.py` | A "Catalog series" switch in the sidebar picks between the main series (real catalog size, height, cover, nutplate pattern) and the ZMR/ZMS mini-series (real size, fixed height, one of 4 materials) — both show a formula quote, a "similar past quotes" comparison, and a downloadable PDF. |
| `branding.py` | Zero Manufacturing header (logo + dark banner, matching the current zerocases.com style) and `st.logo()` sidebar branding. `assets/zero_logo.png` is Zero Cases' own official site icon. |
| `test_deep_draw_pricing.py` | 15 tests on the main-series cost model. |
| `test_mini_series_pricing.py` | 10 tests on the ZMR/ZMS cost model (material resolution, per-material pricing, gauge overrides). |
| `test_quote_history.py` | 10 tests on the main-series generator and lookup. |
| `test_mini_quote_history.py` | 10 tests on the ZMR/ZMS generator and lookup. |
| `quote_export.py` | `to_pdf()` (main series) and `to_pdf_mini()` (ZMR/ZMS) — render the diagram, quote breakdown, and (main series only) historical comparison into a branded, downloadable PDF (fpdf2, same pattern as `case_configurator/quote_export.py`). Both share a `_write_quote_body()` helper. |

## Running it

```bash
python generate_quote_history.py        # one-time: builds data/quote_history.db
python generate_mini_quote_history.py   # one-time: builds data/mini_quote_history.db
streamlit run streamlit_app.py
```

## Known limitations / next steps

- **All pricing is placeholder**, same caveat as `case_configurator`. The
  nutplate price was re-sourced 2026-09-17 against a real 10-32 floating
  nutplate ($1.08 each) and lines up closely with the original guess;
  cover-type and finish-coat adders are still unsourced judgment calls.
- **Draw count is an engineering approximation**, not a catalog-sourced
  figure — see above.
- **ZMR/ZMS have no cover/nutplate modeling**, and no exact-material
  availability restrictions (the catalog flags a couple of rows as "not
  available in brass/aluminum"; not enforced here) — see above.
- Round Housings, Precision Miniatures, Flanged, and ARINC Style
  Housings (the rest of this same catalog) aren't ingested yet — each
  would be a natural next slice of this same tool.
