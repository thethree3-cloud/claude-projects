"""Parsed résumé + parsed job -> a résumé reframed for that specific role.

Slice 5 of Project 10. Same LLM/Python split, same grounding rule as every
other slice: the builder REFRAMES, it never fabricates. It may

- rewrite the professional summary to speak to this role,
- reorder skills and experience so the job-relevant material leads,
- re-word existing bullet points in the job's own vocabulary,
- drop an individual bullet that's pure noise for this application.

It may NOT invent a skill, employer, job title, date, metric, or
accomplishment that isn't already in the source résumé. The split enforces
that in two places:

- the schema: each tailored role points back to a real source role by index,
  and skills are enum-constrained to the résumé's own list;
- `assemble()` (pure Python): title/organization/dates are copied from the
  source role so the model can't drift them, any role the model dropped is
  re-appended untouched, any skill the model somehow returned that isn't in
  the résumé is filtered out, and contact details / certifications pass
  straight through (the model never sees them as editable).

The prompt carries the rest of the promise (don't invent accomplishments in
the bullet text).
"""

from llm_client import extract_json

_NO_SKILLS = "(résumé lists no skills)"


def _numbered_resume(resume):
    """Flatten a parsed résumé to text, numbering each role so the LLM can
    reference it by index in `source_index`."""
    lines = []
    if resume["name"]:
        lines.append(resume["name"])
    if resume["location"]:
        lines.append(resume["location"])
    contact = " | ".join(
        p for p in [resume["email"], resume["phone"], *resume["links"]] if p
    )
    if contact:
        lines.append(contact)
    if resume["summary"]:
        lines += ["", resume["summary"]]
    if resume["skills"]:
        lines += ["", "Skills: " + ", ".join(resume["skills"])]
    if resume["experience"]:
        lines += ["", "Experience:"]
        for i, role in enumerate(resume["experience"]):
            header = f"[{i}] {role['title']} — {role['organization']}"
            if role["dates"]:
                header += f" ({role['dates']})"
            lines.append(header)
            for highlight in role["highlights"]:
                lines.append(f"  - {highlight}")
    if resume["education"]:
        lines += ["", "Education:"]
        for entry in resume["education"]:
            lines.append(
                f"{entry['credential']}, {entry['institution']} ({entry['year']})"
            )
    if resume["certifications"]:
        lines += ["", "Certifications:"]
        for cert in resume["certifications"]:
            text = cert["name"]
            if cert["issuer"]:
                text += f" — {cert['issuer']}"
            if cert["year"]:
                text += f" ({cert['year']})"
            lines.append(text)
    return "\n".join(lines)


def _tailor_schema(resume):
    skill_enum = resume["skills"] or [_NO_SKILLS]
    index_enum = list(range(len(resume["experience"]))) or [0]
    return {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": (
                    "2–4 sentence professional summary rewritten to speak to "
                    "this role — using only facts already in the résumé."
                ),
            },
            "skills": {
                "type": "array",
                "items": {"type": "string", "enum": skill_enum},
                "description": (
                    "The résumé's own skills, reordered so the ones this job "
                    "asks for come first. Keep them all unless one is truly "
                    "irrelevant to this application."
                ),
            },
            "experience": {
                "type": "array",
                "description": (
                    "The résumé's roles, reordered most-relevant-first. Every "
                    "entry must reference a real source role by its number."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "source_index": {"type": "integer", "enum": index_enum},
                        "highlights": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "This role's existing bullets, re-worded toward "
                                "the job. Do not add an accomplishment that "
                                "wasn't in the original bullets."
                            ),
                        },
                    },
                    "required": ["source_index", "highlights"],
                    "additionalProperties": False,
                },
            },
            "changes": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Plain-language list of every change made, one per line, "
                    "so the candidate can audit it before sending."
                ),
            },
        },
        "required": ["summary", "skills", "experience", "changes"],
        "additionalProperties": False,
    }


