"""Look up similar past quotes from the synthetic quote-history database.

Same pattern as case_configurator/quote_lookup.py: find historical quotes
for similar-sized/similar-complexity boxes and report both an average
price and a confidence score based on how much matching data exists.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "quote_history.db"

DIMENSION_TOLERANCE_PCT = 0.25
MIN_MATCHES_FOR_FULL_CONFIDENCE = 20


@dataclass
class HistoryEstimate:
    match_count: int
    avg_price: float
    min_price: float
    max_price: float
    confidence: float  # 0.0-1.0


def load_quotes(db_path: Path = DB_PATH) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM quotes").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _within_tolerance(value: float, target: float, pct: float = DIMENSION_TOLERANCE_PCT) -> bool:
    return abs(value - target) <= target * pct


def find_similar_quotes(
    quotes: list[dict],
    width_in: float,
    length_in: float,
    height_in: float,
    dimension_tolerance_pct: float = DIMENSION_TOLERANCE_PCT,
) -> list[dict]:
    matches = []
    for row in quotes:
        if not _within_tolerance(row["width_in"], width_in, dimension_tolerance_pct):
            continue
        if not _within_tolerance(row["length_in"], length_in, dimension_tolerance_pct):
            continue
        if not _within_tolerance(row["height_in"], height_in, dimension_tolerance_pct):
            continue
        matches.append(row)
    return matches


def estimate_from_history(
    quotes: list[dict],
    width_in: float,
    length_in: float,
    height_in: float,
) -> HistoryEstimate | None:
    matches = find_similar_quotes(quotes, width_in, length_in, height_in)
    if not matches:
        return None

    prices = [row["price"] for row in matches]
    confidence = min(1.0, len(matches) / MIN_MATCHES_FOR_FULL_CONFIDENCE)

    return HistoryEstimate(
        match_count=len(matches),
        avg_price=sum(prices) / len(prices),
        min_price=min(prices),
        max_price=max(prices),
        confidence=confidence,
    )
