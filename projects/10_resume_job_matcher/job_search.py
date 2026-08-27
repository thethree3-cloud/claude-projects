"""Find live job postings with Claude's web-search + web-fetch tools.

`search_jobs()` runs one agentic Claude call: `web_search` restricted to the
curated `job_sites.ALL_JOB_SITES` list (override per call), then `web_fetch` on
the promising results to pull the full posting text. Postings that can't be
fetched keep the search-result snippet and are flagged
`grounding="search snippet"` — the same honesty pattern Project 14 uses for
"Web search" vs. "PDF-grounded" leads.

Returns a list of {title, company, location, url, description, grounding}. The
`description` is what you feed to `pipeline.evaluate_fit` as the job text.

Needs ANTHROPIC_API_KEY in the repo-root .env, same as every entry point here.
"""

import json

from job_sites import ALL_JOB_SITES
from llm_client import MODEL, get_client

# Basic tool variants — the dynamic-filtering _20260209 versions need
# Opus/Sonnet-tier models; these work with the Haiku model the project uses,
# no beta header.
WEB_FETCH_TOOL = {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 15}

# Server-side web search runs its own sampling loop and returns
# stop_reason "pause_turn" between rounds; this caps how many times we resend.
MAX_TOOL_ROUNDS = 8

# Keep each description bounded so a batch of postings fits in one response --
# the matcher only needs the requirements/responsibilities, not boilerplate.
_DESCRIPTION_CHARS = 1500

_JOBS_SCHEMA = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "location": {
                        "type": "string",
                        "description": "City/state, or 'Remote'.",
                    },
                    "url": {"type": "string", "description": "Direct link to the posting."},
                    "description": {
                        "type": "string",
                        "description": (
                            "The posting's requirements and responsibilities — full "
                            "text if the page was fetched, otherwise the search "
                            f"snippet. At most ~{_DESCRIPTION_CHARS} characters."
                        ),
                    },
                    "grounding": {
                        "type": "string",
                        "enum": ["full posting", "search snippet"],
                    },
                },
                "required": [
                    "title",
                    "company",
                    "location",
                    "url",
                    "description",
                    "grounding",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["jobs"],
    "additionalProperties": False,
}

_PROMPT = """\
Find up to {count} current job postings that match:

- Role / keywords: {keywords}
- Near: {location} — within about {radius} miles; strong remote matches are fine too

Search the job boards for matches, then use web_fetch on each promising result
to read the full posting. For any posting you cannot fetch, use the search-result
snippet and set grounding to "search snippet".

Keep each description to the most relevant ~{desc_chars} characters — the
requirements and responsibilities, not company boilerplate.

Only include real postings you actually found, each with a working URL. Never
invent a posting, company, or link. Returning fewer than {count} is fine.
"""


def _tools(sites):
    return [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 8,
            "allowed_domains": sites,
        },
        WEB_FETCH_TOOL,
    ]


def _final_text(response):
    return "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()


def search_jobs(keywords, location, radius_miles=25, count=10, sites=None):
    """Return a list of job-posting dicts matching `keywords` near `location`.

    `sites` defaults to job_sites.ALL_JOB_SITES; pass a trimmed list to focus
    the search (e.g. job_sites.ATS for fetch-reliable results only).
    """
    tools = _tools(sites or ALL_JOB_SITES)
    output_config = {"format": {"type": "json_schema", "schema": _JOBS_SCHEMA}}
    prompt = _PROMPT.format(
        count=count,
        keywords=keywords,
        location=location,
        radius=radius_miles,
        desc_chars=_DESCRIPTION_CHARS,
    )

    client = get_client()
    messages = [{"role": "user", "content": prompt}]

    # Force a tool call on the first turn -- confirmed in Project 14 that Haiku
    # will otherwise answer from memory and never search. Later turns use auto
    # so the model can stop once it has what it needs.
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        tools=tools,
        tool_choice={"type": "any"},
        messages=messages,
        output_config=output_config,
    )

    rounds = 0
    while response.stop_reason == "pause_turn" and rounds < MAX_TOOL_ROUNDS:
        messages.append({"role": "assistant", "content": response.content})
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            tools=tools,
            messages=messages,
            output_config=output_config,
        )
        rounds += 1

    text = _final_text(response)
    if not text:
        return []
    return json.loads(text)["jobs"]
