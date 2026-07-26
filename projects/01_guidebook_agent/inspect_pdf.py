import sys
from pathlib import Path

import fitz  # PyMuPDF

DEFAULT_PDF = Path(__file__).resolve().parent / "data" / "las_vegas_employee_handbook.pdf"
PDF_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF

doc = fitz.open(PDF_PATH)
print(f"Page count: {doc.page_count}")

toc = doc.get_toc()
print(f"\nEmbedded outline entries: {len(toc)}")
for level, title, page in toc[:30]:
    print(f"{'  ' * (level - 1)}- {title} (page {page})")

print("\n--- Raw text of first 3 pages (checking for a printed ToC) ---")
for i in range(min(3, doc.page_count)):
    print(f"\n=== Page {i + 1} ===")
    print(doc[i].get_text()[:500])
