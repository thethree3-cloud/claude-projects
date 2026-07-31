import re

import fitz  # PyMuPDF

LINE_PATTERN = re.compile(r"^\d+\.\s*(.+)$")


def extract_company_names(pdf_path):
    """Pulls company names out of a numbered trade-show exhibitor list PDF.

    Unlike Project 01's handbook (which has a table-of-contents page mapping
    subjects to page ranges), an exhibitor list is just a flat numbered list,
    so this is a standalone line parse rather than a reuse of build_toc.py's
    state machine.
    """
    doc = fitz.open(pdf_path)
    text = "\n".join(page.get_text() for page in doc)
    doc.close()

    names = []
    for line in text.splitlines():
        match = LINE_PATTERN.match(line.strip())
        if match:
            names.append(match.group(1).strip())
    return names
