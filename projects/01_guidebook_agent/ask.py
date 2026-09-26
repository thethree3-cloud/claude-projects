"""Answer questions about the employee handbook, grounded in its text.

  0. rewrite -- a follow-up ("how much notice?") is rewritten into a
                standalone question using the last few turns
  1. route   -- Claude picks up to 3 table-of-contents sections
  2. extract -- those sections' pages are pulled from the PDF
  3. answer  -- Claude answers only from that text and reports which
                sections it actually used; only those are shown as sources

    python ask.py "What is the policy on smoking?"
"""

import csv
import difflib
import os
import re
import sys
import threading
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
HISTORY_TURNS = 3     # question/answer pairs the follow-up rewrite sees
HISTORY_CHARS = 600   # per message, so long answers don't swamp the prompt
_SOURCE_TAG = re.compile(r" ?\[S\d+\]")
_USED_LINE = re.compile(r"^\s*`?USED:\s*(?P<ids>[^`\n]*)`?\s*$", re.MULTILINE | re.IGNORECASE)

# PyMuPDF isn't thread-safe, and Streamlit runs each browser session (and
# run_eval.py each worker) in its own thread. One PDF call at a time.
_PDF_LOCK = threading.Lock()

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
    """ToC rows -> sections with inclusive page ranges.

    Sections in this handbook start mid-page, so a section can run onto the
    page where the next one starts: end = the next section's start page, not
    start - 1. (With start - 1, "Workers' Compensation" lost its second page,
    where the C-1 form and HR phone number are -- found by run_eval.py.) The
    one-page overlap costs a little extra context and never cuts text off.
    """
    sections = []
    for i, row in enumerate(rows):
        start = int(row["start_page"])
        end = int(rows[i + 1]["start_page"]) if i + 1 < len(rows) else doc_page_count
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
    with _PDF_LOCK, fitz.open(PDF_PATH) as doc:
        return "\n".join(doc[p - 1].get_text() for p in range(start_page, end_page + 1))


def render_page_png(page_number, dpi=110):
    """One 1-based PDF page -> PNG bytes, for showing a source page in the UI."""
    with _PDF_LOCK, fitz.open(PDF_PATH) as doc:
        return doc[page_number - 1].get_pixmap(dpi=dpi).tobytes("png")


def page_count():
    with _PDF_LOCK, fitz.open(PDF_PATH) as doc:
        return doc.page_count


def format_history(history, max_turns=HISTORY_TURNS, max_chars=HISTORY_CHARS):
    """Last few chat messages -> a compact transcript for the rewrite prompt.
    Long answers are clipped; the rewrite only needs the gist of each turn."""
    lines = []
    for message in history[-max_turns * 2:]:
        text = " ".join(message["content"].split())
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
        lines.append(f"{message['role'].capitalize()}: {text}")
    return "\n".join(lines)


def standalone_question(question, history):
    """Rewrite a follow-up ("how much notice do I need?") into a question
    that makes sense on its own, so the router can find the right section.
    A first question skips the API call entirely."""
    if not history:
        return question
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=150,
        temperature=0.0,
        messages=[
            {
                "role": "user",
                "content": (
                    "Here is a conversation between an employee and an HR assistant:\n\n"
                    f"{format_history(history)}\n\n"
                    f"Latest question: {question}\n\n"
                    "Rewrite the latest question so it can be understood without the "
                    "conversation, filling in anything it refers back to. If it already "
                    "stands on its own, return it unchanged. Reply with only the question."
                ),
            }
        ],
    )
    return response.content[0].text.strip() or question


def split_used_sources(text, source_count):
    """Pull the trailing "USED: S1, S3" line off an answer.

    Returns (answer_without_that_line, [0-based indexes]). If the model left
    the line out, fall back to every source -- showing too many beats
    silently showing none.
    """
    match = _USED_LINE.search(text)
    body = text[:match.start()] if match else text
    # The prompt says not to show [S1] tags, but strip any that slip through.
    body = _SOURCE_TAG.sub("", body).strip()
    if not match:
        return body, list(range(source_count))
    if match["ids"].strip().upper() == "NONE":
        return body, []
    used = []
    for number in re.findall(r"\d+", match["ids"]):
        index = int(number) - 1
        if 0 <= index < source_count and index not in used:
            used.append(index)
    return body, used


def answer(question, sections_with_text):
    context = "\n\n".join(
        f"=== [S{i}] {s['subject']} (pages {s['start']}-{s['end']}) ===\n{s['text']}"
        for i, s in enumerate(sections_with_text, start=1)
    )
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=500,
        temperature=0.0,
        messages=[
            {
                "role": "user",
                "content": (
                    "Here are section(s) of an employee handbook, each tagged "
                    "[S1], [S2], ...\n\n"
                    f"{context}\n\n"
                    f"Question: {question}\n\n"
                    "Answer using only the text above. If the answer isn't in "
                    "this text, say so and suggest contacting Human Resources. "
                    "Don't start with a heading, and don't write the [S1]-style "
                    "tags in the answer -- name the section instead.\n\n"
                    "End with one final line listing the sections your answer "
                    "actually used, like `USED: S1, S3`, or `USED: NONE` if none "
                    "of them answered the question."
                ),
            }
        ],
    )
    return split_used_sources(response.content[0].text, len(sections_with_text))


NO_MATCH = ("I couldn't find a section of the handbook that covers that. "
            "For anything else, please contact Human Resources.")


def answer_question_full(question, history=()):
    """Pure (no printing) entry point -- rewrites follow-ups, routes,
    extracts, and answers.

    Returns {"answer", "sources", "searched_as"}; each source carries its
    page range so a UI can show the actual pages.
    """
    searched_as = standalone_question(question, list(history))
    sections = load_sections(page_count())
    subjects, _unmatched = route(searched_as, sections)

    if not subjects:
        return {"answer": NO_MATCH, "sources": [], "searched_as": searched_as}

    by_subject = {s["subject"]: s for s in sections}
    matched = [by_subject[subj] for subj in subjects]
    sections_with_text = [
        {**s, "text": extract_pages(s["start"], s["end"])} for s in matched
    ]
    body, used = answer(searched_as, sections_with_text)
    return {
        "answer": body,
        "sources": [matched[i] for i in used],
        "searched_as": searched_as,
    }


def format_reply(result):
    """Result dict -> markdown with a sources list."""
    reply = result["answer"]
    if result["sources"]:
        reply += "\n\nSources:\n" + "\n".join(
            f"- {s['subject']} (pages {s['start']}-{s['end']})" for s in result["sources"]
        )
    return reply


def answer_question(question, history=()):
    """String-returning wrapper, kept print-free so it's safe to call where
    stdout must stay clean, like the Project 06 MCP server (stdio transport)."""
    return format_reply(answer_question_full(question, history))


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {Path(__file__).name} \"<question>\"")
        sys.exit(1)
    question = " ".join(sys.argv[1:])
    print(answer_question(question))


if __name__ == "__main__":
    main()
