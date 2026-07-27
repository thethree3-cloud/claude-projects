"""
Generates fictional AS9100-style sample PDFs for portfolio testing.

Everything here is invented: the company ("Sample Aerospace Co."), the
clause numbering, and the requirement wording are original paraphrases
inspired by general quality-management-system concepts (document control,
calibration, corrective action, etc.) -- NOT copied from the real,
copyrighted AS9100 standard text. This exists purely so the gap-analysis
agent has realistic-looking source documents to parse and test against,
with deliberately planted gaps so the agent's output can be verified.
"""

from pathlib import Path

from fpdf import FPDF

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
WI_DIR = DATA_DIR / "work_instructions"

CRITERIA = [
    ("AC-4.2.3", "Document Control", "Documented procedures exist for controlling quality-system documents, including approval, revision, and distribution."),
    ("AC-5.3", "Quality Policy", "A documented quality policy exists, is communicated to employees, and is reviewed periodically."),
    ("AC-6.2", "Competence & Training", "Training records are maintained for personnel performing work affecting product quality."),
    ("AC-7.1.5", "Calibration Control", "Measuring equipment is calibrated on a defined schedule with records retained."),
    ("AC-7.5", "Configuration Management", "A configuration management process controls product and process changes."),
    ("AC-8.1.1", "Risk Management", "Risk management is applied to operational processes and product realization."),
    ("AC-8.3", "Design and Development Controls", "Design and development activities are planned, reviewed, verified, and validated per defined stages."),
    ("AC-8.4", "Control of Externally Provided Processes", "Suppliers are evaluated and approved before use, with ongoing performance monitoring."),
    ("AC-8.5.1", "Control of Production", "Work instructions are available at the point of use for production operations."),
    ("AC-8.5.2", "Identification and Traceability", "Products are identified and traceable at all stages of production."),
    ("AC-8.7", "Control of Nonconforming Outputs", "A documented process exists for identifying, segregating, and dispositioning nonconforming product."),
    ("AC-9.1.1", "Monitoring & Measurement", "Key process and product characteristics are monitored and measured, with records retained."),
    ("AC-9.2", "Internal Audit", "A documented internal audit program exists, is scheduled, and results are tracked to closure."),
    ("AC-10.2", "Corrective Action", "A documented process exists for corrective action, including root cause analysis and effectiveness verification."),
    ("AC-7.1.6", "FOD Prevention", "A documented foreign-object-debris prevention program is implemented."),
]

WORK_INSTRUCTIONS = {
    "WI-014_document_control.pdf": (
        "WI-014: Document Control Procedure",
        "All quality-system documents at Sample Aerospace Co. are controlled per this "
        "procedure. New and revised documents require Quality Manager approval before "
        "release. Approved documents are distributed via the controlled document "
        "register, and obsolete revisions are removed from points of use. A master "
        "revision log is maintained for all controlled documents.",
    ),
    "WI-022_training_and_quality_policy.pdf": (
        "WI-022: Training and Competency Program",
        "Employees performing work affecting product quality must complete role-based "
        "training before working unsupervised. Training records, including dates and "
        "topics covered, are retained in each employee's personnel file. The company "
        "quality policy is posted in the break room and referenced during new-hire "
        "orientation.",
    ),
    "WI-031_calibration_control.pdf": (
        "WI-031: Calibration and Measurement Equipment Control",
        "All measuring and test equipment is registered in the calibration tracking "
        "system upon receipt. Each instrument is assigned a calibration interval based "
        "on manufacturer recommendation and usage frequency. Calibration is performed "
        "by an accredited third-party lab, and certificates are retained for the life "
        "of the instrument.",
    ),
    "WI-045_production_and_nonconformance.pdf": (
        "WI-045: Production Work Instructions and Nonconforming Material Handling",
        "Current-revision work instructions are posted at each production workstation "
        "before a job is released to the floor. Operators verify the revision matches "
        "the traveler before starting work. Any part suspected of nonconformance is "
        "tagged and moved to the quarantine cage, and a nonconformance report is opened "
        "in the quality system for disposition. Job travelers record lot number and "
        "operator at each step, though raw-material heat-lot traceability is not yet "
        "linked to finished-good serial numbers.",
    ),
    "WI-052_supplier_and_corrective_action.pdf": (
        "WI-052: Supplier Approval and Corrective Action Procedure",
        "New suppliers are evaluated using the Supplier Qualification Checklist before "
        "being added to the Approved Supplier List. Approved suppliers are re-evaluated "
        "annually based on on-time delivery and incoming-inspection reject rate. Any "
        "internal or supplier-caused nonconformance triggers a corrective action "
        "request, which requires documented root-cause analysis and a follow-up "
        "effectiveness check no later than 90 days after closure.",
    ),
}


def write_criteria_pdf():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Sample Aerospace Co. -- Internal Quality Audit Checklist", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, "(Fictional, AS9100-style sample criteria generated for portfolio testing only -- not the official standard text.)")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 10)
    for clause_id, title, requirement in CRITERIA:
        line = f"{clause_id} | {title} | {requirement}"
        pdf.multi_cell(0, 6, line)
        pdf.ln(1)
    out_path = DATA_DIR / "as9100_audit_checklist.pdf"
    pdf.output(str(out_path))
    print(f"Wrote {out_path}")


def write_work_instruction_pdfs():
    WI_DIR.mkdir(parents=True, exist_ok=True)
    for filename, (title, body) in WORK_INSTRUCTIONS.items():
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, body)
        out_path = WI_DIR / filename
        pdf.output(str(out_path))
        print(f"Wrote {out_path}")


REFERENCE_DOC_TITLE = "Acme Aerostructures Inc. -- Supplier Production Process Control Requirements"
REFERENCE_DOC_BODY = (
    "Suppliers to Acme Aerostructures Inc. must post current-revision production "
    "work instructions at the point of use for every operation. Each work "
    "instruction must include a foreign-object-debris (FOD) prevention checkpoint "
    "that is signed off before a work order is closed. Nonconforming material must "
    "be identified, segregated, and dispositioned, with a documented nonconformance "
    "record retained on file. Full traceability is required from raw-material lot "
    "or heat number through to the finished-good serial number, and this linkage "
    "must be captured on the router or an equivalent record at each production "
    "step. Any nonconformance affecting product already delivered to Acme must be "
    "reported to Acme Supplier Quality within 24 hours of detection."
)


def write_reference_doc_pdf():
    # Fictional "uploaded" external document -- a customer's own production
    # process requirements, used to test compare.py's document-to-document
    # gap comparison against the closest internal work instruction (WI-045).
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.multi_cell(0, 7, REFERENCE_DOC_TITLE)
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, REFERENCE_DOC_BODY)
    out_path = DATA_DIR / "acme_production_requirements.pdf"
    pdf.output(str(out_path))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    write_criteria_pdf()
    write_work_instruction_pdfs()
    write_reference_doc_pdf()
