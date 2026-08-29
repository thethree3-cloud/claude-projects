"""One-off script: runs a handful of fictional leads through the full
pipeline (search -> score -> locate -> route) and exports them into a real
HubSpot account -- Companies always, plus Deals (associated to their
Company) for High/Medium fit leads.

Existing-customer status comes from hubspot_deals.find_existing_customer_names()
(live, from closed-won Deals already in the account), not from a static
CSV/Excel file -- this is what actually exercises the bidirectional-read
path end to end.

Not part of the test suite or the reusable library -- a driver script for
a real live run against Alan's own HubSpot sandbox
(HUBSPOT_ACCESS_TOKEN in .env). Same fictional companies used to verify
Slice 5's Company upsert live.
"""

from hubspot_crm import export_leads_to_hubspot
from hubspot_deals import find_existing_customer_names
from pipeline import evaluate_lead

CLIENT_PROFILE_PATH = "data/sample_client_profile.yaml"
TERRITORY_ROUTING_PATH = "data/sample_territory_routing.csv"

FICTIONAL_LEADS = [
    "Ironclad Avionics Systems",
    "Meridian Energy Solutions",
    "Vantage Defense Composites",
]


def main():
    print("Looking up existing customers from HubSpot closed-won deals...")
    existing_customers = find_existing_customer_names()
    print(f"Found {len(existing_customers)} existing customer name(s) in HubSpot.")

    leads = [evaluate_lead(name, CLIENT_PROFILE_PATH, TERRITORY_ROUTING_PATH) for name in FICTIONAL_LEADS]
    for lead in leads:
        print(f"{lead['company_name']}: {lead['score']}/{lead['band']}")

    results = export_leads_to_hubspot(leads, existing_customers)

    print("\nHubSpot export results:")
    for result in results:
        line = f"  {result['company_name']}: company {result['action']} ({result['hubspot_company_id']})"
        if "hubspot_deal_id" in result:
            line += f", deal {result['deal_action']} ({result['hubspot_deal_id']})"
        if "hubspot_note_id" in result:
            line += f", note created ({result['hubspot_note_id']})"
        if "hubspot_contact_id" in result:
            line += f", contact {result['contact_action']} ({result['hubspot_contact_id']})"
        print(line)


if __name__ == "__main__":
    main()
