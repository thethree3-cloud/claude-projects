import json

from web_search_agent import MODEL, get_client, search

COMPANY_NAMES_SCHEMA = {
    "type": "object",
    "properties": {
        "companies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "is_real_prospect_business": {
                        "type": "boolean",
                        "description": (
                            "True only if this is an actual operating business "
                            "that could plausibly be a sales prospect. False for "
                            "review/directory sites (e.g. Yelp, Google Maps), "
                            "chambers of commerce, trade associations, government "
                            "bodies, or any source the text cites rather than a "
                            "business it names as being in the area."
                        ),
                    },
                },
                "required": ["name", "is_real_prospect_business"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["companies"],
    "additionalProperties": False,
}


def extract_company_names_from_text(text):
    """Pulls distinct company names out of free text (e.g. a geo-radius
    search result naming several businesses) via structured-output
    evidence-detection -- same pattern as score_fit.py: Claude only reads
    the text already gathered here, no tool access, so it cannot invent a
    company that isn't actually named in the text.

    Also filters out non-prospect entities (review/directory sites, chambers
    of commerce, trade associations, government bodies) that a live run
    surfaced as false positives -- e.g. "Yelp" or "Dallas Chamber of
    Commerce" showing up as if they were lead companies because the search
    result cited them as a source rather than naming them as a business in
    the area.
    """
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    "Text below is a web search result naming one or more "
                    "real businesses:\n\n" + text + "\n\n"
                    "List every distinct real organization name actually "
                    "mentioned in the text above -- companies, but also any "
                    "review sites, directories, chambers of commerce, trade "
                    "associations, or government bodies mentioned, so each can "
                    "be classified. Do not invent a name that isn't there, and "
                    "do not include a generic description (e.g. \"a "
                    "manufacturing company\") that is not an actual name. For "
                    "each name, set is_real_prospect_business to true only if "
                    "it's an actual operating business that could be a sales "
                    "prospect -- false for review/directory sites, chambers of "
                    "commerce, trade associations, government bodies, or "
                    "anything cited as a source rather than named as a "
                    "business in the area."
                ),
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": COMPANY_NAMES_SCHEMA}},
    )
    parsed = json.loads(response.content[0].text)
    prospect_names = [c["name"] for c in parsed["companies"] if c["is_real_prospect_business"]]
    # dict.fromkeys dedupes while preserving order -- same dedup pattern
    # score_fit.py uses for matched_terms.
    return list(dict.fromkeys(prospect_names))


def find_companies_near(location_query):
    """Geo-radius search entry point: runs the search, then splits the
    (potentially multi-company) result text into individual company names
    so each can be run through pipeline.evaluate_lead() on its own --
    mirrors extract_exhibitors.extract_company_names()'s role for the PDF
    input mode, just sourced from a live search instead of a PDF.
    """
    text = search(location_query)
    return extract_company_names_from_text(text)
