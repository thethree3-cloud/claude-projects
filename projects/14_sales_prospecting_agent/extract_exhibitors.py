import re

import fitz  # PyMuPDF

LINE_PATTERN = re.compile(r"^\d+\.\s*(.+)$")

PURE_BOOTH_NUMBER_PATTERN = re.compile(r"^\d+$")

# A real index-column block (confirmed against a real 27-page expo
# program) is narrow (one column of names) but tall (dozens of entries) --
# distinguishes it from floor-plan labels (small in both dimensions), the
# section header, and the page footer (wide, short).
MIN_COLUMN_WIDTH = 100
MAX_COLUMN_WIDTH = 300
MIN_COLUMN_HEIGHT = 100

# Consecutive spans within this many points of each other's y0 are treated
# as the same visual row (a name span and its booth-number span always
# share the same y0 in the one real program this was tested against).
ROW_Y_TOLERANCE = 2.0

# A name/measurement this long is never a real company name -- catches a
# non-index block (an agenda page, a sponsor page) that still happens to
# pass the column-shape filter above.
MAX_PLAUSIBLE_NAME_LENGTH = 100

# A bare number, optionally with a decimal and a K/M/B/% suffix, is a
# metric/chart label (confirmed live: "1.0K" pulled from a dashboard-style
# ad mockup on a non-index page), never a real company name.
NUMERIC_LABEL_PATTERN = re.compile(r"^[\d,.]+[KMB%]?$", re.IGNORECASE)


def extract_company_names(pdf_path):
    """Pulls company names out of a trade-show exhibitor list PDF.

    Tries the fictional numbered-list format first (`N. Company Name`, what
    generate_sample_data.py writes); if that finds nothing, falls back to
    the tab+booth-number index format a real trade-show program actually
    uses. Unlike Project 01's handbook (which has a table-of-contents page
    mapping subjects to page ranges), an exhibitor list is just a flat
    index, so this is a standalone line parse rather than a reuse of
    build_toc.py's state machine.
    """
    doc = fitz.open(pdf_path)
    pages_text = [page.get_text() for page in doc]

    # Require more than one match before trusting the numbered-list format
    # -- a single coincidental match (confirmed live: some unrelated
    # "$70.0K"-shaped figure elsewhere in a real 27-page program matches
    # "N. text" too) would otherwise short-circuit before ever trying the
    # real tab+booth fallback below.
    names = _extract_numbered_list("\n".join(pages_text))
    if len(names) > 1:
        doc.close()
        return names

    all_names = []
    for page in doc:
        for name, _booth in _extract_tab_booth_index(page):
            if (
                len(name) <= MAX_PLAUSIBLE_NAME_LENGTH
                and not _is_letter_spaced_caption(name)
                and not NUMERIC_LABEL_PATTERN.match(name)
            ):
                all_names.append(_strip_exhibitors_header(name))
    doc.close()
    return all_names


# A decorative letter-spaced footer caption (confirmed live: "A p r e m i e
# r   d o d   b u y e r ..." rendered with a space between every single
# character) can survive the other filters. No real company name is single
# characters end to end, so this is a safe, generic signal -- not
# something that needs a hardcoded string match against this one program's
# specific footer text.
def _is_letter_spaced_caption(name):
    tokens = name.split()
    if not tokens:
        return False
    single_char_tokens = sum(1 for t in tokens if len(t) == 1)
    return single_char_tokens / len(tokens) > 0.5


def _strip_exhibitors_header(name):
    # The index page's "Exhibitors" section header has no booth number of
    # its own, so it merges into whatever the first real entry happens to
    # be (confirmed live: "Exhibitors 313 Industries, Inc.").
    if name.startswith("Exhibitors "):
        return name[len("Exhibitors "):]
    return name


def _extract_numbered_list(text):
    names = []
    for line in text.splitlines():
        match = LINE_PATTERN.match(line.strip())
        if match:
            names.append(match.group(1).strip())
    return names


def _is_index_column_block(block):
    x0, y0, x1, y1 = block[:4]
    return MIN_COLUMN_WIDTH <= (x1 - x0) <= MAX_COLUMN_WIDTH and (y1 - y0) >= MIN_COLUMN_HEIGHT


def _flatten_spans(page, clip):
    spans = []
    for block in page.get_text("dict", clip=clip)["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if text:
                    spans.append((span["bbox"][1], span["bbox"][0], text))
    return spans


def _group_spans_into_rows(spans):
    """Groups spans (y0, x0, text) into visual rows by y0, then sorts each
    row left-to-right by x0."""
    ordered = sorted(spans)
    rows = []
    current = []
    last_y0 = None
    for y0, x0, text in ordered:
        if last_y0 is not None and abs(y0 - last_y0) > ROW_Y_TOLERANCE:
            rows.append(sorted(current, key=lambda s: s[1]))
            current = []
        current.append((y0, x0, text))
        last_y0 = y0
    if current:
        rows.append(sorted(current, key=lambda s: s[1]))
    return rows


def _row_name_and_booth(row):
    """A row is one or more spans left-to-right. If the rightmost span is a
    bare number, it's the booth number and everything else on the row is
    name text; otherwise the whole row is name text with no booth."""
    texts = [text for _, _, text in row]
    if texts and PURE_BOOTH_NUMBER_PATTERN.match(texts[-1]):
        name = " ".join(t.rstrip("\t").strip() for t in texts[:-1]).strip()
        return name or None, texts[-1]
    return " ".join(t.rstrip("\t").strip() for t in texts).strip() or None, None


def _parse_index_rows(rows):
    """Turns rows into (name, booth) entries.

    A row with no booth number is always a continuation of the previous
    row's name -- confirmed live via span geometry: a company name wrapped
    across two rows still has its booth number on the *first* row (shared
    y0 with the name's first line), not the second. So a booth number seen
    on one row is only "claimed" once the next row proves it isn't also
    part of the same name -- i.e. once the next row has its own booth
    number, or there is no next row.
    """
    entries = []
    pending_name_parts = []
    pending_booth = None
    for i, row in enumerate(rows):
        name, booth = _row_name_and_booth(row)
        if name:
            pending_name_parts.append(name)
        if booth:
            pending_booth = booth

        if pending_booth is None:
            continue

        next_row = rows[i + 1] if i + 1 < len(rows) else None
        next_has_own_booth = next_row is not None and _row_name_and_booth(next_row)[1] is not None
        if next_row is None or next_has_own_booth:
            entries.append((" ".join(pending_name_parts), pending_booth))
            pending_name_parts = []
            pending_booth = None
    return entries


def _extract_tab_booth_index(page):
    """Parses the real "Name + right-aligned booth number" index format
    directly from PyMuPDF's span-level geometry, not plain text -- plain
    text has no way to tell that a wrapped company name's booth number sits
    on its *first* row (see _parse_index_rows), since it linearizes
    same-page spans into a single flat line stream.
    """
    entries = []
    for block in page.get_text("blocks"):
        if block[6] != 0 or not _is_index_column_block(block):
            continue
        clip = fitz.Rect(*block[:4])
        spans = _flatten_spans(page, clip)
        rows = _group_spans_into_rows(spans)
        entries.extend(_parse_index_rows(rows))
    return entries
