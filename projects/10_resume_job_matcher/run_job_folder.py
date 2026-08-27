"""Run one résumé against every .txt job listing in a folder, ranked best-fit
first, with the full gap report for each.

Driver script -- not part of the test suite. Reads from paths you pass on the
command line; point it at `data/` (gitignored) to keep a real résumé and real
job listings local.

    python run_job_folder.py data/sample_resume.txt data/sample_jobs/
"""

import sys
from pathlib import Path

from pipeline import evaluate_fit, rank_fits
from report import format_report


def main(resume_path, jobs_dir):
    resume_text = Path(resume_path).read_text()
    job_files = sorted(Path(jobs_dir).glob("*.txt"))
    if not job_files:
        print(f"No .txt job listings found in {jobs_dir}", file=sys.stderr)
        return 1

    print(f"Scoring {len(job_files)} listings against {Path(resume_path).name}...\n")
    reports = []
    for job_file in job_files:
        report = evaluate_fit(resume_text, job_file.read_text())
        report["_file"] = job_file.name
        reports.append(report)
        print(f"  {report['score']:>3}/100 {report['band']:<9} {job_file.name}")

    print("\n" + "=" * 70)
    for report in rank_fits(reports):
        print(f"\n[{report['_file']}]")
        print(format_report(report))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            "usage: python run_job_folder.py <resume.txt> <jobs_dir>", file=sys.stderr
        )
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
