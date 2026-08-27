"""Find live job postings with Claude's web-search + web-fetch tools.

`search_jobs()` runs two Claude calls, the same split as Project 14
(`web_search_agent.search` -> `score_fit`):

1. Agentic search: `web_search` restricted to the curated `job_sites` list
   (override per call), then `web_fetch` on the promising results. Claude
   writes its findings as plain text. No schema on this turn -- combining
   structured output with the server tools proved flaky.
2. Structuring: a plain call, no tools, `output_config` json_schema, turns
   that text into a list of {title, company, location, url, description,
   grounding}. `grounding` is "full posting" or "search snippet".

The `description` is what you feed to `pipeline.evaluate_fit` as the job text.
Needs ANTHROPIC_API_KEY in the repo-root .env.
"""

import json

from job_sites import ALL_JOB_SITES
from llm_client import MODEL, get_client

# Basic tool variants -- the dynamic-filtering _20260209 versions need
# Opus/Sonnet-tier models; these work with the Haiku model the project uses.
WEB_FETCH_TOOL = {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 15}

# Server-side web search returns stop_reason "pause_turn" between rounds;
# this caps how many times we resend.
MAX_TOOL_ROUNDS = 8

# Keep each description bounded so a batch of postings fits in one response.
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
                            "The posting's requirements and responsibilities, "
                            f"at most ~{_DESCRIPTION_CHARS} characters."
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

_SEARCH_PROMPT = """\
Find up to {count} current job postings that match:

- Role / keywords: {keywords}
- Near: {location} — within about {radius} miles; strong remote matches are fine too

Search the job boards for matches, then use web_fetch on each promising result
to read the full posting. For any posting you cannot fetch, use the
search-result snippet instead.

For every posting you actually found, write a short block with: title, company,
location, the working URL, whether you read the FULL POSTING or only a SEARCH
SNIPPET, and the ~{desc_chars} most relevant characters of the description
(requirements and responsibilities, not company boilerplate).

Never invent a posting, company, or link. Returning fewer than {count} is fine.
"""

_STRUCTURE_PROMPT = """\
Convert the job-posting notes below into structured data. Use each posting's
stated URL exactly. Set grounding to "full posting" or "search snippet" based
on what the notes say. Trim each description to about {desc_chars} characters.

Notes:
---
{findings}
---
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


def _text(response):
    return "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()


def _search_and_fetch(client, tools, prompt):
    """Call 1: agentic search + fetch. Returns Claude's plain-text findings.

    tool_choice is forced on the first turn only -- confirmed in Project 14
    that Haiku will otherwise answer from memory and never search.
    """
    messages = [{"role": "user", "content": prompt}]
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        tools=tools,
        tool_choice={"type": "any"},
        messages=messages,
    )

    rounds = 0
    while response.stop_reason == "pause_turn" and rounds < MAX_TOOL_ROUNDS:
        messages.append({"role": "assistant", "content": response.content})
        response = client.messages.create(
            model=MODEL, max_tokens=8000, tools=tools, messages=messages
        )
        rounds += 1

    return _text(response)


def _structure(client, findings):
    """Call 2: no tools, schema-constrained. Findings text -> list of dicts."""
    if not findings:
        return []
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        messages=[
            {
                "role": "user",
                "content": _STRUCTURE_PROMPT.format(
                    findings=findings, desc_chars=_DESCRIPTION_CHARS
                ),
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": _JOBS_SCHEMA}},
    )
    text = _text(response)
    return json.loads(text)["jobs"] if text else []


def search_jobs(keywords, location, radius_miles=25, count=10, sites=None):
    """Return a list of job-posting dicts matching `keywords` near `location`.

    `sites` defaults to job_sites.ALL_JOB_SITES; pass a trimmed list to focus
    the search (e.g. job_sites.ATS for fetch-reliable results only).
    """
    client = get_client()
    tools = _tools(sites or ALL_JOB_SITES)
    prompt = _SEARCH_PROMPT.format(
        count=count,
        keywords=keywords,
        location=location,
        radius=radius_miles,
        desc_chars=_DESCRIPTION_CHARS,
    )
    findings = _search_and_fetch(client, tools, prompt)
    return _structure(client, findings)
