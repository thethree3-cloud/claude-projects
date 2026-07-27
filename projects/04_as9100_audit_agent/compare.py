import csv
import os
import sys
from pathlib import Path

import fitz  # PyMuPDF
from anthropic import Anthropic
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
REGISTRY_CSV = BASE_DIR / "data" / "document_registry.csv"
WI_DIR = BASE_DIR / "data" / "work_instructions"
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
MODEL = "claude-haiku-4-5-20251001"

MATCH_SYSTEM_PROMPT = """\
You match an uploaded reference document to the single best-fitting \
document in an internal document registry, using Doc_Number, Title, \
Department, Process, and Keywords.

Rules:
- Pick the single best match. If other entries are also plausible, list \
them as secondary matches.
- If the best match is only approximate (not a close fit), say so.
- Do not invent a document that isn't in the registry.
- If nothing in the registry is relevant, respond with NONE.

Respond in exactly this format:
BEST_MATCH: <Doc_Number or NONE>
SECONDARY_MATCHES: <comma-separated Doc_Numbers, or NONE>
CONFIDENCE: <exact, approximate, or none>
"""

COMPARISON_SYSTEM_PROMPT = """\
You are an internal AS9100 audit comparison and document review assistant. \
Your job is to compare an internal document against an uploaded reference \
document (customer, supplier, or internal revision) and identify gaps, \
differences, and improvement opportunities.

Do NOT certify compliance, provide audit signoff, or claim approval or \
certification of any kind. Your role is gap identification, comparison, \
and improvement support only.

Use cautious, structured, practical language such as: "possible gap", \
"appears missing", "may need review", "recommended improvement", "less \
detailed", "not clearly defined".

Avoid words like: "compliant", "noncompliant", "certified", "approved", \
"audit passed", "audit failed".

Evaluate: scope and purpose; sequence and logic; required records/forms; \
approvals and signoffs; responsibilities/ownership; verification/inspection \
steps; acceptance criteria; traceability/data capture; completeness and \
structure.

Gap reasoning: a missing step suggests execution risk; a missing control \
suggests consistency risk; a missing record suggests traceability risk; \
unclear ownership suggests confusion risk.

Respond in exactly this structure:

Comparison Summary:
[one or two sentence result]

Documents Compared:
- Internal: [Doc_Number / Title]
- Reference: [reference document name]

Possible Gaps:
- [gap]

Differences:
- [difference]

Recommended Improvements:
- [improvement]

Related Internal References:
- [related Doc_Numbers, but ONLY ones that appear in the provided registry -- never invent a Doc_Number that isn't listed. If none apply, write "None identified from the provided registry."]

Notes:
[state if the comparison is partial or approximate, and any limitations]
"""

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


def load_registry():
    with REGISTRY_CSV.open(newline="") as f:
        return list(csv.DictReader(f))


def extract_pdf_text(pdf_path):
    doc = fitz.open(pdf_path)
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    return text


def parse_match(raw_text):
    lines = [line.strip() for line in raw_text.strip().splitlines() if line.strip()]
    best_match, secondary, confidence = "NONE", "NONE", "none"
    for line in lines:
        if line.startswith("BEST_MATCH:"):
            best_match = line.split(":", 1)[1].strip()
        elif line.startswith("SECONDARY_MATCHES:"):
            secondary = line.split(":", 1)[1].strip()
        elif line.startswith("CONFIDENCE:"):
            confidence = line.split(":", 1)[1].strip()
    return best_match, secondary, confidence


def match_document(reference_text, registry):
    registry_text = "\n".join(
        f"{row['Doc_Number']} | {row['Title']} | {row['Department']} | "
        f"{row['Process']} | {row['Keywords']}"
        for row in registry
    )
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=150,
        temperature=0.0,
        system=MATCH_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Internal document registry:\n{registry_text}\n\n"
                    f"Reference document:\n{reference_text[:4000]}"
                ),
            }
        ],
    )
    return parse_match(response.content[0].text)


def compare_documents(internal_row, internal_text, reference_text, reference_name, registry):
    registry_text = "\n".join(f"{row['Doc_Number']} -- {row['Title']}" for row in registry)
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=1200,
        temperature=0.0,
        system=COMPARISON_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Full internal document registry (for the Related Internal "
                    f"References section -- do not reference anything outside this "
                    f"list):\n{registry_text}\n\n"
                    f"Internal document being compared ({internal_row['Doc_Number']} / "
                    f"{internal_row['Title']}):\n{internal_text}\n\n"
                    f"Reference document ({reference_name}):\n{reference_text}"
                ),
            }
        ],
    )
    return response.content[0].text.strip()


def compute_comparison(reference_path):
    """Pure (no printing) entry point -- safe to call from an MCP server.

    Returns a dict with either an "error" key, or "best_match", "secondary",
    "confidence", and "comparison" on success.
    """
    reference_path = Path(reference_path)
    registry = load_registry()
    reference_text = extract_pdf_text(reference_path)

    best_match, secondary, confidence = match_document(reference_text, registry)
    if best_match == "NONE":
        return {"error": "No relevant internal document found in the registry for this reference document."}

    by_doc_number = {row["Doc_Number"]: row for row in registry}
    internal_row = by_doc_number.get(best_match)
    if internal_row is None:
        return {"error": f"Matcher returned an unrecognized Doc_Number: {best_match!r}"}

    internal_text = extract_pdf_text(WI_DIR / internal_row["File_Name"])
    comparison = compare_documents(internal_row, internal_text, reference_text, reference_path.name, registry)

    return {
        "best_match": internal_row["Doc_Number"],
        "best_match_title": internal_row["Title"],
        "secondary": secondary,
        "confidence": confidence,
        "comparison": comparison,
    }


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {Path(__file__).name} <path-to-reference-document.pdf>")
        sys.exit(1)

    result = compute_comparison(sys.argv[1])
    if "error" in result:
        print(result["error"])
        return

    print(f"Best match: {result['best_match']} -- {result['best_match_title']} (confidence: {result['confidence']})")
    if result["secondary"] != "NONE":
        print(f"Secondary matches considered: {result['secondary']}")
    print(f"\n{result['comparison']}")


if __name__ == "__main__":
    main()
