"""
Generates a fictional trade-show exhibitor list PDF for portfolio testing.

Everything here is invented -- a made-up expo name and made-up company
names spanning the industries a hardened-protective-case maker's ideal
customer profile might span (aerospace, defense, energy, medical,
telecom) -- not real exhibitors from any real trade show.
"""

import csv
from pathlib import Path

import yaml
from fpdf import FPDF

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Fictional, generic ideal-customer profile for a hardened-protective-case
# maker -- not any real company's actual ICP. Signal terms are chosen to
# plausibly match language real companies use in their own descriptions
# (confirmed live: a real web search on a real rugged-display manufacturer
# actually surfaced "rugged", "aerospace", "defense-related", "ISO-13485"
# verbatim), so scoring against real search results has a real shot at
# working, not just against fictional exhibitor names.
SAMPLE_CLIENT_PROFILE = {
    "client_name": "Fictional Rugged Cases Co.",
    "product_summary": (
        "Hardened, custom-foam protective cases and enclosures for "
        "sensitive equipment."
    ),
    "industries": [
        {
            "name": "Aerospace & Defense",
            "fit_tier": "strong",
            "signals": [
                {"term": "MIL-STD-810", "weight": 25},
                {"term": "avionics", "weight": 20},
                {"term": "defense-related", "weight": 15},
                {"term": "rugged", "weight": 15},
            ],
        },
        {
            "name": "Energy / Oil & Gas",
            "fit_tier": "strong",
            "signals": [
                {"term": "field-deployed", "weight": 20},
                {"term": "hazardous environment", "weight": 15},
            ],
        },
        {
            "name": "Medical Devices",
            "fit_tier": "medium",
            "signals": [
                {"term": "portable diagnostic", "weight": 15},
                {"term": "ISO 13485", "weight": 15},
            ],
        },
        {
            "name": "Telecommunications",
            "fit_tier": "medium",
            "signals": [
                {"term": "field service equipment", "weight": 10},
            ],
        },
    ],
}

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


def write_sample_client_profile():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "sample_client_profile.yaml"
    with out_path.open("w") as f:
        yaml.safe_dump(SAMPLE_CLIENT_PROFILE, f, sort_keys=False)
    print(f"Wrote {out_path}")


# Fictional salespeople and territories -- coverage is semicolon-separated
# state abbreviations for a domestic row, or the sentinel "INTERNATIONAL"
# for the one international row. Never invent an assignment beyond what's
# in this file -- a state/country with no covering row here means "Needs
# Review", not a guessed salesperson.
TERRITORY_ROUTING_ROWS = [
    {
        "salesperson_name": "Jordan Reyes",
        "email": "jordan.reyes@fictionalrugged.example",
        "territory": "Southwest",
        "coverage": "TX;NM;AZ;OK",
    },
    {
        "salesperson_name": "Casey Kim",
        "email": "casey.kim@fictionalrugged.example",
        "territory": "Southeast",
        "coverage": "FL;GA;AL;SC;NC",
    },
    {
        "salesperson_name": "Morgan Blake",
        "email": "morgan.blake@fictionalrugged.example",
        "territory": "International",
        "coverage": "INTERNATIONAL",
    },
]


def write_sample_territory_routing():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "sample_territory_routing.csv"
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["salesperson_name", "email", "territory", "coverage"]
        )
        writer.writeheader()
        writer.writerows(TERRITORY_ROUTING_ROWS)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    write_exhibitor_list_pdf()
    write_sample_client_profile()
    write_sample_territory_routing()
