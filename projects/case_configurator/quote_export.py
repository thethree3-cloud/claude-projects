"""Formula quote + diagram -> a downloadable PDF, with Zero Manufacturing
branding.

    pdf_bytes = to_pdf(spec, quote, fig, label_map, estimate=None)

Uses fpdf2 (already a repo dependency -- see
10_resume_job_matcher/resume_export.py for the established pattern this
follows: US Letter, pt units, Helvetica, a `write()` helper).
"""

import io
from datetime import date

from fpdf import FPDF

from branding import LOGO_PATH

# fpdf2's built-in fonts are Latin-1 only; degrade the rest gracefully.
_LATIN1 = str.maketrans({
    "–": "-", "—": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "•": "-", "…": "...",
})

DARK = (20, 23, 26)
ACCENT = (62, 166, 224)
HEADER_H = 70


def _l1(text: str) -> str:
    return text.translate(_LATIN1).encode("latin-1", "replace").decode("latin-1")


def _header(pdf: FPDF, subtitle: str) -> None:
    pdf.set_fill_color(*DARK)
    pdf.rect(0, 0, pdf.w, HEADER_H, style="F")
    pdf.image(str(LOGO_PATH), x=54, y=14, w=42, h=42)

    pdf.set_xy(106, 16)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 24, _l1("ZERO MANUFACTURING"))

    pdf.set_xy(106, 42)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 14, _l1(subtitle.upper()))

    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(54, HEADER_H + 16)


def to_pdf(spec, quote, fig, label_map: dict, estimate=None) -> bytes:
    pdf = FPDF(format="Letter", unit="pt")
    pdf.set_auto_page_break(auto=True, margin=54)
    pdf.set_margins(54, 54, 54)
    pdf.add_page()
    _header(pdf, "Case Configurator Quote")

    def write(text: str, size: float, style: str = "", gap: float = 0.0) -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(0, size * 1.35, text=_l1(text), new_x="LMARGIN", new_y="NEXT")
        if gap:
            pdf.ln(gap)

    write(f"Generated {date.today():%B %d, %Y}", 9, gap=6)
    write(
        f'{spec.width_in:g}"W x {spec.height_in:g}"H x {spec.depth_in:g}"D  |  '
        f"{spec.material}  |  {spec.finish}",
        11, "B", gap=10,
    )

    img_buf = io.BytesIO()
    fig.savefig(img_buf, format="png", dpi=150, bbox_inches="tight")
    img_buf.seek(0)
    pdf.image(img_buf, x=54, w=pdf.w - 108)
    pdf.ln(12)

    write("Estimated Quote", 13, "B", gap=6)
    for key, amount in quote.line_items.items():
        write(f"{label_map.get(key, key)}: ${amount:,.2f}", 10)
    pdf.ln(4)
    write(f"Subtotal: ${quote.subtotal:,.2f}", 10)
    write(f"Markup: ${quote.markup:,.2f}", 10, gap=4)
    write(f"Total Estimate: ${quote.total:,.2f}", 15, "B", gap=10)

    if estimate is not None:
        write("Similar Past Quotes (synthetic historical data)", 11, "B", gap=4)
        write(
            f"Based on {estimate.match_count} similar past quotes: average "
            f"${estimate.avg_price:,.2f} (range ${estimate.min_price:,.2f}-"
            f"${estimate.max_price:,.2f}), confidence {estimate.confidence:.0%}.",
            9, gap=10,
        )

    write(
        "Placeholder pricing -- for internal estimating purposes only, not a final quote.",
        8, "I",
    )

    return bytes(pdf.output())
