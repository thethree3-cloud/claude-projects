import re
from collections import Counter

import fitz  # PyMuPDF

BOOTH_PATTERN = re.compile(r"Booth\s*#?\s*(\d+)", re.IGNORECASE)
URL_LINE_PATTERN = re.compile(r"^(https?://\S+|www\.\S+)$", re.IGNORECASE)

MIN_DESCRIPTION_LENGTH = 15

# A column gap this wide means "start a new column" when clustering blocks
# by x0 -- separates a real 2-column layout without hardcoding page width.
COLUMN_GAP = 100

# Real content blocks within one column consistently share the same left
# edge (confirmed against a real 27-page expo program: every real
# name/description/website block in a column starts at the exact same x0).
# A stray fragment -- a logo caption, a decorative mark -- sits at a
# different x0 even though it falls inside the same broad column-gap
# cluster, so alignment to the column's dominant x0 is a more reliable
# noise signal than text length (a short but genuine continuation line,
# e.g. "platforms." at the end of a wrapped sentence, is just as short as
# real noise like a stray "AeroGlow" logo caption).
X0_ALIGNMENT_TOLERANCE = 3


def _is_noise(text):
    """True for blank text or control-character garbage (icon fonts used
    for page decorations/floor-plan labels)."""
    stripped = text.strip()
    if not stripped:
        return True
    return any(ord(ch) < 32 and ch not in "\n\t\r" for ch in stripped)


def _cluster_columns(blocks):
    """Groups blocks into left-to-right columns by x0, without assuming a
    fixed page width or a fixed number of columns. Within each resulting
    cluster, drops blocks that don't align with the cluster's dominant x0
    -- filters out stray fragments (logo captions, decorative marks) that
    fall inside the same broad x-gap as a real column but don't actually
    start at its left edge.
    """
    ordered = sorted(blocks, key=lambda b: b[0])
    columns = []
    current = []
    last_x0 = None
    for b in ordered:
        if last_x0 is not None and b[0] - last_x0 > COLUMN_GAP:
            columns.append(current)
            current = []
        current.append(b)
        last_x0 = b[0]
    if current:
        columns.append(current)

    aligned_columns = []
    for column in columns:
        if not column:
            continue
        mode_x0, _ = Counter(round(b[0]) for b in column).most_common(1)[0]
        aligned_columns.append(
            [b for b in column if abs(round(b[0]) - mode_x0) <= X0_ALIGNMENT_TOLERANCE]
        )
    return aligned_columns


def _parse_entry(lines, source):
    """Builds one profile record from every line accumulated for an entry
    (name, tagline, description, website, booth-number line, in whatever
    order/block grouping the PDF happened to produce them). Scanning line
    by line rather than assuming a fixed block shape is what makes this
    tolerant of different PDF generators -- a real trade-show program can
    render a paragraph as one block, while other PDF writers can emit one
    block per wrapped line; either way, the booth line and the website line
    are found wherever they are and pulled out, and whatever's left in
    order is the name (first line) plus description (the rest)."""
    website = None
    booth = None
    content_lines = []
    for line in lines:
        booth_match = BOOTH_PATTERN.search(line)
        if booth_match:
            booth = booth_match.group(1)
            continue
        if URL_LINE_PATTERN.match(line):
            website = line
            continue
        content_lines.append(line)

    name = content_lines[0] if content_lines else ""
    description = " ".join(content_lines[1:])

    return {
        "name": name,
        "description": description,
        "website": website,
        "booth": booth,
        "source": source,
    }


def _parse_column(blocks, source):
    """Walks one column's blocks in reading order, accumulating lines until
    a block containing a "Booth N" marker closes out the entry.

    Non-booth blocks accumulate rather than each overwriting the last --
    most entries are name+description in one block, but some (confirmed
    live: RENK Group) split the description into its own separate block
    between the name block and the website/booth block, so a single entry
    can span more than one non-booth block. A booth block closes out and
    parses whatever lines have accumulated (including its own), then
    resets -- any leftover lines with no following booth block (page
    furniture, an ad callout with nothing after it) are simply discarded at
    the end of the column.
    """
    entries = []
    pending_lines = []
    for block in blocks:
        text = block[4]
        pending_lines.extend(l.strip() for l in text.splitlines() if l.strip())
        if BOOTH_PATTERN.search(text):
            entry = _parse_entry(pending_lines, source)
            # A real profile always carries a description; a promo/ad
            # callout elsewhere in the program (e.g. "See X In Action.
            # Visit us at: Booth N") can accidentally match the same
            # name+booth shape but has no real description -- drop it
            # rather than emit a bogus near-duplicate entry.
            if len(entry["description"]) >= MIN_DESCRIPTION_LENGTH:
                entries.append(entry)
            pending_lines = []
    return entries


def extract_exhibitor_profiles(pdf_path):
    """Pulls full exhibitor profiles (name, description, website, booth) out
    of a real trade-show program PDF's exhibitor-profile pages.

    Unlike extract_exhibitors.extract_company_names() (a flat name index),
    profile pages carry a real per-exhibitor description and website --
    pre-gathered grounding text that doesn't need a live web search. Pages
    that don't contain any profile-shaped blocks (cover letter, floor plan,
    sponsor pages) simply yield zero entries and are skipped -- there's no
    hardcoded page range, so this works on any PDF with the same block
    shape, not just one specific program.
    """
    doc = fitz.open(pdf_path)
    profiles = []
    for page_number, page in enumerate(doc):
        blocks = [b for b in page.get_text("blocks") if b[6] == 0]
        blocks = [b for b in blocks if not _is_noise(b[4])]
        for column in _cluster_columns(blocks):
            column.sort(key=lambda b: b[1])
            source = f"{pdf_path} page {page_number + 1}"
            profiles.extend(_parse_column(column, source))
    doc.close()
    return profiles


def normalize_company_name(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def build_profile_lookup(profiles):
    """Maps a normalized company name -> its profile record, for matching
    against names pulled from a separate flat exhibitor index (which may
    format the same company's name slightly differently)."""
    return {normalize_company_name(p["name"]): p for p in profiles}
