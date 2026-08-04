"""One-off script: runs every exhibitor from a real trade-show PDF through
the full pipeline (search/profile-lookup -> score -> locate -> route) and
writes a CSV of results plus a plain-text summary.

Not part of the test suite or the reusable library -- a driver script for
a real end-to-end run against real data (data/ is gitignored, so the
input PDF and all outputs here stay local).
"""

import csv
import sys
import time

from extract_exhibitors import extract_company_names
from extract_exhibitor_profiles import build_profile_lookup, extract_exhibitor_profiles
from pipeline import evaluate_lead

PDF_PATH = "data/26_MDEX_Program_DIGITAL_5-7-26.pdf"
CLIENT_PROFILE_PATH = "data/sample_client_profile.yaml"
TERRITORY_ROUTING_PATH = "data/sample_territory_routing.csv"
OUTPUT_CSV = "data/full_real_exhibitor_run.csv"
OUTPUT_SUMMARY = "data/full_real_exhibitor_run_summary.txt"

FIELDNAMES = [
    "company_name",
    "score",
    "band",
    "fit_reason",
    "state",
    "country",
    "salesperson_name",
    "territory",
    "source",
]


def main():
    names = extract_company_names(PDF_PATH)
    lookup = build_profile_lookup(extract_exhibitor_profiles(PDF_PATH))
    print(f"Loaded {len(names)} exhibitor names, {len(lookup)} with real PDF profiles.")

    results = []
    failures = []
    start = time.time()

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()

        for i, name in enumerate(names, start=1):
            try:
                lead = evaluate_lead(
                    name, CLIENT_PROFILE_PATH, TERRITORY_ROUTING_PATH, exhibitor_profiles=lookup
                )
                location = lead.get("location") or {}
                row = {
                    "company_name": lead["company_name"],
                    "score": lead["score"],
                    "band": lead["band"],
                    "fit_reason": lead["fit_reason"],
                    "state": location.get("state") or "",
                    "country": location.get("country") or "",
                    "salesperson_name": lead["salesperson_name"],
                    "territory": lead["territory"] or "",
                    "source": lead["source"],
                }
                writer.writerow(row)
                f.flush()
                results.append(row)
            except Exception as exc:
                failures.append((name, str(exc)))
                print(f"[{i}/{len(names)}] FAILED: {name} -- {exc}", file=sys.stderr)
                continue

            elapsed = time.time() - start
            print(f"[{i}/{len(names)}] {name} -> {row['score']}/{row['band']} ({elapsed:.0f}s elapsed)")

    high = [r for r in results if r["band"] == "High"]
    medium = [r for r in results if r["band"] == "Medium"]
    low = [r for r in results if r["band"] == "Low"]
    unknown = [r for r in results if r["band"] == "Unknown"]

    with open(OUTPUT_SUMMARY, "w") as f:
        f.write(f"Total exhibitors processed: {len(results)} (of {len(names)}, {len(failures)} failed)\n")
        f.write(f"High: {len(high)}  Medium: {len(medium)}  Low: {len(low)}  Unknown: {len(unknown)}\n\n")

        f.write("=== HIGH fit ===\n")
        for r in sorted(high, key=lambda r: -r["score"]):
            f.write(f"{r['score']:>3} {r['company_name']} -- {r['fit_reason']}\n")

        f.write("\n=== MEDIUM fit ===\n")
        for r in sorted(medium, key=lambda r: -r["score"]):
            f.write(f"{r['score']:>3} {r['company_name']} -- {r['fit_reason']}\n")

        if failures:
            f.write("\n=== FAILURES ===\n")
            for name, err in failures:
                f.write(f"{name}: {err}\n")

    print(f"\nDone in {time.time() - start:.0f}s. Wrote {OUTPUT_CSV} and {OUTPUT_SUMMARY}.")
    print(f"High: {len(high)}  Medium: {len(medium)}  Low: {len(low)}  Unknown: {len(unknown)}  Failed: {len(failures)}")


if __name__ == "__main__":
    main()
