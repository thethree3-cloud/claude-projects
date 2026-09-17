"""Real case sizes from the Zero Manufacturing VAL-AN Series catalog.

Transcribed 2026-09-16 from a customer-provided PDF (Val-An-Series-Catalog-
Compressed.pdf, catalog pages 15/17-42): the "INDEX TO CASE SIZE" table
(width/length per case code) plus, for each of the 52 case codes, the
per-case detail page giving material thickness, the case-height (depth)
range achievable in 1/4" increments, and the handle/latch/hinge counts used
in that page's worked ordering example.

Fields per case:
- code: the 2-letter VAL-AN case number (e.g. "AA").
- width_in, length_in: outside footprint dimensions, inches.
- thickness_in: .063" or .090" deep-drawn 6061 aluminum shell (AD/AK/AS
  are 1100-0 per the catalog, but that distinction isn't cost-relevant
  here since both are treated as the .063" gauge class).
- height_min_in, height_max_in: the case-height (3rd dimension) range the
  catalog allows, adjustable in 1/4" increments.
- handles, latches, hinges: hardware counts from that case's worked
  ordering example (e.g. "AA1EA16C14 ... with 1 handle; 2 latches; 2
  hinges"). These scale with case size, not independently selectable.
"""

VALAN_CASES = [
    {"code": "AA", "width_in": 4.00, "length_in": 7.00, "thickness_in": 0.063, "height_min_in": 3.25, "height_max_in": 5.00, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "AD", "width_in": 5.00, "length_in": 6.00, "thickness_in": 0.063, "height_min_in": 3.00, "height_max_in": 5.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "AG", "width_in": 5.25, "length_in": 9.75, "thickness_in": 0.063, "height_min_in": 3.00, "height_max_in": 4.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "AK", "width_in": 6.00, "length_in": 7.00, "thickness_in": 0.063, "height_min_in": 3.00, "height_max_in": 5.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "AN", "width_in": 6.19, "length_in": 16.88, "thickness_in": 0.063, "height_min_in": 3.25, "height_max_in": 6.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "AS", "width_in": 7.00, "length_in": 8.00, "thickness_in": 0.063, "height_min_in": 3.00, "height_max_in": 6.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "AV", "width_in": 7.00, "length_in": 9.00, "thickness_in": 0.063, "height_min_in": 3.25, "height_max_in": 7.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "AY", "width_in": 7.00, "length_in": 11.00, "thickness_in": 0.063, "height_min_in": 3.25, "height_max_in": 7.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "HA", "width_in": 7.50, "length_in": 12.00, "thickness_in": 0.090, "height_min_in": 3.50, "height_max_in": 11.75, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "BB", "width_in": 8.00, "length_in": 11.00, "thickness_in": 0.063, "height_min_in": 3.75, "height_max_in": 7.75, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "BE", "width_in": 8.00, "length_in": 14.00, "thickness_in": 0.063, "height_min_in": 3.75, "height_max_in": 7.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "HD", "width_in": 8.50, "length_in": 20.50, "thickness_in": 0.090, "height_min_in": 4.00, "height_max_in": 8.75, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "BH", "width_in": 8.75, "length_in": 12.00, "thickness_in": 0.063, "height_min_in": 3.25, "height_max_in": 8.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "BL", "width_in": 8.75, "length_in": 17.97, "thickness_in": 0.063, "height_min_in": 3.50, "height_max_in": 6.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "BP", "width_in": 9.00, "length_in": 9.00, "thickness_in": 0.063, "height_min_in": 3.25, "height_max_in": 8.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "HG", "width_in": 9.00, "length_in": 27.00, "thickness_in": 0.090, "height_min_in": 3.75, "height_max_in": 7.25, "handles": 1, "latches": 4, "hinges": 2},
    {"code": "BT", "width_in": 9.19, "length_in": 13.25, "thickness_in": 0.063, "height_min_in": 3.50, "height_max_in": 9.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "HK", "width_in": 9.88, "length_in": 20.50, "thickness_in": 0.090, "height_min_in": 4.00, "height_max_in": 7.75, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "BW", "width_in": 10.00, "length_in": 10.38, "thickness_in": 0.063, "height_min_in": 3.25, "height_max_in": 9.00, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "HN", "width_in": 10.00, "length_in": 12.00, "thickness_in": 0.090, "height_min_in": 4.00, "height_max_in": 9.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "HS", "width_in": 10.00, "length_in": 16.00, "thickness_in": 0.090, "height_min_in": 4.00, "height_max_in": 9.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "HV", "width_in": 10.00, "length_in": 18.06, "thickness_in": 0.090, "height_min_in": 4.00, "height_max_in": 9.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "HY", "width_in": 11.00, "length_in": 11.00, "thickness_in": 0.090, "height_min_in": 4.00, "height_max_in": 9.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "JB", "width_in": 11.00, "length_in": 18.00, "thickness_in": 0.090, "height_min_in": 4.00, "height_max_in": 10.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "JE", "width_in": 11.44, "length_in": 13.75, "thickness_in": 0.090, "height_min_in": 3.75, "height_max_in": 10.50, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "JH", "width_in": 11.56, "length_in": 15.06, "thickness_in": 0.090, "height_min_in": 4.00, "height_max_in": 8.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "JL", "width_in": 11.75, "length_in": 27.25, "thickness_in": 0.090, "height_min_in": 3.75, "height_max_in": 9.25, "handles": 1, "latches": 4, "hinges": 2},
    {"code": "JP", "width_in": 12.00, "length_in": 12.00, "thickness_in": 0.090, "height_min_in": 4.00, "height_max_in": 10.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "JT", "width_in": 12.00, "length_in": 18.00, "thickness_in": 0.090, "height_min_in": 4.00, "height_max_in": 10.25, "handles": 1, "latches": 2, "hinges": 2},
    {"code": "JW", "width_in": 12.00, "length_in": 21.50, "thickness_in": 0.090, "height_min_in": 3.75, "height_max_in": 10.25, "handles": 1, "latches": 4, "hinges": 2},
    {"code": "JZ", "width_in": 13.00, "length_in": 22.50, "thickness_in": 0.090, "height_min_in": 3.75, "height_max_in": 8.25, "handles": 1, "latches": 4, "hinges": 2},
    {"code": "KC", "width_in": 13.63, "length_in": 20.63, "thickness_in": 0.090, "height_min_in": 4.25, "height_max_in": 10.25, "handles": 1, "latches": 4, "hinges": 2},
    {"code": "KF", "width_in": 14.50, "length_in": 20.63, "thickness_in": 0.090, "height_min_in": 4.25, "height_max_in": 14.50, "handles": 1, "latches": 4, "hinges": 2},
    {"code": "KJ", "width_in": 15.00, "length_in": 15.50, "thickness_in": 0.090, "height_min_in": 3.75, "height_max_in": 9.25, "handles": 1, "latches": 4, "hinges": 2},
    {"code": "BZ", "width_in": 15.50, "length_in": 30.38, "thickness_in": 0.063, "height_min_in": 3.75, "height_max_in": 8.25, "handles": 2, "latches": 5, "hinges": 3},
    {"code": "KM", "width_in": 15.63, "length_in": 19.13, "thickness_in": 0.090, "height_min_in": 3.75, "height_max_in": 11.25, "handles": 1, "latches": 4, "hinges": 2},
    {"code": "KR", "width_in": 16.13, "length_in": 26.13, "thickness_in": 0.090, "height_min_in": 4.00, "height_max_in": 10.25, "handles": 2, "latches": 5, "hinges": 3},
    {"code": "CC", "width_in": 16.50, "length_in": 20.00, "thickness_in": 0.063, "height_min_in": 3.50, "height_max_in": 10.25, "handles": 1, "latches": 4, "hinges": 2},
    {"code": "KU", "width_in": 16.88, "length_in": 20.13, "thickness_in": 0.090, "height_min_in": 4.50, "height_max_in": 13.25, "handles": 1, "latches": 4, "hinges": 2},
    {"code": "KX", "width_in": 16.94, "length_in": 21.94, "thickness_in": 0.090, "height_min_in": 4.50, "height_max_in": 10.25, "handles": 1, "latches": 4, "hinges": 2},
    {"code": "LA", "width_in": 16.94, "length_in": 32.94, "thickness_in": 0.090, "height_min_in": 4.00, "height_max_in": 14.25, "handles": 2, "latches": 5, "hinges": 3},
    {"code": "LD", "width_in": 17.25, "length_in": 22.88, "thickness_in": 0.090, "height_min_in": 3.75, "height_max_in": 9.25, "handles": 1, "latches": 4, "hinges": 2},
    {"code": "LG", "width_in": 18.00, "length_in": 18.00, "thickness_in": 0.090, "height_min_in": 3.75, "height_max_in": 10.25, "handles": 1, "latches": 4, "hinges": 2},
    {"code": "LK", "width_in": 18.00, "length_in": 27.00, "thickness_in": 0.090, "height_min_in": 4.00, "height_max_in": 10.25, "handles": 2, "latches": 5, "hinges": 3},
    {"code": "CF", "width_in": 18.48, "length_in": 22.13, "thickness_in": 0.063, "height_min_in": 3.50, "height_max_in": 8.25, "handles": 2, "latches": 5, "hinges": 3},
    {"code": "CJ", "width_in": 19.56, "length_in": 21.50, "thickness_in": 0.063, "height_min_in": 3.75, "height_max_in": 10.25, "handles": 2, "latches": 5, "hinges": 3},
    {"code": "LN", "width_in": 20.00, "length_in": 26.00, "thickness_in": 0.090, "height_min_in": 4.25, "height_max_in": 10.25, "handles": 2, "latches": 5, "hinges": 3},
    {"code": "LS", "width_in": 20.13, "length_in": 21.38, "thickness_in": 0.090, "height_min_in": 4.00, "height_max_in": 10.25, "handles": 2, "latches": 5, "hinges": 3},
    {"code": "LV", "width_in": 20.13, "length_in": 32.13, "thickness_in": 0.090, "height_min_in": 4.50, "height_max_in": 10.75, "handles": 2, "latches": 5, "hinges": 3},
    {"code": "LY", "width_in": 24.00, "length_in": 26.00, "thickness_in": 0.090, "height_min_in": 4.25, "height_max_in": 14.00, "handles": 2, "latches": 7, "hinges": 3},
    {"code": "MB", "width_in": 27.25, "length_in": 37.25, "thickness_in": 0.090, "height_min_in": 4.25, "height_max_in": 10.00, "handles": 2, "latches": 7, "hinges": 3},
    {"code": "ME", "width_in": 28.25, "length_in": 28.25, "thickness_in": 0.090, "height_min_in": 4.25, "height_max_in": 9.00, "handles": 2, "latches": 7, "hinges": 3},
]

assert len(VALAN_CASES) == 52
