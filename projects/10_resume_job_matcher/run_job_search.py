"""Search live job postings and rank them against a résumé.

Driver script — not part of the test suite. Reads the résumé from the path you
pass, searches the boards in job_sites.py for matches near a location, scores
each posting with the full pipeline, and prints them best-fit first.

    python run_job_search.py data/sample_resume.txt "junior AI engineer"
    python run_job_search.py data/my_resume.txt "data analyst" "Austin, TX" --radius 40 --count 15
    python run_job_search.py data/my_resume.txt "python developer" --preset "Salt Lake City"

Omit the location to use the one parsed from the résumé. `--preset` adds a
region's local boards (see job_sites.LOCAL_PRESETS) and its default
location + radius.
"""

import argparse
import sys
from pathlib import Path

import job_sites
from job_search import search_jobs
from match import match_requirements
from parse_job import parse_job
from parse_resume import parse_resume
from pipeline import rank_fits
from report import build_report, format_report


def _job_text(job):
    """A search result -> the text parse_job expects: a title/company/location
    header (the description alone has neither), then the body."""
    return (
        f"{job['title']}\n{job['company']}\n{job['location']}\n\n{job['description']}"
    )


def main(resume_path, keywords, location, radius, count, preset):
    resume_text = Path(resume_path).read_text()
    # Parse the résumé once — it's the same for every posting.
    resume = parse_resume(resume_text)

    sites = None
    if preset:
        config = job_sites.LOCAL_PRESETS[preset]
        sites = job_sites.preset_sites(preset)
        location = location or config["location"]
        radius = radius if radius is not None else config["radius_miles"]
        print(f"{preset} preset: +{len(config['extra_sites'])} local boards")

    radius = radius if radius is not None else 25
    count = count if count is not None else 10

    if not location:
        location = resume["location"]
        if not location:
            print(
                "No location given and none on the résumé. Pass one explicitly.",
                file=sys.stderr,
            )
            return 1
        print(f"Using résumé location: {location}")

    print(f'Searching for "{keywords}" near {location} (within {radius} mi)…')
    jobs = search_jobs(keywords, location, radius_miles=radius, count=count, sites=sites)
    if not jobs:
        print("No postings found.", file=sys.stderr)
        return 1
    print(f"Found {len(jobs)}. Scoring against {Path(resume_path).name}…\n")

    reports = []
    for job in jobs:
        parsed_job = parse_job(_job_text(job))
        # The search result already knows the title/company/location for real;
        # trust those over whatever parse_job inferred from the body text.
        parsed_job["title"] = job["title"] or parsed_job["title"]
        parsed_job["company"] = job["company"] or parsed_job["company"]
        comparison = match_requirements(resume, parsed_job)
        report = build_report(comparison, resume, parsed_job)
        report["_url"] = job["url"]
        report["_grounding"] = job["grounding"]
        reports.append(report)
        print(
            f"  {report['score']:>3}/100 {report['band']:<9} "
            f"{report['job_title']} @ {report['company']}  ({job['grounding']})"
        )

    print("\n" + "=" * 72)
    for report in rank_fits(reports):
        print(f"\n{report['_url']}  [{report['_grounding']}]")
        print(format_report(report))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resume", help="path to the résumé text file")
    parser.add_argument("keywords", help="role / keywords to search for")
    parser.add_argument(
        "location", nargs="?", default="", help="city/state (default: from the résumé)"
    )
    parser.add_argument("--radius", type=int, default=None, help="search radius in miles")
    parser.add_argument("--count", type=int, default=None, help="max postings to score")
    parser.add_argument(
        "--preset",
        choices=list(job_sites.LOCAL_PRESETS),
        help="add a region's local boards + default location/radius",
    )
    args = parser.parse_args()
    sys.exit(
        main(
            args.resume,
            args.keywords,
            args.location,
            args.radius,
            args.count,
            args.preset,
        )
    )
