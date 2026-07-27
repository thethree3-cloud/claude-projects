"""
Builds the fictional internal document registry (Doc_Number, Title,
File_Name, Department, Process, Keywords, Related_Z) that compare.py
matches uploaded reference documents against -- mirroring the CSV index
described in the real Copilot Studio audit-comparison assistant.
"""

import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_CSV = BASE_DIR / "data" / "document_registry.csv"

REGISTRY = [
    {
        "Doc_Number": "Z2-014",
        "Title": "Document Control Procedure",
        "File_Name": "WI-014_document_control.pdf",
        "Department": "Quality",
        "Process": "Document Control",
        "Keywords": "document control, revision, approval, distribution, master log",
        "Related_Z": "Z4",
    },
    {
        "Doc_Number": "Z2-022",
        "Title": "Training and Competency Program",
        "File_Name": "WI-022_training_and_quality_policy.pdf",
        "Department": "Quality/HR",
        "Process": "Training",
        "Keywords": "training, competency, quality policy, orientation, personnel records",
        "Related_Z": "Z4",
    },
    {
        "Doc_Number": "Z3-031",
        "Title": "Calibration and Measurement Equipment Control",
        "File_Name": "WI-031_calibration_control.pdf",
        "Department": "Quality",
        "Process": "Calibration",
        "Keywords": "calibration, measurement equipment, gage, certificate, third-party lab",
        "Related_Z": "Z4",
    },
    {
        "Doc_Number": "Z3-045",
        "Title": "Production Work Instructions and Nonconforming Material Handling",
        "File_Name": "WI-045_production_and_nonconformance.pdf",
        "Department": "Production/Quality",
        "Process": "Production Control, Nonconformance",
        "Keywords": "production, work instruction, point of use, nonconformance, quarantine, traveler, traceability, FOD",
        "Related_Z": "Z1, Z4",
    },
    {
        "Doc_Number": "Z2-052",
        "Title": "Supplier Approval and Corrective Action Procedure",
        "File_Name": "WI-052_supplier_and_corrective_action.pdf",
        "Department": "Quality/Supply Chain",
        "Process": "Supplier Management, Corrective Action",
        "Keywords": "supplier, approved supplier list, corrective action, root cause, effectiveness check",
        "Related_Z": "Z4",
    },
]

FIELDNAMES = ["Doc_Number", "Title", "File_Name", "Department", "Process", "Keywords", "Related_Z"]

with OUTPUT_CSV.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
    writer.writeheader()
    writer.writerows(REGISTRY)

print(f"Wrote {len(REGISTRY)} rows to {OUTPUT_CSV}")
