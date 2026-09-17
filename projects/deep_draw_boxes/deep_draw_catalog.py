"""Real sample sizes from Zero Manufacturing's Deep Drawn catalog.

Transcribed 2026-09-16 from a customer-provided PDF (Deep-Draw-Catalog-8-
6-2026-Update-1.pdf), "Standard Cans and Boxes" / Rectangular Boxes size
tables (catalog pages 8-29). That section alone lists roughly 900-1,000
real SKUs spanning 0.31" to 28.25"+ widths -- no OCR is available in this
environment (no `tesseract`, no sudo to install it) and full manual
transcription of every row wasn't worth the time/error-risk tradeoff, so
this is a REPRESENTATIVE SAMPLE: real rows, hand-picked to span the full
width range evenly (roughly 3-4 rows per printed catalog page, sampled
from catalog pages 8, 9, 10, 11, 12, 13, 14, 15, 16, 19, 22, 25, 28, 29).

Every alloy in this section is 6061-0 (unlike VAL-AN's mix of 6061/1100-0)
-- see case_configurator/valan_catalog.py for that separate, unrelated
catalog. Per the user's instruction, these two catalogs are kept as
separate tools/agents, not merged.

Fields per box:
- part_no: the catalog's stocked or non-stocked part number.
- width_in, length_in: outside footprint dimensions (W x L), inches.
- height_min_in, height_max_in: the height (H) range achievable for this
  W x L, adjustable to any value in that range per the catalog.
- gauge_in: blank gauge thickness (T) prior to drawing, inches. Actual
  wall thickness runs ~75%+ of this depending on draw depth/count (see
  deep_draw_pricing.py for how that's modeled).
- r1_in, r2_in: bottom and side corner radii, inches.
- catalog_page: the printed page number in the source PDF, for traceability.
"""

