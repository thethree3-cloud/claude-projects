"""Local grounding index built from IMDb's free non-commercial dataset
(https://datasets.imdbws.com/, title.basics.tsv.gz).

generate_pool.py uses this to verify Claude's proposed category-pool titles
against real data before they're eligible for a puzzle -- same
"LLM proposes, data verifies" pattern as Project 01's handbook grounding
and Project 11's SQL generation. Nothing here calls the Anthropic API.

One-time setup:
    python imdb_index.py --build

Re-run with --build again any time to refresh from a newer IMDb dump
(the dataset is refreshed daily upstream, but a stale local copy is fine
for this game -- movie release years don't change).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import re
import sqlite3
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_TSV_GZ = DATA_DIR / "title.basics.tsv.gz"
INDEX_DB = DATA_DIR / "imdb_index.sqlite"

IMDB_BASICS_URL = "https://datasets.imdbws.com/title.basics.tsv.gz"

# Title types worth keeping for a movie/TV-title guessing game -- excludes
# tvEpisode (too granular), short, video, videoGame, tvShort.
KEEP_TITLE_TYPES = {"movie", "tvMovie", "tvSeries", "tvMiniSeries", "tvSpecial"}


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace -- so Claude's
    proposed title text matches IMDb's primaryTitle regardless of minor
    punctuation/casing differences ("Dirty Harry" vs "dirty harry!").
    Canonicalizes "&" to "and" first: found via live testing that IMDb and
    Claude don't always agree on which spelling a title uses (IMDb has the
    1975 TV series as "Starsky and Hutch", Claude proposed "Starsky &
    Hutch") -- without this, that class of title would wrongly ground
    against an unrelated same-named entry (or fail to ground at all)."""
    title = title.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", title).strip()


def download_basics(force: bool = False) -> Path:
    """Download IMDb's title.basics.tsv.gz if not already present."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if RAW_TSV_GZ.exists() and not force:
        return RAW_TSV_GZ
    print(f"Downloading {IMDB_BASICS_URL} ...")
    urllib.request.urlretrieve(IMDB_BASICS_URL, RAW_TSV_GZ)
    return RAW_TSV_GZ


def build_index(force: bool = False, force_download: bool = False) -> Path:
    """Parse the gzipped TSV once and load it into a local SQLite index,
    filtered to title types relevant to this game and indexed by
    normalized title for fast lookups. `force` rebuilds the SQLite index
    from the already-downloaded raw TSV (e.g. after a normalize_title
    change); `force_download` additionally re-pulls the raw dataset from
    IMDb -- the two are independent so a code-only rebuild doesn't re-pull
    a 227MB file that hasn't changed."""
    if INDEX_DB.exists() and not force and not force_download:
        return INDEX_DB

    tsv_path = download_basics(force=force_download)

    if INDEX_DB.exists():
        INDEX_DB.unlink()

    conn = sqlite3.connect(INDEX_DB)
    conn.execute(
        """
        CREATE TABLE titles (
            tconst TEXT PRIMARY KEY,
            primary_title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            title_type TEXT NOT NULL,
            start_year INTEGER,
            genres TEXT
        )
        """
    )
    conn.execute("CREATE INDEX idx_normalized_title ON titles(normalized_title)")

    inserted = 0
    batch = []
    with gzip.open(tsv_path, "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row["titleType"] not in KEEP_TITLE_TYPES:
                continue
            if row.get("isAdult") == "1":
                continue
            year_raw = row.get("startYear", "\\N")
            year = int(year_raw) if year_raw and year_raw != "\\N" else None
            primary_title = row["primaryTitle"]
            genres_raw = row.get("genres")
            batch.append(
                (
                    row["tconst"],
                    primary_title,
                    normalize_title(primary_title),
                    row["titleType"],
                    year,
                    None if genres_raw in (None, "\\N") else genres_raw,
                )
            )
            if len(batch) >= 5000:
                conn.executemany("INSERT INTO titles VALUES (?,?,?,?,?,?)", batch)
                inserted += len(batch)
                batch.clear()
    if batch:
        conn.executemany("INSERT INTO titles VALUES (?,?,?,?,?,?)", batch)
        inserted += len(batch)

    conn.commit()
    conn.close()
    print(f"Indexed {inserted} titles into {INDEX_DB}")
    return INDEX_DB


@dataclass
class GroundedTitle:
    tconst: str
    primary_title: str
    title_type: str
    start_year: int | None
    genres: list[str]


def lookup(
    conn: sqlite3.Connection,
    title: str,
    expected_year: int | None = None,
    year_tolerance: int = 2,
) -> GroundedTitle | None:
    """Look up a candidate title in the local index. When multiple entries
    share the normalized title (remakes, a movie and a TV version, etc.),
    prefer the one closest to expected_year -- but only accept it within
    year_tolerance, so an unrelated same-named title doesn't silently
    ground a wrong candidate."""
    norm = normalize_title(title)
    rows = conn.execute(
        "SELECT tconst, primary_title, title_type, start_year, genres "
        "FROM titles WHERE normalized_title = ?",
        (norm,),
    ).fetchall()
    if not rows:
        return None

    if expected_year is None:
        best = rows[0]
    else:
        def year_distance(row):
            y = row[3]
            return abs(y - expected_year) if y is not None else 9999

        best = min(rows, key=year_distance)
        if year_distance(best) > year_tolerance:
            return None

    tconst, primary_title, title_type, start_year, genres_raw = best
    genres = genres_raw.split(",") if genres_raw else []
    return GroundedTitle(tconst, primary_title, title_type, start_year, genres)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build", action="store_true", help="Download (if needed) and (re)build the index."
    )
    parser.add_argument(
        "--force", action="store_true", help="Rebuild the index from the already-downloaded TSV."
    )
    parser.add_argument(
        "--force-download", action="store_true", help="Also re-download the raw TSV from IMDb."
    )
    args = parser.parse_args()

    if not args.build:
        parser.print_help()
        sys.exit(1)

    build_index(force=args.force or args.force_download, force_download=args.force_download)


if __name__ == "__main__":
    main()
