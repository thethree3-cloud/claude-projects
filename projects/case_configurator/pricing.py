"""Cost-formula quoting for the aluminum case configurator.

Dollar figures in PRICING are grounded in 2026 market research (see sources
below) but are still placeholders, not actual Zerocases costs -- replace
them with real shop numbers before quoting a real customer.

Sources checked 2026-09-16:
- Aluminum sheet, 5052 or 6061 (both used depending on gauge/vendor):
  5052-H32 ~$3.91-$4.23/lb (materialpricebook.com); 6061-T6 distributor
  small-quantity pricing ~$3.68-$5.13/lb depending on thickness
  (materialpricebook.com, hugh-aluminum.com) -> used $4.00/lb either way.
- Custom sheet metal fab shop labor: $70-130/hr depending on region/skill
  (thefabricator.com, insidemetalfab.com) -> used $95/hr (mid-range).
- Powder coating, custom small-run job shop: $8-45/sqft-equivalent once
  labor/setup/masking are folded in (universalpowdercoating.com) -> used
  $6.00/sqft as a conservative custom-run figure; anodizing estimated at a
  similar order of magnitude since a specific 2026 source wasn't found.
- Custom-cut foam: ~$10-30+/cuft depending on density (foamfanatic.com,
  metrofoam4u.com) -> used $18/cuft (mid-range, pick-and-pluck complexity).
- Rubber case bumper feet: ~$0.63-$1.88/piece raw hardware (penn-elcom.com)
  -> used $3.50 each to include mounting labor, not just the part.

Follow-up pass, 2026-09-17 -- Alan asked for closer real numbers on the
two figures flagged above as pure judgment calls. Found real case-grade
(not furniture) part prices and recomputed with labor:
- Case pull handle: Penn Elcom aluminum surface-mount spring-loaded
  handle, EUR3.15-3.78 (~$3.50-4.10) raw part (penn-elcom.com) + ~10 min
  mounting labor at $95/hr (~$16) -> used $20.00/handle (was $14, a pure
  guess with no source).
- 19" rack rail pair: Thon 10U Studio Rack Strip Set, EUR19.90 (~$21.50)
  raw parts (thomann.de) + ~30 min labor to drill/tap mounting holes in
  the case sides (~$47.50) -> used $70.00 flat (was $85, a pure guess).

Material thickness classes (.063"/.090") and the aluminum density figure
come from a real reference: the Zero Manufacturing VAL-AN Series catalog
(customer-provided PDF, 2026-09-16) uses deep-drawn 6061 aluminum shells in
exactly these two gauges, and its own weight formula (.889 lb/sqft at
.063", 1.27 lb/sqft at .090") implies a density of ~0.098 lb/in3 -- used
directly here instead of a generic alloy-density lookup. See
valan_catalog.py for the full 52-size dataset transcribed from that catalog.
"""

from dataclasses import dataclass, field

ALUMINUM_DENSITY_LB_PER_IN3 = 0.098  # derived from the VAL-AN catalog's own weight formula

MATERIAL_THICKNESS_IN = {
    "standard (.063\" 6061)": 0.063,
    "heavy duty (.090\" 6061)": 0.090,
}

PRICING = {
    "aluminum_per_lb": 4.00,
    "labor_rate_per_hr": 95.00,
    "labor_setup_hours": 0.5,
    "labor_minutes_per_sqft": 9,
    "labor_minutes_per_draw": 6,
    "finish_per_sqft": {
        "mill finish": 0.0,
        "black anodized": 5.00,
        "powder coat (custom color)": 6.00,
    },
    "handle_each": 20.00,
    "bumper_each": 3.50,
    "foam_per_cuft": 18.00,
    "rack_rails_flat": 70.00,
    "reinforced_opening_flat": 120.00,
    "mounting_flanges_flat": 90.00,
    "markup_pct": 0.35,
}


@dataclass
class CaseSpec:
    width_in: float
    height_in: float
    depth_in: float
    material: str = "standard (.063\" 6061)"
    finish: str = "mill finish"
    num_draws: int = 4  # forming/bend operations needed to fabricate the case
    handle_count: int = 0
    bumper_count: int = 0
    foam_interior: bool = False
    rack_rails: bool = False
    reinforced_opening: bool = False
    mounting_flanges: bool = False


@dataclass
class QuoteResult:
    line_items: dict = field(default_factory=dict)
    subtotal: float = 0.0
    markup: float = 0.0
    total: float = 0.0


def surface_area_sqft(width_in: float, height_in: float, depth_in: float) -> float:
    sqin = 2 * (width_in * height_in + width_in * depth_in + height_in * depth_in)
    return sqin / 144.0


def interior_volume_cuft(width_in: float, height_in: float, depth_in: float) -> float:
    return (width_in * height_in * depth_in) / 1728.0


def material_cost(area_sqft: float, thickness_in: float, pricing: dict = PRICING) -> float:
    weight_lb = area_sqft * 144.0 * thickness_in * ALUMINUM_DENSITY_LB_PER_IN3
    return weight_lb * pricing["aluminum_per_lb"]


def labor_cost(area_sqft: float, num_draws: int, pricing: dict = PRICING) -> float:
    hours = (
        pricing["labor_setup_hours"]
        + area_sqft * pricing["labor_minutes_per_sqft"] / 60.0
        + num_draws * pricing["labor_minutes_per_draw"] / 60.0
    )
    return hours * pricing["labor_rate_per_hr"]


def compute_quote(spec: CaseSpec, pricing: dict = PRICING) -> QuoteResult:
    if spec.width_in <= 0 or spec.height_in <= 0 or spec.depth_in <= 0:
        raise ValueError("width, height, and depth must all be positive")

    area = surface_area_sqft(spec.width_in, spec.height_in, spec.depth_in)
    thickness = MATERIAL_THICKNESS_IN[spec.material]
    items = {}

    items["material"] = material_cost(area, thickness, pricing)
    items["labor"] = labor_cost(area, spec.num_draws, pricing)
    items["finish"] = area * pricing["finish_per_sqft"][spec.finish]

    if spec.handle_count:
        items["handles"] = spec.handle_count * pricing["handle_each"]
    if spec.bumper_count:
        items["bumpers"] = spec.bumper_count * pricing["bumper_each"]
    if spec.foam_interior:
        volume = interior_volume_cuft(spec.width_in, spec.height_in, spec.depth_in)
        items["foam_interior"] = volume * pricing["foam_per_cuft"]
    if spec.rack_rails:
        items["rack_rails"] = pricing["rack_rails_flat"]
    if spec.reinforced_opening:
        items["reinforced_opening"] = pricing["reinforced_opening_flat"]
    if spec.mounting_flanges:
        items["mounting_flanges"] = pricing["mounting_flanges_flat"]

    subtotal = sum(items.values())
    markup = subtotal * pricing["markup_pct"]
    total = subtotal + markup

    return QuoteResult(line_items=items, subtotal=subtotal, markup=markup, total=total)
