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


# Only some real trade-show programs give every exhibitor a full write-up --
# confirmed against a real 27-page expo program, where 159 of roughly 300
# indexed exhibitors had a full name/description/website/booth profile and
# the rest were index-only. This fictional set mirrors that split: 6 of the
# 10 EXHIBITORS above get a profile, the other 4 stay index-only so a full
# pipeline run has a real mix of "use the PDF's own text" vs. "fall back to
# live web search" cases to exercise.
#
# "Titanium Ridge Aerostructures" deliberately splits its description into
# a second block (rendered as a separate multi_cell call below) -- this
# mirrors a real layout variant found live (RENK Group, MDEX 2026 program)
# where the description sits in its own block rather than combined with the
# name, which extract_exhibitor_profiles._parse_column() must still catch
# as one entry, not two.
EXHIBITOR_PROFILES = [
    {
        "name": "Ironclad Avionics Systems",
        "tagline": "Rugged Avionics Manufacturer",
        "description": (
            "Ironclad Avionics Systems designs MIL-STD-810 rated avionics "
            "enclosures for defense and aerospace platforms."
        ),
        "website": "https://www.ironcladavionics.example/",
        "booth": "3015",
    },
    {
        "name": "Meridian Energy Solutions",
        "tagline": "Field-Deployed Power Systems",
        "description": (
            "Meridian Energy Solutions builds hazardous-environment power "
            "distribution equipment for oil, gas, and grid field sites."
        ),
        "website": "https://www.meridianenergy.example/",
        "booth": "4021",
    },
    {
        "name": "Vantage Defense Composites",
        "tagline": "Composite Structures for Defense",
        "description": (
            "Vantage Defense Composites manufactures rugged composite "
            "airframe and vehicle panels for defense-related programs."
        ),
        "website": "https://www.vantagedefense.example/",
        "booth": "5023",
    },
    {
        "name": "Titanium Ridge Aerostructures",
        "tagline": "",
        "description": (
            "Titanium Ridge Aerostructures is a supplier of MIL-STD-810 "
            "rated airframe components for avionics and defense-related "
            "aircraft programs."
        ),
        "description_extra": (
            "The company also offers field service equipment for "
            "on-site maintenance of deployed aerostructures."
        ),
        "website": "https://www.titaniumridge.example/",
        "booth": "6018",
    },
    {
        "name": "Northbridge Medical Devices",
        "tagline": "Portable Diagnostic Equipment",
        "description": (
            "Northbridge Medical Devices produces ISO 13485 certified "
            "portable diagnostic equipment for field medical use."
        ),
        "website": "https://www.northbridgemedical.example/",
        "booth": "8013",
    },
    {
        "name": "Apex Telecom Infrastructure",
        "tagline": "Field Service Equipment",
        "description": (
            "Apex Telecom Infrastructure supplies field service equipment "
            "for telecommunications network deployment and maintenance."
        ),
        "website": "https://www.apextelecom.example/",
        "booth": "9008",
    },
]


def write_exhibitor_profiles_pdf():
    """Fictional analog of a real trade-show program's exhibitor-profile
    pages -- name, description, website, and booth per exhibitor, in the
    same block shape extract_exhibitor_profiles.py parses (name+description
    as one block or two, then a separate website+booth block)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 11)

    for profile in EXHIBITOR_PROFILES:
        pdf.set_font("Helvetica", "", 11)
        name_block = profile["name"]
        if profile["tagline"]:
            name_block += "\n" + profile["tagline"]
        if "description_extra" not in profile:
            name_block += "\n" + profile["description"]
        pdf.multi_cell(0, 6, name_block, new_x="LMARGIN", new_y="NEXT")

        if "description_extra" in profile:
            pdf.multi_cell(
                0,
                6,
                profile["description"] + "\n" + profile["description_extra"],
                new_x="LMARGIN",
                new_y="NEXT",
            )

        pdf.multi_cell(
            0,
            6,
            f"{profile['website']}\nBooth {profile['booth']}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(4)

    out_path = DATA_DIR / "sample_exhibitor_profiles.pdf"
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


# Fictional past customers -- deliberately includes two names from the
# fictional EXHIBITORS list above (Ironclad Avionics Systems, Sentinel
# Power Systems) plus one name that isn't, so a full-pipeline demo (score
# every exhibitor, export, some flagged as existing customers) has a real
# mix of matches and non-matches to show.
EXISTING_CUSTOMERS = [
    "Ironclad Avionics Systems",
    "Sentinel Power Systems",
    "Harborline Marine Electronics",
]


def write_sample_existing_customers():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "sample_existing_customers.csv"
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["company_name"])
        writer.writeheader()
        writer.writerows({"company_name": name} for name in EXISTING_CUSTOMERS)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    write_exhibitor_list_pdf()
    write_exhibitor_profiles_pdf()
    write_sample_client_profile()
    write_sample_territory_routing()
    write_sample_existing_customers()
