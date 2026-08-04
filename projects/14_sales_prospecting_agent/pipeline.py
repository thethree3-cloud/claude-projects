from client_profile import load_client_profile
from extract_exhibitor_profiles import normalize_company_name
from route_salesperson import extract_location
from score_fit import score_fit
from territory_routing import load_territory_routing, route_salesperson
from web_search_agent import search

WEB_SEARCH_SOURCE = "Web search"


def _research_text_from_profile(profile_record):
    lines = [profile_record["name"], profile_record["description"]]
    if profile_record["website"]:
        lines.append(f"Website: {profile_record['website']}")
    return "\n".join(lines)


def evaluate_lead(query, client_profile_path, territory_routing_path, exhibitor_profiles=None):
    """Agent 1's full pipeline so far: gather research text once, then
    score and route off that same text. Agent 2 (CRM export) is a
    separate, later piece -- this returns the evaluated-lead structure,
    not a CRM-ready row.

    `exhibitor_profiles` (optional) is a normalized-name -> profile dict
    from extract_exhibitor_profiles.build_profile_lookup(). When the query
    matches a company with a real PDF profile (name/description/website
    pulled straight from a trade-show program), that text is used as
    research_text directly -- no live search needed, and `source` points
    at the exact PDF page it came from instead of the opaque "Web search"
    used for everything else. Companies with no matching profile fall back
    to web_search_agent.search() exactly as before.
    """
    profile = load_client_profile(client_profile_path)
    territory_rows = load_territory_routing(territory_routing_path)

    profile_record = (exhibitor_profiles or {}).get(normalize_company_name(query))
    if profile_record:
        research_text = _research_text_from_profile(profile_record)
        source = profile_record["source"]
    else:
        research_text = search(query)
        source = WEB_SEARCH_SOURCE

    fit_result = score_fit(query, research_text, profile)
    location = extract_location(research_text)
    routing_result = route_salesperson(location, territory_rows)

    return {**fit_result, "location": location, "source": source, **routing_result}