DEEP_DRAW_BOXES = [
    {"part_no": "HA050133", "width_in": 0.52, "length_in": 1.34, "height_min_in": 0.50, "height_max_in": 1.63, "gauge_in": 0.032, "r1_in": 0.13, "r2_in": 0.06, "catalog_page": 8},
    {"part_no": "ZT11-29", "width_in": 0.72, "length_in": 1.84, "height_min_in": 0.37, "height_max_in": 0.56, "gauge_in": 0.020, "r1_in": 0.09, "r2_in": 0.11, "catalog_page": 8},
    {"part_no": "ZT13-36", "width_in": 0.81, "length_in": 2.28, "height_min_in": 0.37, "height_max_in": 0.62, "gauge_in": 0.032, "r1_in": 0.09, "r2_in": 0.09, "catalog_page": 8},
    {"part_no": "Z14-26", "width_in": 0.91, "length_in": 1.66, "height_min_in": 0.44, "height_max_in": 2.12, "gauge_in": 0.050, "r1_in": 0.16, "r2_in": 0.25, "catalog_page": 8},
    {"part_no": "ZT15-52", "width_in": 0.94, "length_in": 3.25, "height_min_in": 0.44, "height_max_in": 2.44, "gauge_in": 0.040, "r1_in": 0.12, "r2_in": 0.14, "catalog_page": 9},
    {"part_no": "Z15-64", "width_in": 0.94, "length_in": 4.00, "height_min_in": 0.44, "height_max_in": 1.87, "gauge_in": 0.040, "r1_in": 0.13, "r2_in": 0.13, "catalog_page": 9},
    {"part_no": "ZT16-28", "width_in": 1.00, "length_in": 1.75, "height_min_in": 0.44, "height_max_in": 1.00, "gauge_in": 0.020, "r1_in": 0.12, "r2_in": 0.14, "catalog_page": 9},
    {"part_no": "Z16-34", "width_in": 1.00, "length_in": 2.50, "height_min_in": 0.14, "height_max_in": 0.50, "gauge_in": 0.080, "r1_in": 0.06, "r2_in": 0.06, "catalog_page": 9},
    {"part_no": "Z16-44A", "width_in": 1.00, "length_in": 2.75, "height_min_in": 0.44, "height_max_in": 2.00, "gauge_in": 0.040, "r1_in": 0.12, "r2_in": 0.22, "catalog_page": 9},
    {"part_no": "Z18-44A", "width_in": 1.12, "length_in": 2.75, "height_min_in": 0.37, "height_max_in": 4.75, "gauge_in": 0.050, "r1_in": 0.19, "r2_in": 0.19, "catalog_page": 9},
    {"part_no": "ZT19-28", "width_in": 1.19, "length_in": 1.75, "height_min_in": 0.37, "height_max_in": 1.12, "gauge_in": 0.040, "r1_in": 0.09, "r2_in": 0.08, "catalog_page": 10},
    {"part_no": "Z21-58", "width_in": 1.30, "length_in": 3.60, "height_min_in": 0.50, "height_max_in": 1.00, "gauge_in": 0.032, "r1_in": 0.09, "r2_in": 0.09, "catalog_page": 10},
    {"part_no": "ZT23-39", "width_in": 1.44, "length_in": 2.44, "height_min_in": 0.37, "height_max_in": 2.37, "gauge_in": 0.040, "r1_in": 0.08, "r2_in": 0.08, "catalog_page": 10},
    {"part_no": "ZT24-60A", "width_in": 1.50, "length_in": 3.75, "height_min_in": 0.50, "height_max_in": 3.00, "gauge_in": 0.040, "r1_in": 0.12, "r2_in": 0.20, "catalog_page": 10},
    {"part_no": "ZT26-44", "width_in": 1.62, "length_in": 2.75, "height_min_in": 0.37, "height_max_in": 3.25, "gauge_in": 0.063, "r1_in": 0.06, "r2_in": 0.19, "catalog_page": 11},
    {"part_no": "ZT28-32C", "width_in": 1.75, "length_in": 2.00, "height_min_in": 0.44, "height_max_in": 2.00, "gauge_in": 0.040, "r1_in": 0.09, "r2_in": 0.08, "catalog_page": 11},
    {"part_no": "Z28-80", "width_in": 1.75, "length_in": 5.00, "height_min_in": 0.50, "height_max_in": 4.00, "gauge_in": 0.040, "r1_in": 0.19, "r2_in": 0.19, "catalog_page": 11},
    {"part_no": "Z30-69", "width_in": 1.87, "length_in": 4.31, "height_min_in": 0.50, "height_max_in": 4.00, "gauge_in": 0.050, "r1_in": 0.25, "r2_in": 0.19, "catalog_page": 11},
    {"part_no": "Z32-32A", "width_in": 2.00, "length_in": 2.00, "height_min_in": 0.50, "height_max_in": 2.25, "gauge_in": 0.063, "r1_in": 0.25, "r2_in": 0.25, "catalog_page": 12},
    {"part_no": "ZT32-64D", "width_in": 2.00, "length_in": 4.00, "height_min_in": 0.50, "height_max_in": 3.00, "gauge_in": 0.063, "r1_in": 0.12, "r2_in": 0.12, "catalog_page": 12},
    {"part_no": "ZT34-50A", "width_in": 2.12, "length_in": 3.12, "height_min_in": 0.50, "height_max_in": 3.50, "gauge_in": 0.040, "r1_in": 0.12, "r2_in": 0.20, "catalog_page": 12},
    {"part_no": "Z36-48", "width_in": 2.25, "length_in": 3.00, "height_min_in": 0.50, "height_max_in": 3.00, "gauge_in": 0.050, "r1_in": 0.25, "r2_in": 0.25, "catalog_page": 13},
    {"part_no": "ZT38-71", "width_in": 2.37, "length_in": 4.44, "height_min_in": 0.62, "height_max_in": 3.50, "gauge_in": 0.063, "r1_in": 0.09, "r2_in": 0.06, "catalog_page": 13},
    {"part_no": "Z40-40A", "width_in": 2.50, "length_in": 2.50, "height_min_in": 0.44, "height_max_in": 2.25, "gauge_in": 0.050, "r1_in": 0.19, "r2_in": 0.19, "catalog_page": 13},
    {"part_no": "ZT40-96A", "width_in": 2.50, "length_in": 6.00, "height_min_in": 0.50, "height_max_in": 3.25, "gauge_in": 0.063, "r1_in": 0.25, "r2_in": 0.25, "catalog_page": 14},
    {"part_no": "Z44-72", "width_in": 2.75, "length_in": 4.50, "height_min_in": 0.50, "height_max_in": 2.50, "gauge_in": 0.063, "r1_in": 0.31, "r2_in": 0.31, "catalog_page": 14},
    {"part_no": "Z48-160A", "width_in": 3.00, "length_in": 10.00, "height_min_in": 0.62, "height_max_in": 3.00, "gauge_in": 0.063, "r1_in": 0.25, "r2_in": 0.25, "catalog_page": 16},
    {"part_no": "Z52-84A", "width_in": 3.25, "length_in": 5.25, "height_min_in": 0.69, "height_max_in": 5.00, "gauge_in": 0.050, "r1_in": 0.44, "r2_in": 0.31, "catalog_page": 16},
    {"part_no": "ZT53-194", "width_in": 3.31, "length_in": 12.12, "height_min_in": 0.41, "height_max_in": 1.62, "gauge_in": 0.040, "r1_in": 0.09, "r2_in": 0.20, "catalog_page": 16},
    {"part_no": "Z64-144", "width_in": 4.00, "length_in": 9.00, "height_min_in": 0.50, "height_max_in": 5.00, "gauge_in": 0.063, "r1_in": 0.25, "r2_in": 0.25, "catalog_page": 19},
    {"part_no": "ZT68-96", "width_in": 4.25, "length_in": 6.00, "height_min_in": 0.50, "height_max_in": 4.75, "gauge_in": 0.063, "r1_in": 0.12, "r2_in": 0.19, "catalog_page": 19},
    {"part_no": "Z70-102B", "width_in": 4.37, "length_in": 6.37, "height_min_in": 0.50, "height_max_in": 6.00, "gauge_in": 0.063, "r1_in": 0.25, "r2_in": 0.25, "catalog_page": 19},
    {"part_no": "Z88-128A", "width_in": 5.50, "length_in": 8.00, "height_min_in": 0.87, "height_max_in": 4.75, "gauge_in": 0.063, "r1_in": 0.25, "r2_in": 0.25, "catalog_page": 22},
    {"part_no": "ZT94-120A", "width_in": 5.87, "length_in": 7.50, "height_min_in": 0.56, "height_max_in": 4.50, "gauge_in": 0.050, "r1_in": 0.12, "r2_in": 0.20, "catalog_page": 22},
    {"part_no": "Z96-128A", "width_in": 6.00, "length_in": 8.00, "height_min_in": 0.87, "height_max_in": 6.00, "gauge_in": 0.063, "r1_in": 0.37, "r2_in": 0.31, "catalog_page": 22},
    {"part_no": "Z128-176A", "width_in": 8.00, "length_in": 11.00, "height_min_in": 1.44, "height_max_in": 7.50, "gauge_in": 0.063, "r1_in": 0.87, "r2_in": 0.87, "catalog_page": 25},
    {"part_no": "Z136-192A", "width_in": 8.50, "length_in": 12.00, "height_min_in": 1.62, "height_max_in": 10.00, "gauge_in": 0.090, "r1_in": 1.00, "r2_in": 1.00, "catalog_page": 25},
    {"part_no": "Z144-432A", "width_in": 9.00, "length_in": 27.00, "height_min_in": 1.37, "height_max_in": 7.00, "gauge_in": 0.090, "r1_in": 0.75, "r2_in": 0.75, "catalog_page": 25},
    {"part_no": "Z218-330A", "width_in": 13.62, "length_in": 20.62, "height_min_in": 1.87, "height_max_in": 10.00, "gauge_in": 0.090, "r1_in": 1.25, "r2_in": 1.50, "catalog_page": 28},
    {"part_no": "Z240-320", "width_in": 15.00, "length_in": 20.00, "height_min_in": 1.62, "height_max_in": 9.00, "gauge_in": 0.090, "r1_in": 1.00, "r2_in": 1.00, "catalog_page": 28},
    {"part_no": "Z264-320A", "width_in": 16.50, "length_in": 20.00, "height_min_in": 1.06, "height_max_in": 10.00, "gauge_in": 0.063, "r1_in": 0.50, "r2_in": 0.88, "catalog_page": 28},
    {"part_no": "Z288-432A", "width_in": 18.00, "length_in": 27.00, "height_min_in": 1.50, "height_max_in": 10.00, "gauge_in": 0.090, "r1_in": 1.00, "r2_in": 1.00, "catalog_page": 29},
    {"part_no": "Z336-416", "width_in": 21.00, "length_in": 26.00, "height_min_in": 2.00, "height_max_in": 16.25, "gauge_in": 0.090, "r1_in": 1.10, "r2_in": 1.10, "catalog_page": 29},
    {"part_no": "Z452-452", "width_in": 28.25, "length_in": 28.25, "height_min_in": 1.87, "height_max_in": 10.00, "gauge_in": 0.090, "r1_in": 1.25, "r2_in": 1.25, "catalog_page": 29},
]

ALLOY = "6061-0"  # every row in the sampled pages used this alloy

# Cover styles this catalog offers per box (catalog pages 38+): the box
# itself is priced separately from its cover.
COVER_TYPES = ["none", "CF", "CI", "COG", "COL", "COT"]

# Nutplate mounting patterns (catalog page 48-50), each with a minimum box
# size it's recommended for. Kept as a simple list here since the sample
# doesn't need the full per-pattern minimum-size table.
NUTPLATE_PATTERNS = ["none", "AA", "BB", "CC", "DD", "EE", "FF", "GG", "HH", "JJ"]
