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

## Data: a representative sample, not the full catalog

The real catalog's Rectangular/Square Boxes section (pages 8-29) lists
roughly 900-1,000 real SKUs spanning 0.31" to 28"+ widths. There's no
OCR available in this environment (no `tesseract`, no sudo to install
it), so transcribing every row by hand wasn't a good time/accuracy
tradeoff. `deep_draw_catalog.py` instead holds a **hand-picked
representative sample** — real rows (part number, W×L, height range,
gauge, corner radii), spread evenly across the full width range from a
sampling of catalog pages. See that file's docstring for exactly which
pages were sampled.

If the full table (or a real dimension catalog file) becomes available
later, swap it into `deep_draw_catalog.py` — everything downstream
(pricing, quote history, lookup, UI) stays the same.

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
| `deep_draw_catalog.py` | The representative real-sample dataset (~45 sizes) plus the catalog's cover types (CF/CI/COG/COL/COT) and nutplate patterns (AA-JJ). |
| `deep_draw_pricing.py` | `compute_box_quote()` — material (area × gauge × 6061 density × $/lb) + labor (area + estimated draw count × shop rate) + optional cover + optional nutplates, then markup. Sources and every placeholder/judgment-call figure are documented in the module docstring. |
| `generate_quote_history.py` | Builds a 1,000-row synthetic "historical quote" database (`data/quote_history.db`, gitignored) from the real sample sizes plus random noise. Verified: smallest sampled box (HA050133) averages ~$104, largest (Z452-452) ~$353; every cover type raises the average price over "none." |
| `quote_lookup.py` | Finds similar historical quotes for a given size and reports an average + confidence score. |
| `streamlit_app.py` | Pick a real catalog size, height, cover, and nutplate pattern; see a formula quote and a "similar past quotes" comparison side by side. |
| `branding.py` | Zero Manufacturing header (logo + dark banner, matching the current zerocases.com style) and `st.logo()` sidebar branding. `assets/zero_logo.png` is Zero Cases' own official site icon. |
| `test_deep_draw_pricing.py` | 15 tests on the cost model. |
| `test_quote_history.py` | 10 tests on the generator and lookup. |

## Running it

```bash
python generate_quote_history.py   # one-time: builds data/quote_history.db
streamlit run streamlit_app.py
```

## Known limitations / next steps

- **The sample covers ~45 of ~900-1,000 real box SKUs.** It spans the
  full size range evenly, but a lookup for a size between sampled points
  interpolates less precisely than the full table would.
- **All pricing is placeholder**, same caveat as `case_configurator`.
- **Draw count is an engineering approximation**, not a catalog-sourced
  figure — see above.
- Round Housings, Precision Miniatures, Flanged, and ARINC Style
  Housings (the rest of this same catalog) aren't ingested yet — each
  would be a natural next slice of this same tool.
