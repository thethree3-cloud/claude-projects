"""Build a synthetic historical quote database from the real box sample.

Same approach as case_configurator/generate_quote_history.py: real
dimensions/gauge from deep_draw_catalog.py, prices computed via
deep_draw_pricing.py plus random noise so they scatter like real quotes
would, while still trending reliably more expensive for bigger/thicker/
deeper boxes. Each row also varies height (within the catalog's real
allowed range), cover type, and nutplate pattern.
"""

import random
import sqlite3
from pathlib import Path

from deep_draw_catalog import DEEP_DRAW_BOXES, COVER_TYPES, NUTPLATE_PATTERNS
from deep_draw_pricing import compute_box_quote

DB_PATH = Path(__file__).parent / "data" / "quote_history.db"
NUM_ROWS = 1000
RANDOM_SEED = 42

COVER_WEIGHTS = [0.5, 0.2, 0.1, 0.08, 0.07, 0.05]  # none is most common
NUTPLATE_WEIGHTS = [0.7] + [0.3 / (len(NUTPLATE_PATTERNS) - 1)] * (len(NUTPLATE_PATTERNS) - 1)


def _sample_height(rng: random.Random, height_min: float, height_max: float) -> float:
    if height_max <= height_min:
        return height_min
    steps = max(1, round((height_max - height_min) / 0.25))
    step = rng.randint(0, steps)
    return round(height_min + step * 0.25, 2)


def _simulate_quote(rng: random.Random) -> dict:
    box = rng.choice(DEEP_DRAW_BOXES)
    height = _sample_height(rng, box["height_min_in"], box["height_max_in"])
    cover_type = rng.choices(COVER_TYPES, weights=COVER_WEIGHTS, k=1)[0]
    nutplate_pattern = rng.choices(NUTPLATE_PATTERNS, weights=NUTPLATE_WEIGHTS, k=1)[0]

    quote = compute_box_quote(
        width_in=box["width_in"],
        length_in=box["length_in"],
        height_in=height,
        gauge_in=box["gauge_in"],
        cover_type=cover_type,
        nutplate_pattern=nutplate_pattern,
    )

    noise_factor = rng.gauss(1.0, 0.12)
    price = max(quote["total"] * noise_factor, quote["total"] * 0.7)
    price = round(price / 5.0) * 5.0

    return {
        "part_no": box["part_no"],
        "width_in": box["width_in"],
        "length_in": box["length_in"],
        "height_in": height,
        "gauge_in": box["gauge_in"],
        "num_draws": quote["num_draws"],
        "cover_type": cover_type,
        "nutplate_pattern": nutplate_pattern,
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
                cover_type TEXT,
                nutplate_pattern TEXT,
                price REAL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO quotes
                (part_no, width_in, length_in, height_in, gauge_in, num_draws,
                 cover_type, nutplate_pattern, price)
            VALUES
                (:part_no, :width_in, :length_in, :height_in, :gauge_in, :num_draws,
                 :cover_type, :nutplate_pattern, :price)
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
