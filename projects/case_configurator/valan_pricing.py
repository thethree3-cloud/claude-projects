"""Cost model for VAL-AN-style cases, used only to generate the synthetic
quote-history database (see generate_quote_history.py).

Reuses the material/labor base costs from pricing.py (already sourced) and
adds hardware costs specific to this real catalog's construction: latches,
hinges, and a pressure-relief valve, plus a small adder for instrument-type
cases (which always carry feet on the bottom AND rear, per the catalog's
CASE TYPES note, vs. combination/transit cases which often don't).

Hardware sources checked 2026-09-16, refined 2026-09-17 (still placeholders,
not real Zerocases invoices, but now grounded in real product prices):
- Spring-loaded draw latches: ~$0.81-$14/each depending on grade
  (sugatsune.com, amazon) -> used $9.00 each (mid-range, mil-spec grade).
- Case hinges: no exact case-hinge-each price was found (most case hinge
  listings are continuous hinge sold by the foot); closest comparable is a
  small aluminum butt hinge w/ mounting hardware at $7.45 (fazstore.ca,
  McMaster-equivalent part) -> used $8.00 each, up from a $6 pure guess.
  Flagged: this comparable is a T-slot-framing hinge, not a case hinge, so
  still worth replacing with a real invoice number.
- Automatic vs. manual pressure relief valve: real retail prices found for
  SKB case valves -- automatic (3SKB-V5) $44.99, manual (3SKB-V12) $19.99
  (specialtycases.com) -> used the $25.00 delta directly, up from an
  unsourced $15 guess.
- Instrument case type (feet on bottom AND rear vs. combination/transit's
  conditional feet, per the catalog's CASE TYPES note): a $25 flat adder
  for the extra feet/hardware, still a judgment call -- no source found.
"""

from pricing import PRICING, surface_area_sqft, material_cost, labor_cost

VALAN_PRICING = {
    "latch_each": 9.00,
    "hinge_each": 8.00,
    "valve_automatic_adder": 25.00,
    "instrument_case_adder": 25.00,
}

CASE_TYPES = {1: "combination", 2: "transit", 3: "instrument"}
VALVE_TYPES = {"A": "automatic", "M": "manual"}


def compute_valan_price(
    width_in: float,
    length_in: float,
    height_in: float,
    thickness_in: float,
    handles: int,
    latches: int,
    hinges: int,
    case_type: int = 1,
    valve: str = "A",
    finish: str = "mill finish",
    pricing: dict = PRICING,
    valan_pricing: dict = VALAN_PRICING,
) -> float:
    area = surface_area_sqft(width_in, length_in, height_in)
    num_draws = handles + latches + hinges  # forming/assembly complexity proxy

    cost = material_cost(area, thickness_in, pricing)
    cost += labor_cost(area, num_draws, pricing)
    cost += area * pricing["finish_per_sqft"][finish]
    cost += handles * pricing["handle_each"]
    cost += latches * valan_pricing["latch_each"]
    cost += hinges * valan_pricing["hinge_each"]

    if valve == "A":
        cost += valan_pricing["valve_automatic_adder"]
    if case_type == 3:
        cost += valan_pricing["instrument_case_adder"]

    return cost * (1 + pricing["markup_pct"])
