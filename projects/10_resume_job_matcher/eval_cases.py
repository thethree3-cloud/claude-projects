"""Fixture cases for the eval harness (`run_evals.py`).

Everything here is fictional, same spirit as `sample_data.py` — two of the job
listings are reused from there. Each case pairs an input with **tolerant**
expectations: score *ranges*, band *sets*, and directional properties, never an
exact score, because the runner hits a real model and the output moves a little
between runs. A failure means "a prompt or schema change shifted behaviour —
look at it", not "the build is broken".
"""

from dataclasses import dataclass

from sample_data import SAMPLE_JOB, SAMPLE_JOBS, SAMPLE_RESUME

DATA_ANALYST_JOB = SAMPLE_JOBS["02_data_analyst.txt"]
ML_SCIENTIST_JOB = SAMPLE_JOBS["03_ml_research_scientist.txt"]

# A deliberately partial fit: Jordan scripts (PowerShell, Python) and runs
# Windows infra, but has no containers / cloud / IaC / CI-CD.
PLATFORM_JOB = """\
Platform Engineer
Basalt Systems — Hybrid (Seattle, WA)

Own the delivery platform a 40-engineer product org ships on.

What you'll do
- Run our Kubernetes clusters and the services that support them.
- Build and maintain CI/CD pipelines.
- Manage cloud infrastructure as code.

Required qualifications (all of these are hard requirements):
- 3+ years in a platform, DevOps, or SRE role — required.
- Kubernetes: production operations experience — required.
- Docker: required.
- Terraform: required.
- AWS: required.
- CI/CD pipeline ownership for a multi-team codebase — required.

Nice to have
- Prometheus / Grafana observability experience.
- Exposure to a regulated industry.
"""


@dataclass
class FitCase:
    name: str
    resume: str
    job: str
    band_in: tuple  # acceptable bands
    score_range: tuple  # (min, max) inclusive
    max_unmet_required: int | None = None
    expect_genuine_gap: bool = False  # >=1 suggestion assessed "genuine_gap"


@dataclass
class TailorCase:
    name: str
    resume: str
    job: str
    # How many bullets the verification pass may drop before it's a smell that
    # the reframe prompt is drifting. Whatever the count, `run_evals` also
    # checks a flagged bullet never survives into the final résumé.
    max_flags: int = 2


@dataclass
class CoverLetterCase:
    name: str
    resume: str
    job: str
    max_flags: int = 1  # unsupported claims the verification pass may surface
    forbid_in_letter: tuple = ()  # cliché phrases that must not appear


FIT_CASES = [
    FitCase(
        "career-changer vs junior AI engineer",
        SAMPLE_RESUME,
        SAMPLE_JOB,
        band_in=("Strong",),
        score_range=(72, 100),
        max_unmet_required=1,
    ),
    FitCase(
        "career-changer vs data analyst",
        SAMPLE_RESUME,
        DATA_ANALYST_JOB,
        band_in=("Strong",),
        score_range=(72, 100),
        max_unmet_required=1,
    ),
    FitCase(
        "career-changer vs senior ML research scientist",
        SAMPLE_RESUME,
        ML_SCIENTIST_JOB,
        band_in=("Weak",),
        score_range=(0, 40),
        expect_genuine_gap=True,
    ),
    FitCase(
        "career-changer vs platform engineer (partial)",
        SAMPLE_RESUME,
        PLATFORM_JOB,
        band_in=("Possible", "Weak"),
        score_range=(10, 60),
        expect_genuine_gap=True,
    ),
]

TAILOR_CASES = [
    TailorCase("reframe for junior AI engineer", SAMPLE_RESUME, SAMPLE_JOB),
    TailorCase("reframe for data analyst", SAMPLE_RESUME, DATA_ANALYST_JOB),
]

_CLICHES = (
    "i am passionate",
    "team player",
    "hit the ground running",
    "i believe i would be a great fit",
)

COVER_LETTER_CASES = [
    CoverLetterCase(
        "cover letter for junior AI engineer",
        SAMPLE_RESUME,
        SAMPLE_JOB,
        forbid_in_letter=_CLICHES,
    ),
    CoverLetterCase(
        # the ML role is a genuine stretch, so the letter reaches a little and
        # the verification pass catches it — a couple of surfaced flags here is
        # the system working, not a regression
        "cover letter for senior ML research scientist",
        SAMPLE_RESUME,
        ML_SCIENTIST_JOB,
        max_flags=2,
        forbid_in_letter=_CLICHES,
    ),
]

VALID_BANDS = {"Strong", "Possible", "Weak"}
