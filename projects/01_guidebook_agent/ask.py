import csv
import os
import sys
from pathlib import Path

import fitz  # PyMuPDF
from anthropic import Anthropic
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PDF_PATH = BASE_DIR / "data" / "las_vegas_employee_handbook.pdf"
TOC_CSV = BASE_DIR / "data" / "table_of_contents.csv"
MODEL = "claude-haiku-4-5-20251001"

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH)
api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise RuntimeError(f"ANTHROPIC_API_KEY not found. Checked: {ENV_PATH}")

client = Anthropic(api_key=api_key)


def load_sections(doc_page_count):
    with TOC_CSV.open(newline="") as f:
        rows = list(csv.DictReader(f))

    sections = []
    for i, row in enumerate(rows):
        start = int(row["start_page"])
        end = int(rows[i + 1]["start_page"]) - 1 if i + 1 < len(rows) else doc_page_count
        end = max(start, end)
        sections.append({"subject": row["subject"], "start": start, "end": end})
    return sections


def route(question, sections):
    subject_list = "\n".join(s["subject"] for s in sections)
    response = client.messages.create(
        model=MODEL,
        max_tokens=50,
        temperature=0.0,
        messages=[
            {
                "role": "user",
                "content": (
                    "Here are the section subjects from an employee handbook's "
                    f"table of contents:\n\n{subject_list}\n\n"
                    f"Question: {question}\n\n"
                    "Reply with ONLY the single subject line that would contain the "
                    "answer, copied exactly as it appears above. If none of them "
                    "would help, reply with exactly: NONE"
                ),
            }
        ],
    )
    return response.content[0].text.strip()


def extract_pages(start_page, end_page):
    doc = fitz.open(PDF_PATH)
    text = "\n".join(doc[p - 1].get_text() for p in range(start_page, end_page + 1))
    doc.close()
    return text


def answer(question, section_text, subject):
    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        temperature=0.0,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Here is the '{subject}' section of an employee handbook:\n\n"
                    f"{section_text}\n\n"
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
    subject = route(question, sections)

    if subject == "NONE":
        print("No matching section found in the table of contents.")
        return

    matched = next((s for s in sections if s["subject"] == subject), None)
    if matched is None:
        print(f"Router returned an unrecognized subject: {subject!r}")
        return

    print(f"Routed to section: {matched['subject']} (pages {matched['start']}-{matched['end']})")
    section_text = extract_pages(matched["start"], matched["end"])
    print(f"\n{answer(question, section_text, matched['subject'])}")


if __name__ == "__main__":
    main()
