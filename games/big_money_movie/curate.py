"""CLI driver for category pool curation.

Usage:
    python imdb_index.py --build                          # one-time setup
    python curate.py --theme "Cop Movies" --era-start 1970 --era-end 1979

Writes grounded and rejected candidates to
data/pools/<theme-slug>.json for a human to review once before the
grounded list becomes a shipped category pool (per the games_track spec --
this script verifies facts, it doesn't judge whether a title truly fits
the category's feel).
"""
import argparse
import json
import re
import sys
from pathlib import Path

from generate_pool import generate_category_pool
from imdb_index import INDEX_DB

BASE_DIR = Path(__file__).resolve().parent
POOLS_DIR = BASE_DIR / "data" / "pools"


def slugify(theme):
    return re.sub(r"[^a-z0-9]+", "-", theme.lower()).strip("-")


def main():
    parser = argparse.ArgumentParser(description="Curate a Big Money Movie category pool.")
    parser.add_argument("--theme", required=True, help='e.g. "Cop Movies"')
    parser.add_argument("--era-start", type=int, required=True)
    parser.add_argument("--era-end", type=int, required=True)
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()

    if not INDEX_DB.exists():
        print(f"No IMDb index at {INDEX_DB}. Run: python imdb_index.py --build")
        sys.exit(1)

    candidates = generate_category_pool(
        theme=args.theme, era_start=args.era_start, era_end=args.era_end, count=args.count
    )

    grounded = [c for c in candidates if c.grounded]
    rejected = [c for c in candidates if not c.grounded]

    POOLS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = POOLS_DIR / f"{slugify(args.theme)}.json"
    out_path.write_text(
        json.dumps(
            {
                "theme": args.theme,
                "era_start": args.era_start,
                "era_end": args.era_end,
                "grounded": [c.to_dict() for c in grounded],
                "rejected": [c.to_dict() for c in rejected],
            },
            indent=2,
        )
    )

    print(f"{len(grounded)}/{len(candidates)} candidates grounded -> {out_path}")
    if rejected:
        print("Rejected (review these -- Claude hallucination, or a real gap in the index):")
        for c in rejected:
            print(f"  - {c.proposed_title} ({c.proposed_year}): {c.rejection_reason}")


if __name__ == "__main__":
    main()
