from client_profile import load_client_profile
from route_salesperson import extract_location
from score_fit import score_fit
from territory_routing import load_territory_routing, route_salesperson
from web_search_agent import search


def evaluate_lead(query, client_profile_path, territory_routing_path):
    """Agent 1's full pipeline so far: search once, then score and route
    off that same research text. Agent 2 (CRM export) is a separate,
    later piece -- this returns the evaluated-lead structure, not a
    CRM-ready row.
    """
    profile = load_client_profile(client_profile_path)
    territory_rows = load_territory_routing(territory_routing_path)

    research_text = search(query)
    fit_result = score_fit(query, research_text, profile)
    location = extract_location(research_text)
    routing_result = route_salesperson(location, territory_rows)

    return {**fit_result, "location": location, **routing_result}
