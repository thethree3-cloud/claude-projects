"""Cost model for the ZMR/ZMS miniature box series.

These are a different part of the same Zero Manufacturing Deep Drawn
catalog as deep_draw_pricing.py's main Rectangular Boxes series, but with
a genuinely different spec: instead of a direct gauge and a height range,
each row gives a material THICKNESS CODE (A/B/C) that resolves to a
different actual thickness depending which of four materials it's drawn
in (steel/aluminum/brass/Monel), a single fixed maximum depth (no
published minimum), and usually one combined R1/R2 radius (occasionally
two distinct ones) instead of always-separate values. See
deep_draw_catalog.py's docstring for the code table and the handful of
special-gauge/ambiguous-code rows.

Sources checked 2026-09-18 (same research-and-cite approach as
deep_draw_pricing.py and case_configurator/pricing.py):
- Aluminum: reuses the existing $4.00/lb, 0.098 lb/in3 figures already
  sourced for the main series (materialpricebook.com, hugh-aluminum.com).
- Steel (A1008 cold-rolled, the catalog's "ST" gauge column): general
  small-quantity market pricing runs $0.70-$1.60/lb depending on
  quantity/thickness (procurementresource.com, latestcost.com,
  vmtcnc.com) -> used $1.50/lb, the top of that band, consistent with
  this tool's practice of picking the higher end of a sourced range for
  small custom-run jobs. Density 0.284 lb/in3 is the standard figure for
  AISI 1008/1010 low-carbon steel.
- Brass (C260 cartridge brass, the catalog's "BR" gauge column): got an
  actual distributor price, not just a market range -- Alcobra Metals'
  .020" C260 sheet (half-hard) is $14.81 for a 12"x12" piece and $177.77
  for 36"x48" (alcobrametals.com); both back out to the same $16.70/lb
  at 0.308 lb/in3 (8.53 g/cm3, standard C260 density per ASTM B36),
  confirming the figure rather than just picking a range midpoint.
- Monel 400 (the catalog's "MU" gauge column): factory/market price
  $13-$22/lb, trending up in 2026 (ncalloys.com, huaxiao-alloy.com,
  price-watch.ai); used $20.00/lb, near the top of that band for the
  same small-custom-run reasoning as steel. Density 0.319 lb/in3
  (8.83 g/cm3) is the standard figure for Monel 400.
- Labor rate and finish-coat pricing reuse deep_draw_pricing.PRICING's
  already-sourced figures -- same fab shop, same job-shop labor market,
  same powder-coat/anodize process regardless of which base metal is
  underneath.

Not modeled (documented limitation, not a silent gap): a few rows use a
literal gauge instead of a material code (flagged "Special Gauge" in the
catalog, no alloy specified) -- MATERIALS_BY_CODE lookup is skipped for
those and the printed gauge is used as-is regardless of material chosen.
One row (ZMR-094-112) lists code "A/B" ambiguously; treated as "A".
Two rows carry footnotes restricting them to a subset of materials
(not available in aluminum / not available in brass); those
restrictions aren't enforced here, so every material stays selectable
for every row.
"""

from deep_draw_pricing import PRICING as MAIN_PRICING, estimate_num_draws

MATERIALS = {
    "AL": {"label": "Aluminum (6061-0)", "density_lb_per_in3": 0.098, "price_per_lb": 4.00},
    "ST": {"label": "Steel (A1008 cold-rolled)", "density_lb_per_in3": 0.284, "price_per_lb": 1.50},
    "BR": {"label": "Brass (C260)", "density_lb_per_in3": 0.308, "price_per_lb": 16.70},
    "MU": {"label": "Monel 400", "density_lb_per_in3": 0.319, "price_per_lb": 20.00},
}

# Material thickness code -> gauge (inches) per material, from the
# catalog's "MATERIAL THICKNESS CODE" table (same for both ZMR and ZMS).
MATERIAL_THICKNESS_CODE = {
    "A": {"ST": 0.018, "AL": 0.020, "BR": 0.020, "MU": 0.020},
    "B": {"ST": 0.024, "AL": 0.025, "BR": 0.025, "MU": 0.025},
    "C": {"ST": 0.029, "AL": 0.032, "BR": 0.032, "MU": 0.031},
}

LABOR_SETUP_HOURS = 0.25
LABOR_MINUTES_PER_SQFT = 8
LABOR_MINUTES_PER_DRAW = 5


def resolve_gauge_in(material_code: str, gauge_override_in, material_key: str) -> float:
    if gauge_override_in:
        return gauge_override_in
    return MATERIAL_THICKNESS_CODE[material_code][material_key]


def open_box_surface_area_sqft(width_in: float, length_in: float, height_in: float) -> float:
    sqin = width_in * length_in + 2 * (width_in + length_in) * height_in
    return sqin / 144.0


def material_cost(area_sqft: float, gauge_in: float, material_key: str) -> float:
    density = MATERIALS[material_key]["density_lb_per_in3"]
    price_per_lb = MATERIALS[material_key]["price_per_lb"]
    weight_lb = area_sqft * 144.0 * gauge_in * density
    return weight_lb * price_per_lb


def labor_cost(area_sqft: float, num_draws: int) -> float:
    hours = (
        LABOR_SETUP_HOURS
        + area_sqft * LABOR_MINUTES_PER_SQFT / 60.0
        + num_draws * LABOR_MINUTES_PER_DRAW / 60.0
    )
    return hours * MAIN_PRICING["labor_rate_per_hr"]


def compute_mini_box_quote(
    width_in: float,
    length_in: float,
    height_in: float,
    material_code: str,
    gauge_override_in,
    material_key: str,
    finish: str = "mill finish",
) -> dict:
    if width_in <= 0 or length_in <= 0 or height_in <= 0:
        raise ValueError("width, length, and height must all be positive")

    gauge_in = resolve_gauge_in(material_code, gauge_override_in, material_key)
    num_draws = estimate_num_draws(width_in, length_in, height_in)
    area = open_box_surface_area_sqft(width_in, length_in, height_in)

    items = {
        "material": material_cost(area, gauge_in, material_key),
        "labor": labor_cost(area, num_draws),
        "finish": area * MAIN_PRICING["finish_per_sqft"][finish],
    }

    subtotal = sum(items.values())
    markup = subtotal * MAIN_PRICING["markup_pct"]
    total = subtotal + markup

    return {
        "gauge_in": gauge_in,
        "num_draws": num_draws,
        "line_items": items,
        "subtotal": subtotal,
        "markup": markup,
        "total": total,
    }
