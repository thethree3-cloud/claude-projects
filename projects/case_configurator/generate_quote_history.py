"""Build a synthetic ~2,000-row historical quote database.

The DIMENSIONS, thickness, and handle/latch/hinge hardware counts are REAL
-- transcribed from the Zero Manufacturing VAL-AN Series catalog (see
valan_catalog.py). The PRICES are synthetic: computed from the same cost
model as pricing.py/valan_pricing.py plus random noise, so they scatter
realistically (like real quotes would) while still trending reliably more
expensive for bigger/thicker/more-complex cases.

Each row samples one of the 52 real case sizes, a height within that case's
real catalog-allowed range (rounded to the nearest 1/4", matching the
catalog's real ordering granularity), and a case type / valve / finish
combination -- so the ~2,000 rows are variations on real, catalog-aligned
configurations, not arbitrary dimensions.
"""

import random
import sqlite3
from pathlib import Path

from pricing import MATERIAL_THICKNESS_IN
from valan_catalog import VALAN_CASES
from valan_pricing import CASE_TYPES, VALVE_TYPES, compute_valan_price

DB_PATH = Path(__file__).parent / "data" / "quote_history.db"
NUM_ROWS = 2000
RANDOM_SEED = 42

CASE_TYPE_WEIGHTS = {1: 0.6, 2: 0.3, 3: 0.1}  # combination cases are most common
VALVE_WEIGHTS = {"A": 0.7, "M": 0.3}
FINISHES = ["mill finish", "black anodized", "powder coat (custom color)"]
FINISH_WEIGHTS = [0.5, 0.3, 0.2]

MATERIAL_LABEL_BY_THICKNESS = {v: k for k, v in MATERIAL_THICKNESS_IN.items()}


def _sample_height(rng: random.Random, height_min: float, height_max: float) -> float:
    steps = max(1, round((height_max - height_min) / 0.25))
    step = rng.randint(0, steps)
    return round(height_min + step * 0.25, 2)


def _simulate_quote(rng: random.Random) -> dict:
    case = rng.choice(VALAN_CASES)
    height = _sample_height(rng, case["height_min_in"], case["height_max_in"])
    case_type = rng.choices(list(CASE_TYPE_WEIGHTS.keys()), weights=list(CASE_TYPE_WEIGHTS.values()), k=1)[0]
    valve = rng.choices(list(VALVE_WEIGHTS.keys()), weights=list(VALVE_WEIGHTS.values()), k=1)[0]
    finish = rng.choices(FINISHES, weights=FINISH_WEIGHTS, k=1)[0]

    base_price = compute_valan_price(
        width_in=case["width_in"],
        length_in=case["length_in"],
        height_in=height,
        thickness_in=case["thickness_in"],
        handles=case["handles"],
        latches=case["latches"],
        hinges=case["hinges"],
        case_type=case_type,
        valve=valve,
        finish=finish,
    )

    # Real historical quotes scatter around the "true" cost -- different
    # estimators, rush jobs, negotiated discounts, etc.
    noise_factor = rng.gauss(1.0, 0.12)
    price = max(base_price * noise_factor, base_price * 0.7)
    price = round(price / 5.0) * 5.0  # shops quote in round numbers

    return {
        "case_code": case["code"],
        "width_in": case["width_in"],
        "height_in": case["length_in"],
        "depth_in": height,
        "thickness_in": case["thickness_in"],
        "num_draws": case["handles"] + case["latches"] + case["hinges"],
        "case_type": CASE_TYPES[case_type],
        "valve": VALVE_TYPES[valve],
        "material": MATERIAL_LABEL_BY_THICKNESS[case["thickness_in"]],
        "finish": finish,
        "price": price,
    }


def generate(num_rows: int = NUM_ROWS, seed: int = RANDOM_SEED) -> list[dict]:
    rng = random.Random(seed)
    return [_simulate_quote(rng) for _ in range(num_rows)]


def write_to_db(rows: list[dict], db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS quotes")
        conn.execute(
            """
            CREATE TABLE quotes (
                id INTEGER PRIMARY KEY,
                case_code TEXT,
                width_in REAL,
                height_in REAL,
                depth_in REAL,
                thickness_in REAL,
                num_draws INTEGER,
                case_type TEXT,
                valve TEXT,
                material TEXT,
                finish TEXT,
                price REAL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO quotes
                (case_code, width_in, height_in, depth_in, thickness_in, num_draws,
                 case_type, valve, material, finish, price)
            VALUES
                (:case_code, :width_in, :height_in, :depth_in, :thickness_in, :num_draws,
                 :case_type, :valve, :material, :finish, :price)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    rows = generate()
    write_to_db(rows)
    print(f"Wrote {len(rows)} synthetic quotes to {DB_PATH}")
