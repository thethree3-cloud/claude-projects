from pathlib import Path

import yaml


def load_client_profile(path):
    with Path(path).open() as f:
        return yaml.safe_load(f)


def flatten_signals(profile):
    """Flattens industries -> signals into a flat term/industry/weight list.

    This is the shape both the scoring prompt (which needs the full list of
    terms to check for) and compute_score (which needs to look up a
    matched term's weight) actually need -- the nested industry grouping in
    the YAML is for human authoring, not for scoring.
    """
    flat = []
    for industry in profile.get("industries", []):
        for signal in industry.get("signals", []):
            flat.append(
                {
                    "industry": industry["name"],
                    "term": signal["term"],
                    "weight": signal["weight"],
                }
            )
    return flat
