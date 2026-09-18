"""Build a synthetic historical quote database for Round Housings.

Same approach as generate_quote_history.py (main series) and
generate_mini_quote_history.py (ZMR/ZMS/ZMC): real dimensions from
deep_draw_catalog.py, prices computed via deep_draw_pricing.py plus
random noise so they scatter like real quotes would. Its own db file,
kept separate from both the main series' and the mini-series' history --
Round Housings is a distinct top-level catalog section from either.

Height isn't varied here: the catalog publishes only one max height per
size, no adjustable range (same situation as the mini-series), so every
simulated quote uses that fixed height.
"""

import random
import sqlite3
from pathlib import Path

from deep_draw_catalog import ROUND_HOUSINGS
from deep_draw_pricing import compute_round_housing_quote

DB_PATH = Path(__file__).parent / "data" / "round_housing_quote_history.db"
NUM_ROWS = 1000
RANDOM_SEED = 42

FINISH_WEIGHTS = {"mill finish": 0.6, "black anodized": 0.25, "powder coat (custom color)": 0.15}


def _simulate_quote(rng: random.Random) -> dict:
    box = rng.choice(ROUND_HOUSINGS)
    finish = rng.choices(list(FINISH_WEIGHTS), weights=list(FINISH_WEIGHTS.values()), k=1)[0]
    height = box["height_max_in"]

    quote = compute_round_housing_quote(
        diameter_in=box["diameter_in"],
        height_in=height,
        gauge_in=box["gauge_in"],
        finish=finish,
    )

    noise_factor = rng.gauss(1.0, 0.12)
    price = max(quote["total"] * noise_factor, quote["total"] * 0.7)
    price = round(price / 5.0) * 5.0

    return {
        "part_no": box["part_no"],
        "width_in": box["diameter_in"],
        "length_in": box["diameter_in"],
        "height_in": height,
        "gauge_in": box["gauge_in"],
        "num_draws": quote["num_draws"],
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
                finish TEXT,
                price REAL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO quotes
                (part_no, width_in, length_in, height_in, gauge_in, num_draws, finish, price)
            VALUES
                (:part_no, :width_in, :length_in, :height_in, :gauge_in, :num_draws, :finish, :price)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    rows = generate()
    write_to_db(rows)
    print(f"Wrote {len(rows)} synthetic round-housing quotes to {DB_PATH}")
