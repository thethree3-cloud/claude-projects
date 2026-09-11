"""Category pool curation: ask Claude to propose candidate movie/TV titles
for a themed category ("70s Cop Movies"), then verify each one against the
local IMDb grounding index (imdb_index.py) before it's eligible for a
puzzle. This is a batch/offline step, deliberately kept out of the timed
gameplay loop -- LLM latency variance would corrupt a speed leaderboard.
Claude's title text is treated as a claim to check, not a fact to trust.

Usage:
    python curate.py --theme "Cop Movies" --era-start 1970 --era-end 1979
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from imdb_index import INDEX_DB, lookup

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
MODEL = "claude-haiku-4-5-20251001"

CANDIDATE_PROMPT = """You are helping curate a movie/TV title-guessing game category.

Category: "{theme}"
Era: {era_start}-{era_end}

Propose {count} real, well-known movies or TV shows that clearly fit this
category and era. Favor titles a general audience would recognize -- this
is for a guessing game, obscure picks make for a bad puzzle. Do not repeat
titles.

Respond with ONLY a JSON array, no other text, in this exact shape:
[{{"title": "Dirty Harry", "year": 1971}}, {{"title": "The French Connection", "year": 1971}}]
"""

_client = None


def get_client():
    global _client
    if _client is None:
        load_dotenv(ENV_PATH)
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(f"ANTHROPIC_API_KEY not found. Checked: {ENV_PATH}")
        _client = Anthropic(api_key=api_key)
    return _client


def extract_json(raw_text):
    """Strip markdown code fencing if the model added it despite being told not to."""
    match = re.search(r"```(?:json)?\s*(.*?)```", raw_text, re.DOTALL)
    text = match.group(1) if match else raw_text
    return text.strip()


@dataclass
class CandidateMovie:
    """One proposed title after grounding. `grounded` is False when the
    local IMDb index could not verify it within year tolerance -- those
    should NOT enter a shipped category pool without a human looking at
    why (Claude hallucination vs. a real gap in the local index)."""

    proposed_title: str
    proposed_year: int | None
    grounded: bool
    rejection_reason: str | None = None
    imdb_id: str | None = None
    canonical_title: str | None = None
    year: int | None = None
    title_type: str | None = None
    genres: list[str] = field(default_factory=list)
    word_count: int | None = None

    def to_dict(self) -> dict:
        return {
            "proposed_title": self.proposed_title,
            "proposed_year": self.proposed_year,
            "grounded": self.grounded,
            "rejection_reason": self.rejection_reason,
            "imdb_id": self.imdb_id,
            "canonical_title": self.canonical_title,
            "year": self.year,
            "title_type": self.title_type,
            "genres": self.genres,
            "word_count": self.word_count,
        }


def propose_candidates(theme, era_start, era_end, count=20, client=None):
    """Ask Claude for candidate titles. Returns raw {title, year} dicts --
    unverified, must be passed through ground_candidates() before use."""
    client = client or get_client()
    prompt = CANDIDATE_PROMPT.format(theme=theme, era_start=era_start, era_end=era_end, count=count)
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        temperature=0.7,
        messages=[{"role": "user", "content": prompt}],
    )
    return json.loads(extract_json(response.content[0].text))


def ground_candidates(raw_candidates, conn, year_tolerance=2):
    """Verify each Claude-proposed title against the local IMDb index."""
    results = []
    for raw in raw_candidates:
        proposed_title = raw["title"]
        proposed_year = raw.get("year")
        grounded_title = lookup(
            conn, proposed_title, expected_year=proposed_year, year_tolerance=year_tolerance
        )
        if grounded_title is None:
            results.append(
                CandidateMovie(
                    proposed_title=proposed_title,
                    proposed_year=proposed_year,
                    grounded=False,
                    rejection_reason="not found in IMDb index within year tolerance",
                )
            )
            continue
        results.append(
            CandidateMovie(
                proposed_title=proposed_title,
                proposed_year=proposed_year,
                grounded=True,
                imdb_id=grounded_title.tconst,
                canonical_title=grounded_title.primary_title,
                year=grounded_title.start_year,
                title_type=grounded_title.title_type,
                genres=grounded_title.genres,
                word_count=len(grounded_title.primary_title.split()),
            )
        )
    return results


def generate_category_pool(theme, era_start, era_end, count=20, client=None, index_path=INDEX_DB):
    """End-to-end: propose candidates with Claude, ground them against the
    local IMDb index. Returns both grounded and rejected candidates so a
    human reviewer can see what was filtered out and why."""
    if not Path(index_path).exists():
        raise RuntimeError(
            f"No IMDb index at {index_path}. Run: python imdb_index.py --build"
        )
    raw = propose_candidates(theme, era_start, era_end, count=count, client=client)
    conn = sqlite3.connect(index_path)
    try:
        return ground_candidates(raw, conn)
    finally:
        conn.close()
