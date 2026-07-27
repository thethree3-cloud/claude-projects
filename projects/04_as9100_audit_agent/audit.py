import csv
import os
from pathlib import Path

import fitz  # PyMuPDF
from anthropic import Anthropic
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
CRITERIA_CSV = BASE_DIR / "data" / "criteria.csv"
WI_DIR = BASE_DIR / "data" / "work_instructions"
REPORT_CSV = BASE_DIR / "data" / "gap_analysis_report.csv"
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
MODEL = "claude-haiku-4-5-20251001"
VALID_STATUSES = {"Met", "Partial", "Gap"}

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


def load_criteria():
    with CRITERIA_CSV.open(newline="") as f:
        return list(csv.DictReader(f))


def load_work_instructions():
    documents = []
    for pdf_path in sorted(WI_DIR.glob("*.pdf")):
        doc = fitz.open(pdf_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        documents.append({"filename": pdf_path.name, "text": text})
    return documents


def build_corpus(documents):
    return "\n\n".join(f"=== {d['filename']} ===\n{d['text']}" for d in documents)


def parse_verdict(raw_text):
    lines = [line.strip() for line in raw_text.strip().splitlines() if line.strip()]
    status, source, rationale = "Gap", "", ""
    for line in lines:
        if line.startswith("STATUS:"):
            candidate = line.split(":", 1)[1].strip()
            status = candidate if candidate in VALID_STATUSES else "Gap"
        elif line.startswith("SOURCE:"):
            source = line.split(":", 1)[1].strip()
        elif line.startswith("RATIONALE:"):
            rationale = line.split(":", 1)[1].strip()
    return status, source, rationale


def evaluate_clause(clause, corpus):
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=300,
        temperature=0.0,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are auditing a company's internal work-instruction documents "
                    "against a single quality-audit criterion. Here are the internal "
                    f"documents:\n\n{corpus}\n\n"
                    f"Criterion {clause['id']} -- {clause['title']}: {clause['requirement']}\n\n"
                    "Judge only from the text above. Reply in exactly this format:\n"
                    "STATUS: <Met, Partial, or Gap>\n"
                    "SOURCE: <filename(s) that support this, or NONE>\n"
                    "RATIONALE: <one sentence>\n\n"
                    "Use Met if the documents fully address the criterion, Partial if "
                    "they address it incompletely, and Gap if nothing in the documents "
                    "addresses it."
                ),
            }
        ],
    )
    return parse_verdict(response.content[0].text)


def run_audit():
    criteria = load_criteria()
    documents = load_work_instructions()
    corpus = build_corpus(documents)

    results = []
    for clause in criteria:
        status, source, rationale = evaluate_clause(clause, corpus)
        results.append({**clause, "status": status, "source": source, "rationale": rationale})
        print(f"[{status:7}] {clause['id']} -- {clause['title']}")
        print(f"          {rationale}")
        if source:
            print(f"          Source: {source}")

    with REPORT_CSV.open("w", newline="") as f:
        fieldnames = ["id", "title", "requirement", "status", "source", "rationale"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    counts = {status: sum(1 for r in results if r["status"] == status) for status in VALID_STATUSES}
    print(f"\nSummary: {counts['Met']} Met, {counts['Partial']} Partial, {counts['Gap']} Gap")
    print(f"Full report written to {REPORT_CSV}")


if __name__ == "__main__":
    run_audit()
