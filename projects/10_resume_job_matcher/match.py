"""Compare a parsed resume against a parsed job listing.

Slice 2 of Project 10. Same split as Project 14's `score_fit.py`:

- The LLM does ONE job: evidence-detection. Given the resume text and the
  job's skill list, which skills are actually backed up by something on the
  resume, and what's the quote? It has no tools, so it can't invent evidence
  beyond the text it's handed.
- Everything deterministic -- which skills came back met, the years-of-
  experience comparison, assembling the result -- is plain Python here, and the
  scoring arithmetic is plain Python in `score.py`.

`match_requirements()` returns a "comparison" dict that `score.py` turns into
a number. Keeping the two steps separate means the scoring rubric is unit-
testable with zero mocking.
"""

from llm_client import extract_json


def build_resume_text(resume):
    """Flattens a parsed-resume dict (see parse_resume.RESUME_SCHEMA) into one
    plain-text block for the evidence-detection prompt."""
    lines = []
    if resume["name"]:
        lines.append(resume["name"])
    if resume["summary"]:
        lines.append(resume["summary"])
    if resume["skills"]:
        lines.append("")
        lines.append("Skills: " + ", ".join(resume["skills"]))
    if resume["experience"]:
        lines.append("")
        lines.append("Experience:")
        for role in resume["experience"]:
            header = f"{role['title']} — {role['organization']}"
            if role["dates"]:
                header += f" ({role['dates']})"
            lines.append(header)
            for highlight in role["highlights"]:
                lines.append(f"- {highlight}")
    if resume["education"]:
        lines.append("")
        lines.append("Education:")
        for entry in resume["education"]:
            lines.append(
                f"{entry['credential']}, {entry['institution']} ({entry['year']})"
            )
    if resume["certifications"]:
        lines.append("")
        lines.append(
            "Certifications: "
            + ", ".join(cert["name"] for cert in resume["certifications"])
        )
    return "\n".join(lines)


def _evidence_schema(known_skills):
    """`skill` is enum-constrained to the job's actual skill list, so Claude
    physically cannot return a skill that wasn't asked about (same trick as
    score_fit.py)."""
    return {
        "type": "object",
        "properties": {
            "skill_matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "skill": {"type": "string", "enum": known_skills},
                        "evidence": {
                            "type": "string",
                            "description": "Short quote from the résumé that supports this skill.",
                        },
                    },
                    "required": ["skill", "evidence"],
                    "additionalProperties": False,
                },
            },
            "education_met": {
                "type": "boolean",
                "description": (
                    "True if the résumé's education or experience plausibly "
                    "satisfies the stated requirement, including "
                    "'or equivalent experience' style wording."
                ),
            },
            "education_note": {
                "type": "string",
                "description": "One sentence explaining the education_met call.",
            },
        },
        "required": ["skill_matches", "education_met", "education_note"],
        "additionalProperties": False,
    }


_PROMPT = """\
Résumé:

{resume_text}

---

Skills / technologies to check for:
{skills_list}

For every skill in that list that has actual supporting evidence in the résumé
above, return the skill with a short quote from the résumé showing it. Do not
include a skill just because it seems plausible for this person's background —
if the résumé doesn't demonstrate it, leave it out.

Education requirement for the role: {education_requirement}

Judge whether the résumé satisfies that requirement (treat an empty requirement
as automatically satisfied) and explain your call in one sentence.
"""


def detect_skill_evidence(resume_text, skills, education_requirement):
    """One schema-constrained Claude call. Returns
    {skill_matches: [{skill, evidence}], education_met: bool, education_note: str}.
    Only skills with evidence come back -- absence means "not demonstrated"."""
    prompt = _PROMPT.format(
        resume_text=resume_text,
        skills_list="\n".join(f"- {s}" for s in skills),
        education_requirement=education_requirement or "(none stated)",
    )
    return extract_json(prompt, _evidence_schema(skills))


def _skill_rows(skills, evidence_by_skill):
    return [
        {
            "skill": skill,
            "met": skill in evidence_by_skill,
            "evidence": evidence_by_skill.get(skill, ""),
        }
        for skill in skills
    ]


def match_requirements(resume, job):
    """Builds the full comparison dict `score.py` consumes.

    Shape:
      {
        "required_skills":  [{skill, met, evidence}, ...],
        "preferred_skills": [{skill, met, evidence}, ...],
        "years":     {"required": int, "candidate": number, "met": bool},
        "education": {"requirement": str, "met": bool, "note": str},
      }
    """
    all_skills = job["required_skills"] + job["preferred_skills"]

    if all_skills:
        detected = detect_skill_evidence(
            build_resume_text(resume), all_skills, job["education_requirement"]
        )
    else:
        # Degenerate listing with no named skills -- nothing for the LLM to
        # detect. Treat education as satisfied and skip the call.
        detected = {
            "skill_matches": [],
            "education_met": True,
            "education_note": "Not evaluated (job listing named no skills).",
        }

    evidence_by_skill = {m["skill"]: m["evidence"] for m in detected["skill_matches"]}

    required_years = job["min_years_experience"]
    candidate_years = resume["total_years_experience"]

    has_requirement = bool(job["education_requirement"])
    return {
        "required_skills": _skill_rows(job["required_skills"], evidence_by_skill),
        "preferred_skills": _skill_rows(job["preferred_skills"], evidence_by_skill),
        "years": {
            "required": required_years,
            "candidate": candidate_years,
            "met": candidate_years >= required_years,
        },
        "education": {
            "requirement": job["education_requirement"],
            "met": detected["education_met"] if has_requirement else True,
            "note": (
                detected["education_note"]
                if has_requirement
                else "No education requirement stated."
            ),
        },
    }
