import csv
import difflib
import os
import sys
from pathlib import Path

import fitz  # PyMuPDF
from anthropic import Anthropic
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PDF_PATH = BASE_DIR / "data" / "las_vegas_employee_handbook.pdf"
TOC_CSV = BASE_DIR / "data" / "table_of_contents.csv"
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
MODEL = "claude-haiku-4-5-20251001"
FUZZY_MATCH_CUTOFF = 0.6

_client = None


def get_client():
    global _client
    if _client is None:
        load_dotenv(ENV_PATH)
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(f"ANTHROPIC_API_KEY not found. Checked: {ENV_PATH}")
        _client = Anthropic(api_key=api_key)
    return _client


def compute_ranges(rows, doc_page_count):
    sections = []
    for i, row in enumerate(rows):
        start = int(row["start_page"])
        end = int(rows[i + 1]["start_page"]) - 1 if i + 1 < len(rows) else doc_page_count
        end = max(start, end)
        sections.append({"subject": row["subject"], "start": start, "end": end})
    return sections


def load_sections(doc_page_count):
    with TOC_CSV.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return compute_ranges(rows, doc_page_count)


def parse_route_lines(raw_text, valid_subjects):
    lines = [line.strip() for line in raw_text.strip().splitlines() if line.strip()]
    if not lines or lines == ["NONE"]:
        return [], []

    matched, unmatched = [], []
    for line in lines:
        if line in valid_subjects:
            match = line
        else:
            close = difflib.get_close_matches(line, valid_subjects, n=1, cutoff=FUZZY_MATCH_CUTOFF)
            match = close[0] if close else None

        if match is None:
            unmatched.append(line)
        elif match not in matched:
            matched.append(match)

    return matched, unmatched


def route(question, sections):
    subject_list = "\n".join(s["subject"] for s in sections)
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=100,
        temperature=0.0,
        messages=[
            {
                "role": "user",
                "content": (
                    "Here are the section subjects from an employee handbook's "
                    f"table of contents:\n\n{subject_list}\n\n"
                    f"Question: {question}\n\n"
                    "Reply with the subject lines (up to 3, most relevant first) "
                    "that would contain the answer, copied exactly as they appear "
                    "above, one per line. If none of them would help, reply with "
                    "exactly: NONE"
                ),
            }
        ],
    )
    valid_subjects = [s["subject"] for s in sections]
    return parse_route_lines(response.content[0].text, valid_subjects)


def extract_pages(start_page, end_page):
    doc = fitz.open(PDF_PATH)
    text = "\n".join(doc[p - 1].get_text() for p in range(start_page, end_page + 1))
    doc.close()
    return text


def answer(question, sections_with_text):
    context = "\n\n".join(
        f"=== {s['subject']} ===\n{s['text']}" for s in sections_with_text
    )
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=500,
        temperature=0.0,
        messages=[
            {
                "role": "user",
                "content": (
                    "Here are section(s) of an employee handbook:\n\n"
                    f"{context}\n\n"
                    f"Question: {question}\n\n"
                    "Answer using only the text above. If the answer isn't in "
                    "this text, say so."
                ),
            }
        ],
    )
    return response.content[0].text.strip()


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {Path(__file__).name} \"<question>\"")
        sys.exit(1)
    question = " ".join(sys.argv[1:])

    doc = fitz.open(PDF_PATH)
    page_count = doc.page_count
    doc.close()

    sections = load_sections(page_count)
    subjects, unmatched = route(question, sections)

    if unmatched:
        print(f"(router suggested unmatched subjects, ignoring: {unmatched!r})")
    if not subjects:
        print("No matching section found in the table of contents.")
        return

    by_subject = {s["subject"]: s for s in sections}
    matched = [by_subject[subj] for subj in subjects]
    for s in matched:
        print(f"Routed to section: {s['subject']} (pages {s['start']}-{s['end']})")

    sections_with_text = [
        {**s, "text": extract_pages(s["start"], s["end"])} for s in matched
    ]
    print(f"\n{answer(question, sections_with_text)}")


if __name__ == "__main__":
    main()
