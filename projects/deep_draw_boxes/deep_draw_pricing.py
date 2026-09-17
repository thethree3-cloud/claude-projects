"""Cost model for Zero Manufacturing-style deep-drawn boxes.

These are raw, open-top drawn shells (bottom + 4 sides, no lid) -- covers
and nutplates are separate, optional add-ons per the catalog's own
modular ordering system (see deep_draw_catalog.py). This is a different
shape/cost model than case_configurator's fully-enclosed CaseSpec, and is
kept as its own separate tool per the user's instruction to keep each
catalog/product line separate rather than merging them.

Sources (2026-09-16, same research pass as case_configurator/pricing.py):
- Aluminum sheet (here 6061-0 specifically, matching every row in the
  sampled catalog pages): ~$4.00/lb, same figure used elsewhere.
- Aluminum density: 0.098 lb/in3, matching the 6061 figure derived from
  the VAL-AN catalog's own weight formula (case_configurator/pricing.py);
  not re-derived from this catalog since it doesn't publish one.
- Custom sheet metal fab shop labor: ~$95/hr, same sourced figure.
- Cover-type and nutplate hardware costs are placeholders (judgment
  calls, not sourced) -- flag if real invoice numbers become available.

Draw-count estimate: the catalog states wall thickness depends on "depth
of draw, number of draws, and net blank thickness" but does NOT publish a
per-part draw count (it's an internal engineering variable, confirmed in
the catalog text and glossary). num_draws here is an ENGINEERING
APPROXIMATION, not a catalog figure: deeper cavities relative to their
opening width need more successive draw/redraw passes before the metal
would tear. Modeled as ceil(height / (0.6 * min(width, length))), floored
at 1 -- a simplified proxy, not a citation to a specific published
draw-ratio table.
"""

import math

ALUMINUM_DENSITY_LB_PER_IN3 = 0.098
ALLOY = "6061-0"

PRICING = {
    "aluminum_per_lb": 4.00,
    "labor_rate_per_hr": 95.00,
    "labor_setup_hours": 0.4,
    "labor_minutes_per_sqft": 8,
    "labor_minutes_per_draw": 5,
    "markup_pct": 0.35,
    # Cover types (catalog pg. 38): flat adders reflecting relative
    # complexity (CF flush-fit is simplest; COG gasket-fit needs a groove
    # + optional gasket). All placeholders.
    "cover_adder": {
        "none": 0.0,
        "CF": 8.0,
        "CI": 10.0,
        "COT": 9.0,
        "COL": 9.0,
        "COG": 14.0,
    },
    "nutplate_each": 1.25,  # hardware + installation, placeholder
}


def estimate_num_draws(width_in: float, length_in: float, height_in: float) -> int:
    opening = min(width_in, length_in)
    return max(1, math.ceil(height_in / (0.6 * opening)))


def open_box_surface_area_sqft(width_in: float, length_in: float, height_in: float) -> float:
    # Bottom + 4 sides; no lid (open-top shell).
    sqin = width_in * length_in + 2 * (width_in + length_in) * height_in
    return sqin / 144.0


def material_cost(area_sqft: float, gauge_in: float, pricing: dict = PRICING) -> float:
    weight_lb = area_sqft * 144.0 * gauge_in * ALUMINUM_DENSITY_LB_PER_IN3
    return weight_lb * pricing["aluminum_per_lb"]


def labor_cost(area_sqft: float, num_draws: int, pricing: dict = PRICING) -> float:
    hours = (
        pricing["labor_setup_hours"]
        + area_sqft * pricing["labor_minutes_per_sqft"] / 60.0
        + num_draws * pricing["labor_minutes_per_draw"] / 60.0
    )
    return hours * pricing["labor_rate_per_hr"]


def cover_cost(width_in: float, length_in: float, gauge_in: float, cover_type: str, pricing: dict = PRICING) -> float:
    if cover_type == "none":
        return 0.0
    footprint_sqft = (width_in * length_in) / 144.0
    return material_cost(footprint_sqft, gauge_in, pricing) + pricing["cover_adder"][cover_type]


def nutplate_count(width_in: float, length_in: float) -> int:
    perimeter_in = 2 * (width_in + length_in)
    return max(4, math.ceil(perimeter_in / 4.0))  # spaced no more than 4" apart


def nutplate_cost(width_in: float, length_in: float, pattern: str, pricing: dict = PRICING) -> float:
    if pattern == "none":
        return 0.0
    return nutplate_count(width_in, length_in) * pricing["nutplate_each"]


def compute_box_quote(
    width_in: float,
    length_in: float,
    height_in: float,
    gauge_in: float,
    cover_type: str = "none",
    nutplate_pattern: str = "none",
    pricing: dict = PRICING,
) -> dict:
    if width_in <= 0 or length_in <= 0 or height_in <= 0:
        raise ValueError("width, length, and height must all be positive")

    num_draws = estimate_num_draws(width_in, length_in, height_in)
    area = open_box_surface_area_sqft(width_in, length_in, height_in)

    items = {
        "material": material_cost(area, gauge_in, pricing),
        "labor": labor_cost(area, num_draws, pricing),
    }
    cover = cover_cost(width_in, length_in, gauge_in, cover_type, pricing)
    if cover:
        items["cover"] = cover
    nutplates = nutplate_cost(width_in, length_in, nutplate_pattern, pricing)
    if nutplates:
        items["nutplates"] = nutplates

    subtotal = sum(items.values())
    markup = subtotal * pricing["markup_pct"]
    total = subtotal + markup

    return {
        "num_draws": num_draws,
        "line_items": items,
        "subtotal": subtotal,
        "markup": markup,
        "total": total,
    }
