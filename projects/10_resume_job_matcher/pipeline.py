"""The one call that runs the whole project.

Slice 4 of Project 10. `evaluate_fit()` takes raw résumé text and raw
job-listing text and returns a finished report:

    parse_resume ─┐
                  ├─> match_requirements ─> build_report ─> {score, band,
    parse_job   ──┘                                          breakdown, gaps,
                                                             suggestions, ...}

Four Claude calls at most (résumé parse, job parse, skill evidence-detection,
improvement suggestions) — three when the job has no gaps. `rank_fits()` is
pure and just orders a batch of reports best-first, for the folder driver
(`run_job_folder.py`).
"""

from match import match_requirements
from parse_job import parse_job
from parse_resume import parse_resume
from report import build_report
from tailor_resume import build_tailored_resume


def evaluate_fit(resume_text, job_text):
    """Raw résumé text + raw job-listing text -> a full report dict."""
    resume = parse_resume(resume_text)
    job = parse_job(job_text)
    comparison = match_requirements(resume, job)
    return build_report(comparison, resume, job)


def tailor_fit(resume_text, job_text, verify=True):
    """Raw résumé text + raw job-listing text -> a résumé reframed for that
    role: {"resume", "markdown", "changes", "flags", "diff"}. Five Claude
    calls (résumé parse, job parse, skill evidence-detection, the reframe, and
    the bullet-verification pass — four when `verify` is False)."""
    resume = parse_resume(resume_text)
    job = parse_job(job_text)
    comparison = match_requirements(resume, job)
    return build_tailored_resume(comparison, resume, job, verify=verify)


def rank_fits(reports):
    """Order report dicts by score, highest first. Stable, so reports that
    tie keep their input order. Pure."""
    return sorted(reports, key=lambda report: report["score"], reverse=True)
