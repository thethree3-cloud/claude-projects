import csv

from existing_customers import is_existing_customer

# Invented layout -- no real CRM import format was available to reference.
# Loosely follows common CRM lead-import conventions (company, fit rating,
# lead source/status, owner) adapted to what this pipeline actually
# gathers.
CSV_FIELDNAMES = [
    "Company Name",
    "Fit Score",
    "Fit Band",
    "Fit Reason",
    "State",
    "Country",
    "Assigned Salesperson",
    "Assigned Salesperson Email",
    "Territory",
    "Assignment Reason",
    "Lead Status",
    "Existing Customer Match",
    "Review Notes",
]


def build_crm_row(lead, is_existing_customer_match):
    """Maps one pipeline.evaluate_lead()-shaped dict into a flat CRM row.

    Only "New" and "Needs Review" are ever auto-assigned as Lead Status --
    Contacted/Qualified/Follow Up Later/Not A Fit are human-set states from
    the original Lead Status design, not something this step invents on
    generation.
    """
    needs_review = lead["salesperson_name"] == "Needs Review" or lead["band"] == "Unknown"
    lead_status = "Needs Review" if needs_review else "New"

    location = lead.get("location") or {}

    return {
        "Company Name": lead["company_name"],
        "Fit Score": lead["score"],
        "Fit Band": lead["band"],
        "Fit Reason": lead["fit_reason"],
        "State": location.get("state") or "Not Found",
        "Country": location.get("country") or "Not Found",
        "Assigned Salesperson": lead["salesperson_name"],
        "Assigned Salesperson Email": lead["email"],
        "Territory": lead["territory"] or "Not Found",
        "Assignment Reason": lead["assignment_reason"],
        "Lead Status": lead_status,
        "Existing Customer Match": "Yes" if is_existing_customer_match else "No",
        "Review Notes": lead["assignment_reason"] if needs_review else "",
    }


def export_leads_to_csv(leads, existing_customers, output_path):
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for lead in leads:
            match = is_existing_customer(lead["company_name"], existing_customers)
            writer.writerow(build_crm_row(lead, match))
