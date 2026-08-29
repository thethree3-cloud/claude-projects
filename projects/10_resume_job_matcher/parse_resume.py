"""Resume text -> structured resume data.

Slice 1 of Project 10. This module only *parses*; matching a resume against a
job listing and scoring the fit are later slices (see README).
"""

from llm_client import extract_json

RESUME_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "Candidate name as written, or empty string if absent.",
        },
        "summary": {
            "type": "string",
            "description": "The professional summary / objective, verbatim or lightly trimmed. Empty string if there isn't one.",
        },
        "location": {
            "type": "string",
            "description": "The candidate's location as written — city/state, or city/state/ZIP. Empty string if the résumé doesn't give one.",
        },
        "email": {
            "type": "string",
            "description": "Email address from the header, or empty string if absent.",
        },
        "phone": {
            "type": "string",
            "description": "Phone number as written, or empty string if absent.",
        },
        "links": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Profile / portfolio URLs (LinkedIn, GitHub, personal site), "
                "as written. Empty list if none."
            ),
        },
        "skills": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Skills, tools, and technologies explicitly named anywhere in the resume.",
        },
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "organization": {"type": "string"},
                    "dates": {
                        "type": "string",
                        "description": "Date range as written, e.g. 'Jan 2022 - Present'. Empty string if absent.",
                    },
                    "highlights": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Bullet points / accomplishments for this role, as written.",
                    },
                },
                "required": ["title", "organization", "dates", "highlights"],
                "additionalProperties": False,
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "credential": {"type": "string"},
                    "institution": {"type": "string"},
                    "year": {"type": "string"},
                },
                "required": ["credential", "institution", "year"],
                "additionalProperties": False,
            },
        },
        "certifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "issuer": {
                        "type": "string",
                        "description": "Issuing body, or empty string if not stated.",
                    },
                    "year": {
                        "type": "string",
                        "description": "Year earned as written, or empty string.",
                    },
                },
                "required": ["name", "issuer", "year"],
                "additionalProperties": False,
            },
            "description": "Professional certifications / licenses. Empty list if none.",
        },
        "total_years_experience": {
            "type": "number",
            "description": (
                "Best estimate of total years of professional experience, derived "
                "from the date ranges in the Experience section. Use 0 if the "
                "dates don't allow an estimate -- do not guess from seniority."
            ),
        },
    },
    "required": [
        "name",
        "summary",
        "location",
        "email",
        "phone",
        "links",
        "skills",
        "experience",
        "education",
        "certifications",
        "total_years_experience",
    ],
    "additionalProperties": False,
}

_PROMPT = """\
Extract structured data from the resume below.

Rules:
- Only include information that is actually present in the text. Do not infer
  skills, titles, or dates that aren't written down.
- For skills, list the specific tools/technologies/methods named -- not broad
  categories you assume from a job title.
- Pull contact details (email, phone, profile/portfolio links) from the header.
- List certifications and licenses with their issuer and year where the résumé
  gives them.
- If a field has no supporting content, use an empty string, an empty list, or
  0 as the schema requires.

Resume:
---
{resume_text}
---
"""


def parse_resume(resume_text):
    """Parses raw resume text into the RESUME_SCHEMA shape.

    Returns a plain dict. Extraction is grounded: the prompt tells Claude to
    pull only what's on the page, so a downstream matcher isn't scoring
    against skills the candidate never claimed.
    """
    return extract_json(_PROMPT.format(resume_text=resume_text), RESUME_SCHEMA)
