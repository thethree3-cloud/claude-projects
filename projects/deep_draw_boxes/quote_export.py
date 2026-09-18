"""Formula quote + diagram -> a downloadable PDF, with Zero Manufacturing
branding.

    pdf_bytes = to_pdf(part_no, box, height_in, quote, fig, cover_type,
                        nutplate_pattern, estimate=None)

    pdf_bytes = to_pdf_mini(part_no, series, width_in, length_in, height_in,
                             material_label, quote, fig, finish=..., estimate=None)

`to_pdf_mini` is for the ZMR/ZMS miniature series (mini_series_pricing.py)
-- no cover/nutplate section, since those aren't modeled for that series
yet. Both share the header/body layout via `_write_quote_body`.

Uses fpdf2 (already a repo dependency -- see
10_resume_job_matcher/resume_export.py for the established pattern this
follows: US Letter, pt units, Helvetica, a `write()` helper). Same
approach as case_configurator/quote_export.py, duplicated rather than
shared per the decision to keep each catalog/tool self-contained.
"""

import io
from datetime import date

from fpdf import FPDF

from branding import LOGO_PATH

_LATIN1 = str.maketrans({
    "–": "-", "—": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "•": "-", "…": "...",
})

DARK = (20, 23, 26)
ACCENT = (62, 166, 224)
HEADER_H = 70

_LABELS = {
    "material": "Material", "labor": "Fabrication labor", "cover": "Cover",
    "nutplates": "Nutplates", "finish": "Finish upcharge",
}


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


def to_pdf(part_no, box, height_in, quote, fig, cover_type, nutplate_pattern, finish="mill finish", estimate=None) -> bytes:
    pdf = FPDF(format="Letter", unit="pt")
    pdf.set_auto_page_break(auto=True, margin=54)
    pdf.set_margins(54, 54, 54)
    pdf.add_page()
    _header(pdf, "Deep-Draw Box Quote")

    def write(text: str, size: float, style: str = "", gap: float = 0.0) -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(0, size * 1.35, text=_l1(text), new_x="LMARGIN", new_y="NEXT")
        if gap:
            pdf.ln(gap)

    write(f"Generated {date.today():%B %d, %Y}", 9, gap=6)
    write(
        f"{part_no}: {box['width_in']:g}\"W x {box['length_in']:g}\"L x {height_in:g}\"H, "
        f".{str(box['gauge_in']).split('.')[1]}\" gauge, cover: {cover_type}, "
        f"nutplates: {nutplate_pattern}, finish: {finish}",
        11, "B", gap=10,
    )

    _write_quote_body(pdf, write, quote, fig, estimate)
    return bytes(pdf.output())


def to_pdf_mini(part_no, series, width_in, length_in, height_in, material_label, quote, fig, finish="mill finish", estimate=None) -> bytes:
    pdf = FPDF(format="Letter", unit="pt")
    pdf.set_auto_page_break(auto=True, margin=54)
    pdf.set_margins(54, 54, 54)
    pdf.add_page()
    _header(pdf, f"{series} Miniature Box Quote")

    def write(text: str, size: float, style: str = "", gap: float = 0.0) -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(0, size * 1.35, text=_l1(text), new_x="LMARGIN", new_y="NEXT")
        if gap:
            pdf.ln(gap)

    write(f"Generated {date.today():%B %d, %Y}", 9, gap=6)
    write(
        f"{part_no}: {width_in:g}\"W x {length_in:g}\"L x {height_in:g}\"H, "
        f".{str(quote['gauge_in']).split('.')[1]}\" gauge, {material_label}, finish: {finish}",
        11, "B", gap=10,
    )

    _write_quote_body(pdf, write, quote, fig, estimate=estimate)
    return bytes(pdf.output())


def _write_quote_body(pdf: FPDF, write, quote: dict, fig, estimate) -> None:
    img_buf = io.BytesIO()
    fig.savefig(img_buf, format="png", dpi=150, bbox_inches="tight")
    img_buf.seek(0)
    pdf.image(img_buf, x=54, w=pdf.w - 108)
    pdf.ln(12)

    write("Formula Quote", 13, "B", gap=6)
    write(f"Estimated draw operations: {quote['num_draws']}", 9, gap=4)
    for key, amount in quote["line_items"].items():
        write(f"{_LABELS.get(key, key)}: ${amount:,.2f}", 10)
    pdf.ln(4)
    write(f"Subtotal: ${quote['subtotal']:,.2f}", 10)
    write(f"Markup: ${quote['markup']:,.2f}", 10, gap=4)
    write(f"Total Estimate: ${quote['total']:,.2f}", 15, "B", gap=10)

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
