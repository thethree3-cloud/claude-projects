import csv
import re
from pathlib import Path

import fitz  # PyMuPDF

BASE_DIR = Path(__file__).resolve().parent
PDF_PATH = BASE_DIR / "data" / "as9100_audit_checklist.pdf"
OUTPUT_CSV = BASE_DIR / "data" / "criteria.csv"

# Each clause is printed as "AC-x.y | Title | Requirement text", but long
# requirements wrap onto extra lines in the PDF -- those continuation lines
# don't match CLAUSE_START, so they get appended to the current clause.
CLAUSE_START = re.compile(r"^(AC-[\d.]+)\s*\|\s*([^|]+)\|\s*(.*)$")


def parse_clauses(lines):
    clauses = []
    current = None
    for line in lines:
        match = CLAUSE_START.match(line)
        if match:
            if current:
                clauses.append(current)
            clause_id, title, requirement = match.groups()
            current = {"id": clause_id.strip(), "title": title.strip(), "requirement": requirement.strip()}
        elif current:
            current["requirement"] += " " + line
    if current:
        clauses.append(current)
    return clauses


def main():
    doc = fitz.open(PDF_PATH)
    lines = [line.strip() for line in doc[0].get_text().splitlines() if line.strip()]
    doc.close()

    clauses = parse_clauses(lines)

    with OUTPUT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "title", "requirement"])
        writer.writeheader()
        writer.writerows(clauses)

    print(f"Extracted {len(clauses)} clauses to {OUTPUT_CSV}")
    for c in clauses:
        print(f"  {c['id']}: {c['title']}")


if __name__ == "__main__":
    main()
