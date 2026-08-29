import json

from web_search_agent import MODEL, get_client

CONTACT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "A named person's full name, only if explicitly stated in the text.",
        },
        "title": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "That person's job title, only if explicitly stated in the text.",
        },
        "email": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "That person's email address, only if explicitly stated in the text.",
        },
        "insufficient_information": {
            "type": "boolean",
            "description": "True if the text doesn't name a specific person at the company.",
        },
    },
    "required": ["name", "title", "email", "insufficient_information"],
    "additionalProperties": False,
}


def extract_contact(research_text):
    """Extracts a named contact person from already-gathered research text
    -- no new search, no inventing a plausible-sounding name/title/email.

    Most research text describes a company, not a specific person, so this
    is expected to honestly return insufficient_information=True far more
    often than not -- that's correct behavior, not a failure to find
    contacts that exist.
    """
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Research text:\n\n{research_text}\n\n"
                    "Extract a specific named person at this company (name, "
                    "job title, email), but ONLY if the text explicitly "
                    "names one. Do not invent a plausible-sounding contact, "
                    "and do not infer a generic role (e.g. 'Sales Manager') "
                    "if no actual person is named. If the text doesn't name "
                    "a specific person, set insufficient_information to "
                    "true and leave name/title/email null."
                ),
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": CONTACT_SCHEMA}},
    )
    parsed = json.loads(response.content[0].text)
    return {
        "name": parsed["name"],
        "title": parsed["title"],
        "email": parsed["email"],
        "insufficient_information": parsed["insufficient_information"],
    }
