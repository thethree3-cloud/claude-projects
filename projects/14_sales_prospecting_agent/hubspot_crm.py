import os
from pathlib import Path

from dotenv import load_dotenv
from hubspot import HubSpot
from hubspot.crm.companies import (
    ApiException,
    Filter,
    FilterGroup,
    PublicObjectSearchRequest,
    SimplePublicObjectInput,
    SimplePublicObjectInputForCreate,
)
from hubspot.crm.properties import ApiException as PropertiesApiException
from hubspot.crm.properties import OptionInput, PropertyCreate

from crm_export import CSV_FIELDNAMES, build_crm_row
from existing_customers import is_existing_customer

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

_client = None

# "Company Name"/"State"/"Country" map to properties HubSpot's default
# Company object already has; everything else needs a custom property
# definition created via ensure_custom_properties().
HUBSPOT_PROPERTY_NAME_MAP = {
    "Company Name": "name",
    "Fit Score": "fit_score",
    "Fit Band": "fit_band",
    "Fit Reason": "fit_reason",
    "State": "state",
    "Country": "country",
    "Assigned Salesperson": "assigned_salesperson",
    "Assigned Salesperson Email": "assigned_salesperson_email",
    "Territory": "territory",
    "Assignment Reason": "assignment_reason",
    "Lead Status": "lead_status",
    "Existing Customer Match": "existing_customer_match",
    "Review Notes": "review_notes",
}

# Every CSV_FIELDNAMES entry must have a mapping -- checked at import time
# so a field added to one place and forgotten in the other fails loudly.
assert set(HUBSPOT_PROPERTY_NAME_MAP) == set(CSV_FIELDNAMES)


def _options(values):
    return [OptionInput(label=v, value=v, display_order=i) for i, v in enumerate(values)]


CUSTOM_COMPANY_PROPERTIES = [
    {
        "name": "fit_score",
        "label": "Fit Score",
        "type": "number",
        "field_type": "number",
        "group_name": "companyinformation",
    },
    {
        "name": "fit_band",
        "label": "Fit Band",
        "type": "enumeration",
        "field_type": "select",
        "group_name": "companyinformation",
        "options": _options(["High", "Medium", "Low", "Unknown"]),
    },
    {
        "name": "fit_reason",
        "label": "Fit Reason",
        "type": "string",
        "field_type": "textarea",
        "group_name": "companyinformation",
    },
    {
        "name": "assigned_salesperson",
        "label": "Assigned Salesperson",
        "type": "string",
        "field_type": "text",
        "group_name": "companyinformation",
    },
    {
        "name": "assigned_salesperson_email",
        "label": "Assigned Salesperson Email",
        "type": "string",
        "field_type": "text",
        "group_name": "companyinformation",
    },
    {
        "name": "territory",
        "label": "Territory",
        "type": "string",
        "field_type": "text",
        "group_name": "companyinformation",
    },
    {
        "name": "assignment_reason",
        "label": "Assignment Reason",
        "type": "string",
        "field_type": "textarea",
        "group_name": "companyinformation",
    },
    {
        "name": "lead_status",
        # Not "Lead Status" -- HubSpot's own built-in property
        # hs_lead_status already uses that exact label, and labels must be
        # unique per object type (found live: a real ApiException on
        # property creation).
        "label": "Prospecting Lead Status",
        "type": "enumeration",
        "field_type": "select",
        "group_name": "companyinformation",
        # Only "New" and "Needs Review" are ever auto-assigned by
        # crm_export.build_crm_row(); the rest are here for a human to set
        # later, same as the original Lead Status design.
        "options": _options(
            ["New", "Assigned", "Contacted", "Qualified", "Follow Up Later", "Not A Fit", "Needs Review"]
        ),
    },
    {
        "name": "existing_customer_match",
        "label": "Existing Customer Match",
        "type": "enumeration",
        "field_type": "select",
        "group_name": "companyinformation",
        "options": _options(["Yes", "No"]),
    },
    {
        "name": "review_notes",
        "label": "Review Notes",
        "type": "string",
        "field_type": "textarea",
        "group_name": "companyinformation",
    },
]


def get_hubspot_client():
    global _client
    if _client is None:
        load_dotenv(ENV_PATH)
        access_token = os.environ.get("HUBSPOT_ACCESS_TOKEN")
        if not access_token:
            raise RuntimeError(f"HUBSPOT_ACCESS_TOKEN not found. Checked: {ENV_PATH}")
        _client = HubSpot(access_token=access_token)
    return _client


def ensure_custom_properties():
    """Creates any custom company properties that don't exist yet.

    A one-time setup step against a HubSpot account, not something to run
    per lead -- same "setup once" principle as generate_sample_data.py.
    """
    client = get_hubspot_client()
    for prop in CUSTOM_COMPANY_PROPERTIES:
        try:
            client.crm.properties.core_api.get_by_name("companies", prop["name"])
        except PropertiesApiException as e:
            if e.status == 404:
                client.crm.properties.core_api.create("companies", PropertyCreate(**prop))
            else:
                raise


def build_hubspot_properties(lead, is_existing_customer_match):
    """Reuses crm_export.build_crm_row() as the single source of truth for
    field values, only translating human-readable CSV column names into
    HubSpot's required snake_case internal property names."""
    row = build_crm_row(lead, is_existing_customer_match)
    return {HUBSPOT_PROPERTY_NAME_MAP[column]: str(value) for column, value in row.items()}


def find_existing_company_id(name):
    """Searches by the "name" property (exact match) -- a real, weaker
    substitute for HubSpot's own canonical Company dedup key (domain),
    which this pipeline has never extracted. Documented, not hidden."""
    client = get_hubspot_client()
    request = PublicObjectSearchRequest(
        filter_groups=[FilterGroup(filters=[Filter(property_name="name", operator="EQ", value=name)])],
        limit=1,
    )
    response = client.crm.companies.search_api.do_search(public_object_search_request=request)
    if response.total > 0:
        return response.results[0].id
    return None


def upsert_company(lead, is_existing_customer_match):
    """Creates or updates one HubSpot Company record for a lead. Catches
    ApiException per company rather than letting one bad record crash a
    whole batch -- a real external API call can fail independently per
    record in a way a CSV write never could."""
    client = get_hubspot_client()
    company_name = lead["company_name"]
    properties = build_hubspot_properties(lead, is_existing_customer_match)

    try:
        existing_id = find_existing_company_id(company_name)
        if existing_id:
            client.crm.companies.basic_api.update(
                company_id=existing_id,
                simple_public_object_input=SimplePublicObjectInput(properties=properties),
            )
            return {"company_name": company_name, "hubspot_company_id": existing_id, "action": "updated"}

        response = client.crm.companies.basic_api.create(
            simple_public_object_input_for_create=SimplePublicObjectInputForCreate(properties=properties),
        )
        return {"company_name": company_name, "hubspot_company_id": response.id, "action": "created"}
    except ApiException as e:
        return {"company_name": company_name, "hubspot_company_id": None, "action": "error", "error": str(e)}


def export_leads_to_hubspot(leads, existing_customers):
    ensure_custom_properties()
    return [
        upsert_company(lead, is_existing_customer(lead["company_name"], existing_customers))
        for lead in leads
    ]
