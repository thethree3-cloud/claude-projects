"""Writes a fictional sample resume and job listing into data/.

Everything here is invented -- fictional people, companies, and dates -- so the
project has something to run against without using anyone's real resume. A real
resume dropped into data/ is gitignored (see the repo .gitignore) and never
committed.

Run:  python sample_data.py
"""

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

SAMPLE_RESUME = """\
Jordan Rivera
Portland, OR | jordan.rivera@example.com | github.com/jrivera-example

PROFESSIONAL SUMMARY
IT support specialist moving into data and automation work. Five years keeping
a 300-person manufacturing office running, the last two spent replacing manual
reporting with scripted pipelines. Comfortable owning a small tool end to end:
gathering the requirement, building it in Python, and supporting it in production.

SKILLS
Python, SQL, pandas, Power Automate, Excel, Git, REST APIs, Windows Server,
Active Directory, PowerShell, ticket triage, technical documentation

EXPERIENCE

IT Support Analyst - Cascade Precision Manufacturing
Feb 2021 - Present
- Sole support contact for 300 staff across two plants; ~40 tickets/week.
- Built a Python + pandas pipeline that turned 6 monthly Excel exports into a
  single scheduled report, cutting a half-day manual task to zero.
- Wrote a PowerShell script to automate new-hire account provisioning across
  Active Directory and three SaaS tools.
- Maintained the internal IT knowledge base (60+ articles).

Help Desk Technician - Rose City Software
Jun 2019 - Feb 2021
- Tier 1/2 support for a 120-person SaaS company.
- Automated weekly license-usage reporting with a Google Apps Script.

EDUCATION
Associate of Applied Science, Network Administration
Portland Community College, 2019

CERTIFICATIONS
CompTIA A+ (2019), Microsoft Certified: Azure Fundamentals (2022)
"""

SAMPLE_JOB = """\
Junior AI Engineer
Northwind Analytics - Remote (US)

About the role
Northwind Analytics builds internal decision-support tools for mid-size
manufacturers. You'll join a three-person applied AI team building agents and
pipelines on top of large language models. This is a hands-on build role with
real production ownership.

What you'll do
- Build and ship LLM-backed features: retrieval, extraction, summarization.
- Turn messy business documents (PDFs, spreadsheets) into structured data.
- Write and maintain Python services and their test suites.
- Work directly with analysts to scope what to build.

Requirements
- 2+ years writing Python in a professional setting.
- Solid SQL and comfort working with relational data.
- Experience calling REST APIs and handling their failure modes.
- Able to write clear technical documentation.
- Bachelor's degree in a technical field or equivalent practical experience.

Nice to have
- Hands-on experience with the OpenAI or Anthropic APIs.
- Familiarity with the Model Context Protocol (MCP).
- Experience with pandas for data wrangling.
- Prior exposure to a manufacturing or industrial domain.

We do not require prior "machine learning" or model-training experience -- this
is an applied engineering role.
"""


def write_sample_data():
    DATA_DIR.mkdir(exist_ok=True)
    resume_path = DATA_DIR / "sample_resume.txt"
    job_path = DATA_DIR / "sample_job.txt"
    resume_path.write_text(SAMPLE_RESUME)
    job_path.write_text(SAMPLE_JOB)
    return resume_path, job_path


if __name__ == "__main__":
    for path in write_sample_data():
        print(f"wrote {path}")
