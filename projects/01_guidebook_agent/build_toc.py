import csv
import re
from pathlib import Path

import fitz  # PyMuPDF

BASE_DIR = Path(__file__).resolve().parent
PDF_PATH = BASE_DIR / "data" / "las_vegas_employee_handbook.pdf"
OUTPUT_CSV = BASE_DIR / "data" / "table_of_contents.csv"
TOC_PAGE_INDEX = 3  # PDF page 4, confirmed via inspect_pdf.py

doc = fitz.open(PDF_PATH)
raw_text = doc[TOC_PAGE_INDEX].get_text().replace("\xa0", " ")
lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

# The ToC page prints "SUBJECT" then "PAGE NUMBER" as headers, then
# alternates: subject line, page-number line, subject line, ...
start = lines.index("PAGE NUMBER") + 1

entries = []
subject = None
for line in lines[start:]:
    if re.fullmatch(r"\d+", line):
        entries.append((subject, int(line)))
        subject = None
    else:
        subject = line

with OUTPUT_CSV.open("w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["subject", "start_page"])
    writer.writerows(entries)

print(f"Extracted {len(entries)} entries to {OUTPUT_CSV}")
for subject, page in entries:
    print(f"  {subject} -> page {page}")
