"""The curated list of job boards `job_search.py` searches.

Grouped by kind, with one flat `ALL_JOB_SITES` list passed to the web-search
tool's `allowed_domains`. `allowed_domains` matches subdomains too, so a bare
`myworkdayjobs.com` covers `acme.wd5.myworkdayjobs.com` etc.

Edit these lists freely — `job_search.search_jobs(..., sites=[...])` also takes
a per-call override.
"""

# General aggregators — the biggest coverage, but their posting pages fight
# automated fetches hard (bot protection). Good for *finding* a listing;
# expect to fall back to the search snippet for the actual text.
AGGREGATORS = [
    "indeed.com",
    "linkedin.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "monster.com",
    "simplyhired.com",
    "careerbuilder.com",
]

# Tech / startup boards.
TECH = [
    "dice.com",
    "builtin.com",
    "wellfound.com",
    "workatastartup.com",
    "otta.com",
]

# AI / ML niche boards.
AI_ML = [
    "ai-jobs.net",
    "aijobs.com",
]

# Remote-first boards.
REMOTE = [
    "weworkremotely.com",
    "remoteok.com",
    "remotive.com",
]

# US government + cleared/defense — relevant to compliance (AS9100 / CMMC /
# NIST 800-171) and manufacturing-quality roles.
GOVERNMENT = [
    "usajobs.gov",
    "clearancejobs.com",
    "governmentjobs.com",  # NeoGov — most US state / county / city career portals
]

# Applicant-tracking-system job pages. Fewer listings per domain, but these
# fetch reliably and carry the complete posting text — the best grounding.
ATS = [
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "apply.workable.com",
    "myworkdayjobs.com",
    "jobs.jobvite.com",
    "smartrecruiters.com",
    "bamboohr.com",
    "icims.com",
]

ALL_JOB_SITES = [*AGGREGATORS, *TECH, *AI_ML, *REMOTE, *GOVERNMENT, *ATS]

# The subset whose posting pages an automated fetch can usually read in full.
FETCHABLE = [*GOVERNMENT, *ATS]

# =============================================================================
# Local presets — extra region-specific boards to search on top of
# ALL_JOB_SITES, plus a default location + radius.
# =============================================================================

# Utah / Salt Lake City boards (verified 2026-08). `myworkdayjobs.com` (already
# in ATS) covers slcgov.wd1.myworkdayjobs.com and utah.wd1.myworkdayjobs.com;
# `governmentjobs.com` covers the State of Utah and Salt Lake County portals.
UTAH = [
    "jobs.utah.gov",            # Dept. of Workforce Services job-seeker board
    "statejobs.utah.gov",       # State of Utah careers / apply portal
    "careers-slco.icims.com",   # Salt Lake County
    "jobs.ksl.com",             # KSL Jobs
    "classifieds.ksl.com",      # KSL Classifieds (jobs consolidating here, 2026)
    "siliconslopes.com",        # Silicon Slopes tech job board
    "jobs.siliconslopes.com",
    "siliconslopesjobs.com",
    "utah.edu",                 # University of Utah (largest SLC-area employer)
]

LOCAL_PRESETS = {
    "Salt Lake City": {
        "location": "Salt Lake City, Utah",
        "radius_miles": 25,
        "extra_sites": UTAH,
    },
}


def preset_sites(preset_name):
    """ALL_JOB_SITES plus the named preset's region boards, order-preserving
    and de-duplicated."""
    extra = LOCAL_PRESETS[preset_name]["extra_sites"]
    return list(dict.fromkeys([*ALL_JOB_SITES, *extra]))
