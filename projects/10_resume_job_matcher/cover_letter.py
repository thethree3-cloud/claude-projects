"""Parsed résumé + parsed job -> a grounded cover letter.

Same rule as the rest of Project 10: the letter may only say things the
résumé backs up. Two Claude calls, the `tailor_resume` pattern:

1. `write_cover_letter()` drafts the letter AND, alongside it, lists every
   substantive claim it makes about the candidate's background, each paired
   with the résumé phrase that supports it. The prompt is handed the
   comparison so it leans on skills that are actually evidenced and steers
   clear of the gaps.
2. `verify_claims()` audits that list against the résumé text — a claim whose
   support isn't really there comes back in `flags`.

Prose can't be surgically edited the way a résumé bullet can, so the letter
is **not** auto-rewritten: flagged claims are surfaced for the candidate to
fix or cut before sending. `render_text()` assembles the final letter and is
pure.
"""

import datetime

from llm_client import extract_json
from match import build_resume_text

_SCHEMA = {
    "type": "object",
    "properties": {
        "greeting": {
            "type": "string",
            "description": (
                "e.g. 'Dear Hiring Manager,'. Use the company name if the "
                "listing gives one; never invent a specific person's name."
            ),
        },
        "paragraphs": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "EXACTLY three strings, one per paragraph: (1) an opening "
                "naming the role and why the candidate is a real match, (2) a "
                "middle paragraph mapping specific résumé experience to what "
                "the job asks for, (3) a brief close. About 220 words total."
            ),
        },
        "signoff": {
            "type": "string",
            "description": "e.g. 'Sincerely,' — the candidate's name is added separately.",
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {
                        "type": "string",
                        "description": "A statement the letter makes about the candidate's background.",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "The phrase from the résumé that supports it.",
                    },
                },
                "required": ["claim", "evidence"],
                "additionalProperties": False,
            },
            "description": (
                "Every substantive claim the letter makes about the "
                "candidate's experience, each with its supporting résumé quote."
            ),
        },
    },
    "required": ["greeting", "paragraphs", "signoff", "claims"],
    "additionalProperties": False,
}

_PROMPT = """\
Write a cover letter for this application. It has to survive an interview —
every claim about the candidate's background must be something the résumé
actually shows.

TARGET ROLE: {job_title}{company}

What the job asks for:
- Required: {required_skills}
- Preferred: {preferred_skills}
- Responsibilities: {responsibilities}

SKILLS THE RÉSUMÉ DEMONSTRATES (cite these freely, drawing on the quote):
{evidence_lines}

SKILLS THE JOB WANTS BUT THE RÉSUMÉ DOES NOT DEMONSTRATE:
{gaps}
Never present these as things the candidate has. If the overall fit is a
stretch, it is fine — better — to name them plainly as areas to grow.

RÉSUMÉ:
{resume_text}

Rules:
- First person. EXACTLY three paragraphs, one string each in `paragraphs`,
  roughly 220 words total. Plain, direct, specific.
- Every concrete claim about the candidate's experience must trace to the
  résumé. Build the letter around the demonstrated skills above and specific
  things the candidate actually did — not a list of technologies.
- Do not round up or aggregate. If the résumé shows two years of a kind of
  work inside a longer role, the letter says two years, not five.
- Do not claim a skill from the "does not demonstrate" list, and do not imply
  it by lumping it into a phrase like "the stack you need".
- No clichés ("I am passionate", "team player", "hit the ground running", "I
  believe I would be a great fit"). No invented enthusiasm about or knowledge
  of the company beyond what the listing states.
- Address it to the company or "Hiring Manager" — never make up a name.
- In `claims`, list every substantive statement the letter makes about the
  candidate's background, each with the résumé phrase behind it.
"""


def _gap_list(comparison):
    unmet = [r["skill"] for r in comparison["required_skills"] if not r["met"]]
    unmet += [r["skill"] for r in comparison["preferred_skills"] if not r["met"]]
    return ", ".join(unmet) or "(none)"


