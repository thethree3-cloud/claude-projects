from client_profile import flatten_signals, load_client_profile
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


def _scoring_search_query(company_name, profile):
    """A second search query, built from the client profile's own signal
    terms, aimed at product/spec-level content instead of the generic
    corporate-overview text a bare company-name search tends to return.

    Built from client_profile.yaml (not hardcoded product language) so this
    stays generic across clients -- verified live that a bare name search
    for real defense primes (Collins Aerospace, BAE Systems, Boeing SC)
    surfaces revenue/headcount/news but not the spec-sheet terms
    (MIL-STD-810, field-deployed, hazardous environment) score_fit checks
    for; this query exists to go looking for that evidence specifically.
    """
    terms = sorted({s["term"] for s in flatten_signals(profile)})
    return f"{company_name} products, certifications, and technical specifications related to: {', '.join(terms)}"


def evaluate_lead(query, client_profile_path, territory_routing_path, exhibitor_profiles=None):
    """Agent 1's full pipeline so far: gather research text, then score and
    route off it. Agent 2 (CRM export) is a separate, later piece -- this
    returns the evaluated-lead structure, not a CRM-ready row.

    `exhibitor_profiles` (optional) is a normalized-name -> profile dict
    from extract_exhibitor_profiles.build_profile_lookup(). When the query
    matches a company with a real PDF profile (name/description/website
    pulled straight from a trade-show program), that text is used directly
    -- no live search needed, and `source` points at the exact PDF page.
    Companies with no matching profile fall back to live search.

    For the search fallback, two calls happen, not one: a neutral identity
    search (`search(query)`) used for location extraction and as a
    baseline for scoring, plus a second, targeted search
    (`_scoring_search_query`) aimed specifically at the client profile's
    own signal terms, appended to the same research text before scoring.
    This doesn't touch the PDF-profile path -- that text is already real
    marketing/product copy, not a generic overview, so it doesn't need a
    second search.
    """
    profile = load_client_profile(client_profile_path)
    territory_rows = load_territory_routing(territory_routing_path)

    profile_record = (exhibitor_profiles or {}).get(normalize_company_name(query))
    if profile_record:
        research_text = _research_text_from_profile(profile_record)
        scoring_text = research_text
        source = profile_record["source"]
    else:
        research_text = search(query)
        scoring_text = research_text + "\n\n" + search(_scoring_search_query(query, profile))
        source = WEB_SEARCH_SOURCE

    fit_result = score_fit(query, scoring_text, profile)
    location = extract_location(research_text)
    routing_result = route_salesperson(location, territory_rows)

    return {**fit_result, "location": location, "source": source, **routing_result}
