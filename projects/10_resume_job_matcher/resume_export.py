"""Assembled résumé dict -> a downloadable PDF or Word file.

The tailored-résumé builder produces Markdown; this renders the same structured
dict (see `tailor_resume.assemble`) into the two formats people actually submit.
Both are deliberately plain — one column, standard fonts, real headings, no
tables or text boxes — so an applicant-tracking system parses them cleanly.

    pdf_bytes  = to_pdf(tailored["resume"])
    docx_bytes = to_docx(tailored["resume"])

PDF uses fpdf2 (already a repo dependency). DOCX is written directly as
WordprocessingML in a zip — no python-docx needed, same call as
`resume_source`'s reader in reverse.
"""

import io
import zipfile

from fpdf import FPDF

# fpdf2's built-in fonts are Latin-1 only; map the punctuation a résumé
# actually picks up, then let anything else degrade to "?".
_LATIN1 = str.maketrans(
    {
        "–": "-",
        "—": "-",
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "•": "-",
        "…": "...",
        " ": " ",
    }
)


def _contact_line(resume, sep):
    return sep.join(
        p
        for p in [
            resume["location"],
            resume["email"],
            resume["phone"],
            *resume["links"],
        ]
        if p
    )


def _sections(resume):
    """The résumé as an ordered list of (heading, rows) blocks, where every
    row is a `(kind, text)` pair — `kind` in {"role", "bullet", "plain"}.
    `heading` is None for the summary. Shared by both renderers."""
    blocks = []
    if resume["summary"]:
        blocks.append((None, [("plain", resume["summary"])]))
    if resume["skills"]:
        blocks.append(("Skills", [("plain", ", ".join(resume["skills"]))]))
    if resume["experience"]:
        rows = []
        for role in resume["experience"]:
            header = f"{role['title']} — {role['organization']}"
            if role["dates"]:
                header += f"  ·  {role['dates']}"
            rows.append(("role", header))
            rows.extend(("bullet", h) for h in role["highlights"])
        blocks.append(("Experience", rows))
    if resume["education"]:
        rows = []
        for entry in resume["education"]:
            year = f" ({entry['year']})" if entry["year"] else ""
            rows.append(("plain", f"{entry['credential']}, {entry['institution']}{year}"))
        blocks.append(("Education", rows))
    if resume["certifications"]:
        rows = []
        for cert in resume["certifications"]:
            extra = ", ".join(p for p in [cert["issuer"], cert["year"]] if p)
            rows.append(("plain", f"{cert['name']}" + (f" ({extra})" if extra else "")))
        blocks.append(("Certifications", rows))
    return blocks


# --------------------------------------------------------------------------- PDF


def _l1(text):
    return text.translate(_LATIN1).encode("latin-1", "replace").decode("latin-1")


def to_pdf(resume) -> bytes:
    """Render an assembled résumé dict to PDF bytes (US Letter)."""
    pdf = FPDF(format="Letter", unit="pt")
    pdf.set_auto_page_break(auto=True, margin=54)
    pdf.set_margins(54, 54, 54)
    pdf.add_page()

    def write(text, size, style="", gap=0.0):
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(0, size * 1.35, text=_l1(text), new_x="LMARGIN", new_y="NEXT")
        if gap:
            pdf.ln(gap)

    if resume["name"]:
        write(resume["name"], 18, "B", gap=2)
    contact = _contact_line(resume, "  |  ")
    if contact:
        write(contact, 9, gap=8)

    style_for = {
        "role": ("", 10.5, "B"),
        "bullet": ("-  ", 10, ""),
        "plain": ("", 10, ""),
    }
    for heading, rows in _sections(resume):
        if heading:
            pdf.ln(6)
            write(heading.upper(), 10.5, "B", gap=3)
        for kind, text in rows:
            prefix, size, style = style_for[kind]
            write(prefix + text, size, style)

    return bytes(pdf.output())


# -------------------------------------------------------------------------- DOCX

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/></Relationships>'
)
_SECT_PR = (
    '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
    '<w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080"/></w:sectPr>'
)


def _esc(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _para(text, *, bold=False, half_pt=22, space_before=0):
    ppr = (
        f'<w:pPr><w:spacing w:before="{space_before}"/></w:pPr>' if space_before else ""
    )
    rpr = "<w:rPr>"
    if bold:
        rpr += "<w:b/>"
    rpr += f'<w:sz w:val="{half_pt}"/><w:szCs w:val="{half_pt}"/></w:rPr>'
    return (
        f'<w:p>{ppr}<w:r>{rpr}'
        f'<w:t xml:space="preserve">{_esc(text)}</w:t></w:r></w:p>'
    )


def to_docx(resume) -> bytes:
    """Render an assembled résumé dict to .docx bytes."""
    paras = []
    if resume["name"]:
        paras.append(_para(resume["name"], bold=True, half_pt=32))
    contact = _contact_line(resume, "  |  ")
    if contact:
        paras.append(_para(contact, half_pt=18))

    for heading, rows in _sections(resume):
        if heading:
            paras.append(_para(heading.upper(), bold=True, half_pt=24, space_before=200))
        for kind, text in rows:
            if kind == "role":
                paras.append(_para(text, bold=True, half_pt=22, space_before=120))
            elif kind == "bullet":
                paras.append(_para(f"•  {text}", half_pt=22))
            else:
                paras.append(_para(text, half_pt=22))

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(paras)}{_SECT_PR}</w:body></w:document>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", document)
    return buf.getvalue()
