"""Turn a resume-vs-job comparison into a readable report: score, the gap
list, and honest suggestions for closing the gaps.

Slice 3 of Project 10. Same split as the rest of the project:

- `find_gaps()` is pure filtering over the comparison dict -- which required
  skills came back unmet, is the candidate short on years, is education unmet.
  No judgment, no LLM.
- `suggest_improvements()` is the one LLM call. It gets the gap list plus the
  full résumé and returns one piece of advice per gap, each classified as
  "surface it better" / "adjacent experience" / "genuine gap". The prompt
  forbids suggesting the candidate claim anything the résumé doesn't support --
  the point is a stronger honest résumé, not a padded one.
- `format_report()` renders the whole thing to text and is pure/testable.
"""

from match import build_resume_text
from llm_client import extract_json
from score import score_comparison

_GENUINE_GAP = "genuine_gap"
_SURFACE_BETTER = "surface_it_better"
_ADJACENT = "adjacent_experience"


def find_gaps(comparison):
    """Pure. Extracts the shortfalls from a match.match_requirements() dict."""
    years = comparison["years"]
    return {
        "unmet_required_skills": [
            row["skill"] for row in comparison["required_skills"] if not row["met"]
        ],
        "unmet_preferred_skills": [
            row["skill"] for row in comparison["preferred_skills"] if not row["met"]
        ],
        "years_short": (
            None
            if years["met"]
            else {"required": years["required"], "candidate": years["candidate"]}
        ),
        "education_unmet": not comparison["education"]["met"],
    }


def gap_labels(gaps):
    """The flat list of gap names, used both as the LLM's enum constraint and
    to decide whether there's anything to report at all."""
    labels = list(gaps["unmet_required_skills"]) + list(gaps["unmet_preferred_skills"])
    if gaps["years_short"]:
        labels.append("years of experience")
    if gaps["education_unmet"]:
        labels.append("education")
    return labels


def _suggestion_schema(labels):
    return {
        "type": "object",
        "properties": {
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "gap": {"type": "string", "enum": labels},
                        "assessment": {
                            "type": "string",
                            "enum": [_SURFACE_BETTER, _ADJACENT, _GENUINE_GAP],
                        },
                        "suggestion": {"type": "string"},
                    },
                    "required": ["gap", "assessment", "suggestion"],
                    "additionalProperties": False,
                },
            },
            "overall": {
                "type": "string",
                "description": "One or two sentences on how close this candidate is to the role.",
            },
        },
        "required": ["suggestions", "overall"],
        "additionalProperties": False,
    }


_PROMPT = """\
A candidate is applying for this role: {job_title}

Gaps found — requirements NOT evidenced in their résumé:
{gap_lines}

Their résumé:

{resume_text}

Give exactly one piece of advice per gap listed above. Classify each:
- "{surface}": the résumé shows related work but never makes the skill
  explicit — say which bullet or phrasing would fix that.
- "{adjacent}": they have closely related experience a reviewer might accept —
  say how to frame the connection.
- "{genuine}": nothing in the résumé supports this — say so plainly, and
  suggest how they'd actually close it (a project, a course). Do NOT tell them
  to claim it.

Never suggest adding a skill or experience the résumé gives no basis for.
Finish with a one- or two-sentence overall read.
"""


def suggest_improvements(resume, job, gaps):
    """One schema-constrained Claude call. Returns
    {suggestions: [{gap, assessment, suggestion}], overall: str}."""
    labels = gap_labels(gaps)
    prompt = _PROMPT.format(
        job_title=job["title"],
        gap_lines="\n".join(f"- {label}" for label in labels),
        resume_text=build_resume_text(resume),
        surface=_SURFACE_BETTER,
        adjacent=_ADJACENT,
        genuine=_GENUINE_GAP,
    )
    return extract_json(prompt, _suggestion_schema(labels))


def build_report(comparison, resume, job):
    """The single entry point: comparison + parsed résumé + parsed job -> a
    full report dict (score, band, breakdown, gaps, suggestions, overall)."""
    scored = score_comparison(comparison)
    gaps = find_gaps(comparison)

    if gap_labels(gaps):
        advice = suggest_improvements(resume, job, gaps)
    else:
        advice = {
            "suggestions": [],
            "overall": "No unmet requirements — the résumé already evidences the role.",
        }

    return {
        "job_title": job["title"],
        "company": job["company"],
        "score": scored["score"],
        "band": scored["band"],
        "breakdown": scored["breakdown"],
        "gaps": gaps,
        "suggestions": advice["suggestions"],
        "overall": advice["overall"],
    }


def format_report(report):
    """Pure. Renders a report dict to a plain-text block for a human."""
    heading = report["job_title"]
    if report.get("company"):
        heading += f" @ {report['company']}"
    lines = [
        f"{heading} — {report['score']}/100 ({report['band']})",
        "",
        "Score breakdown:",
    ]
    for component in report["breakdown"]:
        lines.append(
            f"  {component['component']:<22} "
            f"{component['points']:>5} / {component['max_points']:<3}  "
            f"{component['detail']}"
        )

    gaps = report["gaps"]
    lines.append("")
    lines.append("Gaps:")
    if gaps["unmet_required_skills"]:
        lines.append(
            "  Required, not shown:  " + ", ".join(gaps["unmet_required_skills"])
        )
    if gaps["unmet_preferred_skills"]:
        lines.append(
            "  Preferred, not shown: " + ", ".join(gaps["unmet_preferred_skills"])
        )
    if gaps["years_short"]:
        lines.append(
            f"  Years: {gaps['years_short']['candidate']} vs "
            f"{gaps['years_short']['required']} required"
        )
    if gaps["education_unmet"]:
        lines.append("  Education requirement not met")
    if not gap_labels(gaps):
        lines.append("  (none)")

    if report["suggestions"]:
        lines.append("")
        lines.append("Suggestions:")
        for item in report["suggestions"]:
            lines.append(f"  [{item['assessment']}] {item['gap']}")
            lines.append(f"    {item['suggestion']}")

    lines.append("")
    lines.append(f"Overall: {report['overall']}")
    return "\n".join(lines)
