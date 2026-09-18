"""Build a synthetic historical quote database for the ZMR/ZMS/ZMC mini-series.

Same approach as generate_quote_history.py (main series): real dimensions
from deep_draw_catalog.py, prices computed via mini_series_pricing.py plus
random noise so they scatter like real quotes would. Written to a separate
db file from the main series' history -- the two catalogs' size ranges
overlap a little at the boundary (mini-series tops out at ~4" wide, main
series starts at ~0.5"), and keeping them in separate tables avoids a
mini box ever matching against a main-series quote or vice versa.

Height isn't varied here: unlike the main series, the catalog publishes
only one max depth per mini-series size, no adjustable range, so every
simulated quote uses that fixed depth.

ZMC (circular) rows have no width_in/length_in of their own -- a round
part's diameter is stored as both, so the shared quote_lookup.py matching
(which is dimension-based, not shape-aware) still works for it.
"""

import random
import sqlite3
from pathlib import Path

from deep_draw_catalog import ZMS_BOXES, ZMR_BOXES, ZMC_BOXES
from mini_series_pricing import compute_mini_box_quote, compute_mini_can_quote

DB_PATH = Path(__file__).parent / "data" / "mini_quote_history.db"
NUM_ROWS = 1000
RANDOM_SEED = 42

MATERIAL_WEIGHTS = {"AL": 0.55, "ST": 0.25, "BR": 0.12, "MU": 0.08}
FINISH_WEIGHTS = {"mill finish": 0.6, "black anodized": 0.25, "powder coat (custom color)": 0.15}


def _simulate_quote(rng: random.Random) -> dict:
    box = rng.choice(ZMS_BOXES + ZMR_BOXES + ZMC_BOXES)
    material_key = rng.choices(list(MATERIAL_WEIGHTS), weights=list(MATERIAL_WEIGHTS.values()), k=1)[0]
    finish = rng.choices(list(FINISH_WEIGHTS), weights=list(FINISH_WEIGHTS.values()), k=1)[0]
    height = box["max_depth_in"]
    is_round = "diameter_in" in box

    if is_round:
        width_in = length_in = box["diameter_in"]
        quote = compute_mini_can_quote(
            diameter_in=box["diameter_in"],
            height_in=height,
            material_code=box["material_code"],
            gauge_override_in=box["gauge_override_in"],
            material_key=material_key,
            finish=finish,
        )
    else:
        width_in, length_in = box["width_in"], box["length_in"]
        quote = compute_mini_box_quote(
            width_in=width_in,
            length_in=length_in,
            height_in=height,
            material_code=box["material_code"],
            gauge_override_in=box["gauge_override_in"],
            material_key=material_key,
            finish=finish,
        )

    noise_factor = rng.gauss(1.0, 0.12)
    price = max(quote["total"] * noise_factor, quote["total"] * 0.7)
    price = round(price / 5.0) * 5.0

    return {
        "part_no": box["part_no"],
        "width_in": width_in,
        "length_in": length_in,
        "height_in": height,
        "gauge_in": quote["gauge_in"],
        "num_draws": quote["num_draws"],
        "material_key": material_key,
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
                part_no TEXT,
                width_in REAL,
                length_in REAL,
                height_in REAL,
                gauge_in REAL,
                num_draws INTEGER,
                material_key TEXT,
                finish TEXT,
                price REAL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO quotes
                (part_no, width_in, length_in, height_in, gauge_in, num_draws,
                 material_key, finish, price)
            VALUES
                (:part_no, :width_in, :length_in, :height_in, :gauge_in, :num_draws,
                 :material_key, :finish, :price)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    rows = generate()
    write_to_db(rows)
    print(f"Wrote {len(rows)} synthetic mini-series quotes to {DB_PATH}")
