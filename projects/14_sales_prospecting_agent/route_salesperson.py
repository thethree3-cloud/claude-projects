import json

from web_search_agent import MODEL, get_client

LOCATION_SCHEMA = {
    "type": "object",
    "properties": {
        "state": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "US state abbreviation (e.g. TX), only if explicitly stated in the text.",
        },
        "country": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "Country name, only if explicitly stated in the text.",
        },
        "insufficient_information": {
            "type": "boolean",
            "description": "True if the text doesn't state the company's location.",
        },
    },
    "required": ["state", "country", "insufficient_information"],
    "additionalProperties": False,
}


def extract_location(research_text):
    """Extracts a company's state/country from already-gathered research
    text -- no new search, no inferring location from what industry a
    company is in or where similar companies are typically based.
    """
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Research text:\n\n{research_text}\n\n"
                    "Extract the company's US state (as a two-letter "
                    "abbreviation) and/or country, but ONLY if the text "
                    "explicitly states it. Do not infer a location from "
                    "the industry or from general knowledge about where "
                    "similar companies are usually based. If the text "
                    "doesn't state a location, set insufficient_information "
                    "to true and leave state/country null."
                ),
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": LOCATION_SCHEMA}},
    )
    parsed = json.loads(response.content[0].text)
    return {
        "state": parsed["state"],
        "country": parsed["country"],
        "insufficient_information": parsed["insufficient_information"],
    }