_PROMPT = """\
Reframe the résumé below for one specific role. This is a real job application —
every word has to be something the candidate could defend in an interview.

TARGET ROLE: {job_title}{company}

What the job asks for:
- Required: {required_skills}
- Preferred: {preferred_skills}
- Responsibilities: {responsibilities}

Already evidenced in the résumé (skill -> the quote that proves it):
{evidence_lines}

SOURCE RÉSUMÉ — roles are numbered; reference them by number:
{resume_text}

Rules:
- REFRAME, don't invent. Rewrite the summary, reorder skills and roles so the
  job-relevant material leads, and re-word existing bullets in the job's
  vocabulary.
- Never add a skill, employer, title, date, metric, or accomplishment that
  isn't already in the source résumé. If the job wants something the résumé
  doesn't show, leave it out — the fit report already flags those gaps.
- Keep every role. You may drop an individual bullet that is irrelevant to
  this application, but never drop a whole job.
- Record each change you made in `changes`, one short line each.
"""


def tailor_resume(resume, job, comparison):
    """One schema-constrained Claude call. Returns the raw tailored dict:
    {summary, skills, experience: [{source_index, highlights}], changes}."""
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
        resume_text=_numbered_resume(resume),
    )
    return extract_json(prompt, _tailor_schema(resume), max_tokens=3000)


def assemble(tailored, resume):
    """Pure. Rebuild a full résumé dict from the LLM's tailored output, with
    the deterministic guarantees this project promises:

    - title / organization / dates come from the real source role, by index —
      the model only gets to reorder roles and re-word their bullets;
    - a role the model dropped entirely is re-appended, untouched, in its
      original position relative to the other dropped roles — no job is ever
      silently lost;
    - a "skill" that isn't in the source résumé is discarded.
    """
    seen = set()
    experience = []
    for entry in tailored["experience"]:
        idx = entry["source_index"]
        if idx in seen or not (0 <= idx < len(resume["experience"])):
            continue
        seen.add(idx)
        source = resume["experience"][idx]
        experience.append(
            {
                "title": source["title"],
                "organization": source["organization"],
                "dates": source["dates"],
                "highlights": entry["highlights"] or source["highlights"],
            }
        )
    for idx, source in enumerate(resume["experience"]):
        if idx not in seen:
            experience.append(dict(source))

    known = set(resume["skills"])
    skills = [s for s in tailored["skills"] if s in known]
    skills += [s for s in resume["skills"] if s not in skills]

    return {
        "name": resume["name"],
        "location": resume["location"],
        "email": resume["email"],
        "phone": resume["phone"],
        "links": resume["links"],
        "summary": tailored["summary"] or resume["summary"],
        "skills": skills,
        "experience": experience,
        "education": resume["education"],
        "certifications": resume["certifications"],
    }


def render_markdown(resume):
    """Pure. Render an assembled résumé dict to a Markdown document."""
    lines = []
    if resume["name"]:
        lines.append(f"# {resume['name']}")
    if resume["location"]:
        lines.append(resume["location"])
    contact = " · ".join(
        p for p in [resume["email"], resume["phone"], *resume["links"]] if p
    )
    if contact:
        lines.append(contact)
    lines.append("")
    if resume["summary"]:
        lines += ["## Summary", "", resume["summary"], ""]
    if resume["skills"]:
        lines += ["## Skills", "", ", ".join(resume["skills"]), ""]
    if resume["experience"]:
        lines += ["## Experience", ""]
        for role in resume["experience"]:
            lines.append(f"### {role['title']} — {role['organization']}")
            lines.append(f"*{role['dates']}*" if role["dates"] else "")
            lines.append("")
            lines += [f"- {h}" for h in role["highlights"]]
            lines.append("")
    if resume["education"]:
        lines += ["## Education", ""]
        for entry in resume["education"]:
            year = f" ({entry['year']})" if entry["year"] else ""
            lines.append(f"- {entry['credential']}, {entry['institution']}{year}")
        lines.append("")
    if resume["certifications"]:
        lines += ["## Certifications", ""]
        for cert in resume["certifications"]:
            extra = ", ".join(p for p in [cert["issuer"], cert["year"]] if p)
            lines.append(f"- {cert['name']}" + (f" ({extra})" if extra else ""))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_tailored_resume(comparison, resume, job):
    """The single entry point. comparison + parsed résumé + parsed job ->
    {"resume": <assembled dict>, "markdown": str, "changes": [str, ...]}."""
    tailored = tailor_resume(resume, job, comparison)
    assembled = assemble(tailored, resume)
    return {
        "resume": assembled,
        "markdown": render_markdown(assembled),
        "changes": tailored["changes"],
    }
