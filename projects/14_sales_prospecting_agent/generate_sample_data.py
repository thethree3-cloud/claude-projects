"""
Generates a fictional trade-show exhibitor list PDF for portfolio testing.

Everything here is invented -- a made-up expo name and made-up company
names spanning the industries a hardened-protective-case maker's ideal
customer profile might span (aerospace, defense, energy, medical,
telecom) -- not real exhibitors from any real trade show.
"""

from pathlib import Path

from fpdf import FPDF

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

EXPO_TITLE = "Fictional Aerospace & Energy Expo 2026 -- Exhibitor List"

EXHIBITORS = [
    "Ironclad Avionics Systems",
    "Meridian Energy Solutions",
    "Vantage Defense Composites",
    "Solaris Grid Technologies",
    "Northbridge Medical Devices",
    "Apex Telecom Infrastructure",
    "Titanium Ridge Aerostructures",
    "Bluewater Oil Field Services",
    "Sentinel Power Systems",
    "Cascade Signal Networks",
]


def write_exhibitor_list_pdf():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.multi_cell(0, 10, EXPO_TITLE)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    for i, name in enumerate(EXHIBITORS, start=1):
        pdf.cell(0, 8, f"{i}. {name}", new_x="LMARGIN", new_y="NEXT")
    out_path = DATA_DIR / "sample_expo_exhibitors.pdf"
    pdf.output(str(out_path))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    write_exhibitor_list_pdf()
