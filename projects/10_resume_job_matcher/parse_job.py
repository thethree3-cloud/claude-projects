"""Job-listing text -> structured job data.

Slice 1 of Project 10. Parsing only -- see README for the deferred slices.

The one real judgment call this module asks Claude to make: splitting
requirements into *required* vs. *preferred*. A later scoring slice weights
those two buckets differently, so getting the split right here matters.
"""

from llm_client import extract_json

JOB_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "company": {
            "type": "string",
            "description": "Hiring company, or empty string if not stated.",
        },
        "required_skills": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Skills/technologies the listing frames as mandatory -- phrased "
                "with 'required', 'must have', 'X+ years of', or listed under a "
                "Requirements/Qualifications heading with no softening language."
            ),
        },
        "preferred_skills": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Skills the listing frames as optional -- 'nice to have', "
                "'bonus', 'a plus', 'preferred', 'ideally'."
            ),
        },
        "min_years_experience": {
            "type": "number",
            "description": "Minimum years of experience explicitly required. 0 if not stated.",
        },
        "education_requirement": {
            "type": "string",
            "description": "Stated education requirement (e.g. \"Bachelor's in CS or equivalent\"). Empty string if none.",
        },
        "responsibilities": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Day-to-day responsibilities / what the role does.",
        },
    },
    "required": [
        "title",
        "company",
        "required_skills",
        "preferred_skills",
        "min_years_experience",
        "education_requirement",
        "responsibilities",
    ],
    "additionalProperties": False,
}

_PROMPT = """\
Extract structured data from the job listing below.

Rules:
- Only include skills and requirements actually named in the listing.
- Sort each named skill into required_skills OR preferred_skills based on how
  the listing frames it -- mandatory language vs. optional/"bonus" language.
  If it's genuinely ambiguous, treat it as required.
- Use 0 for min_years_experience and empty strings/lists where the listing
  says nothing.

Job listing:
---
{job_text}
---
"""


def parse_job(job_text):
    """Parses raw job-listing text into the JOB_SCHEMA shape. Returns a dict."""
    return extract_json(_PROMPT.format(job_text=job_text), JOB_SCHEMA)
