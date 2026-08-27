"""Turn a `match.match_requirements()` comparison dict into a fit score.

Pure arithmetic -- no LLM call, no I/O. Every number here is explainable
contribution-by-contribution (the `breakdown` list), the same principle as
Project 14's `score_fit.py`: a human reviewer should be able to see exactly
why a résumé scored what it did, not just trust a single opaque number.

Weights sum to 100:
    required skills   60   (the bulk of fit -- the "must haves")
    years experience  20   (all-or-nothing: meets the stated minimum or not)
    preferred skills  15   (bonus -- the "nice to haves")
    education          5    (all-or-nothing)
"""

WEIGHT_REQUIRED_SKILLS = 60
WEIGHT_YEARS = 20
WEIGHT_PREFERRED_SKILLS = 15
WEIGHT_EDUCATION = 5

STRONG_MIN = 75
POSSIBLE_MIN = 45


def _met_count(rows):
    return sum(1 for row in rows if row["met"])


def _met_ratio(rows):
    """Fraction of requirement rows that are met.

    An empty list scores 1.0 -- if the listing named no required skills (or no
    preferred skills), there's nothing to miss, so that component is full marks
    rather than a division by zero or an undeserved zero.
    """
    if not rows:
        return 1.0
    return _met_count(rows) / len(rows)


def band_for(score):
    if score >= STRONG_MIN:
        return "Strong"
    if score >= POSSIBLE_MIN:
        return "Possible"
    return "Weak"


def score_comparison(comparison):
    """comparison dict -> {score: int, band: str, breakdown: [...]}"""
    required = comparison["required_skills"]
    preferred = comparison["preferred_skills"]

    breakdown = [
        {
            "component": "Required skills",
            "points": round(WEIGHT_REQUIRED_SKILLS * _met_ratio(required), 1),
            "max_points": WEIGHT_REQUIRED_SKILLS,
            "detail": f"{_met_count(required)} of {len(required)} met",
        },
        {
            "component": "Years of experience",
            "points": WEIGHT_YEARS if comparison["years"]["met"] else 0,
            "max_points": WEIGHT_YEARS,
            "detail": (
                f"{comparison['years']['candidate']} yrs vs "
                f"{comparison['years']['required']} required"
            ),
        },
        {
            "component": "Preferred skills",
            "points": round(WEIGHT_PREFERRED_SKILLS * _met_ratio(preferred), 1),
            "max_points": WEIGHT_PREFERRED_SKILLS,
            "detail": f"{_met_count(preferred)} of {len(preferred)} met",
        },
        {
            "component": "Education",
            "points": WEIGHT_EDUCATION if comparison["education"]["met"] else 0,
            "max_points": WEIGHT_EDUCATION,
            "detail": comparison["education"]["note"],
        },
    ]

    score = round(sum(component["points"] for component in breakdown))
    return {"score": score, "band": band_for(score), "breakdown": breakdown}
