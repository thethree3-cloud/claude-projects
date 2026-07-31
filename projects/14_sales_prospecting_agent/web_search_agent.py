import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
MODEL = "claude-haiku-4-5-20251001"

# Haiku 4.5 isn't in the model family that supports the dynamic-filtering
# web_search_20260209 tool (that requires Opus 4.8/4.7/4.6, Sonnet 5, or
# Sonnet 4.6) -- use the basic tool version instead.
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}

# Server-side web search runs its own internal sampling loop (up to 10
# rounds) before returning stop_reason "pause_turn". This caps how many
# times we resend to let it continue, as a safety net against looping
# forever on an unusual query.
MAX_TOOL_ROUNDS = 5

# Forcing the tool is not optional here -- confirmed via a live smoke test
# that Haiku 4.5 will otherwise answer from its own training data and never
# call web_search at all (even with an explicit "you must search" system
# prompt), which silently defeats this whole project's grounding
# requirement: every claim has to trace back to an actual search, not the
# model's memory of what's near Dallas.
TOOL_CHOICE = {"type": "tool", "name": "web_search"}

_client = None


def get_client():
    global _client
    if _client is None:
        load_dotenv(ENV_PATH)
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(f"ANTHROPIC_API_KEY not found. Checked: {ENV_PATH}")
        _client = Anthropic(api_key=api_key)
    return _client


def _text_from(response):
    return "\n".join(
        block.text for block in response.content if block.type == "text"
    ).strip()


def search(query):
    """Runs a web search for `query` and returns Claude's text answer.

    Covers both prospecting input modes with the same function: pass a
    company name extracted from a trade-show exhibitor list, or a
    geo-radius query like "manufacturing businesses within 10 miles of
    Dallas, TX" -- just different query text, no branching needed.
    """
    client = get_client()
    messages = [{"role": "user", "content": query}]

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        tools=[WEB_SEARCH_TOOL],
        tool_choice=TOOL_CHOICE,
        messages=messages,
    )

    rounds = 0
    while response.stop_reason == "pause_turn" and rounds < MAX_TOOL_ROUNDS:
        # Re-send the original question plus the paused assistant turn so
        # the server resumes its search loop -- do NOT append a new
        # "continue" message, the trailing server_tool_use block is what
        # tells the API to keep going.
        messages = [
            {"role": "user", "content": query},
            {"role": "assistant", "content": response.content},
        ]
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            tools=[WEB_SEARCH_TOOL],
            tool_choice=TOOL_CHOICE,
            messages=messages,
        )
        rounds += 1

    return _text_from(response)