def write_cover_letter(resume, job, comparison):
    """One schema-constrained Claude call. Returns
    {greeting, paragraphs: [str], signoff, claims: [{claim, evidence}]}."""
    evidence = [
        f'- {row["skill"]}: "{row["evidence"]}"'
        for row in comparison["required_skills"] + comparison["preferred_skills"]
        if row["met"] and row["evidence"]
    ]
    prompt = _PROMPT.format(
        job_title=job["title"] or "(untitled role)",
        company=f' at {job["company"]}' if job["company"] else "",
        required_skills=", ".join(job["required_skills"]) or "(none named)",
        preferred_skills=", ".join(job["preferred_skills"]) or "(none named)",
        responsibilities="; ".join(job["responsibilities"]) or "(none named)",
        evidence_lines="\n".join(evidence) or "(nothing matched yet)",
        gaps=_gap_list(comparison),
        resume_text=build_resume_text(resume),
    )
    return extract_json(prompt, _SCHEMA, max_tokens=1500)


def _verify_schema(claim_indices):
    return {
        "type": "object",
        "properties": {
            "unsupported": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_index": {"type": "integer", "enum": claim_indices},
                        "issue": {
                            "type": "string",
                            "description": "What the résumé does not actually support.",
                        },
                    },
                    "required": ["claim_index", "issue"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["unsupported"],
        "additionalProperties": False,
    }


_VERIFY_PROMPT = """\
Below is a candidate's résumé, then a numbered list of claims a cover letter
makes about that candidate.

A claim is FINE if the résumé supports it — including a skill or tool named
anywhere in the résumé, even if only in a skills list. The candidate is
entitled to reference their own résumé.

Flag a claim only if it goes beyond the résumé:
- a skill, tool, employer, or activity the résumé never mentions at all;
- an overstatement of scope, seniority, team size, impact, or duration
  (e.g. "five years doing X" when the résumé shows two);
- an outcome or achievement the résumé doesn't state.

RÉSUMÉ:
{resume_text}

CLAIMS:
{claims_block}

Return every claim that goes beyond the résumé.
"""


def verify_claims(letter, resume):
    """One schema-constrained Claude call auditing `letter["claims"]` against
    the résumé. Returns {"unsupported": [{claim_index, issue}, ...]}."""
    claims = letter["claims"]
    if not claims:
        return {"unsupported": []}
    claims_block = "\n".join(
        f'[{i}] {c["claim"]}  (cites: "{c["evidence"]}")' for i, c in enumerate(claims)
    )
    prompt = _VERIFY_PROMPT.format(
        resume_text=build_resume_text(resume), claims_block=claims_block
    )
    return extract_json(prompt, _verify_schema(list(range(len(claims)))))


def _flag_unsupported(letter, unsupported):
    """Pure. Turn verify_claims output into [{claim, issue}]."""
    claims = letter["claims"]
    flags = []
    for item in unsupported:
        idx = item["claim_index"]
        if 0 <= idx < len(claims):
            flags.append({"claim": claims[idx]["claim"], "issue": item["issue"]})
    return flags


def _contact_line(resume):
    return "  |  ".join(
        p
        for p in [
            resume["location"],
            resume["email"],
            resume["phone"],
            *resume["links"],
        ]
        if p
    )


def render_text(letter, resume, job, today=None):
    """Pure. Assemble the final letter as plain text."""
    today = today or datetime.date.today()
    lines = []
    if resume["name"]:
        lines.append(resume["name"])
    contact = _contact_line(resume)
    if contact:
        lines.append(contact)
    lines += ["", f"{today:%B} {today.day}, {today.year}", ""]
    lines.append(letter["greeting"])
    for para in letter["paragraphs"]:
        lines += ["", para]
    lines += ["", letter["signoff"], resume["name"] or ""]
    return "\n".join(lines).strip() + "\n"


def build_cover_letter(comparison, resume, job, verify=True):
    """The single entry point. comparison + parsed résumé + parsed job ->
    {"text", "paragraphs", "greeting", "claims", "flags"}.

    With `verify` (the default) a second Claude call audits the letter's
    claims; ones the résumé doesn't support come back in `flags` for the
    candidate to fix — the prose is not auto-edited.
    """
    letter = write_cover_letter(resume, job, comparison)
    flags = []
    if verify:
        unsupported = verify_claims(letter, resume)["unsupported"]
        flags = _flag_unsupported(letter, unsupported)
    return {
        "text": render_text(letter, resume, job),
        "paragraphs": letter["paragraphs"],
        "greeting": letter["greeting"],
        "claims": letter["claims"],
        "flags": flags,
    }
