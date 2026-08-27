import json
import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

# .env lives at the repo root, two directories up from this file
# (projects/10_resume_job_matcher/llm_client.py -> repo root).
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

# Same model the rest of the portfolio uses -- these are structured-extraction
# calls with a strict JSON schema, which Haiku handles well and cheaply.
MODEL = "claude-haiku-4-5-20251001"

_client = None


def get_client():
    """Lazily builds a single shared Anthropic client.

    Lazy so importing this module (e.g. in tests, which mock get_client)
    never requires a real API key on disk.
    """
    global _client
    if _client is None:
        load_dotenv(ENV_PATH)
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(f"ANTHROPIC_API_KEY not found. Checked: {ENV_PATH}")
        _client = Anthropic(api_key=api_key)
    return _client


def extract_json(text_prompt, schema, max_tokens=2048):
    """Runs one Claude call constrained to `schema` and returns the parsed dict.

    The whole point of this project's parsing layer: Claude turns free-text
    resumes / job listings into structured data, but the *shape* of that data
    is guaranteed by the JSON schema, not by hoping the model formats its
    answer correctly. Callers get a plain dict back and never touch the API.
    """
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": text_prompt}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    return json.loads(response.content[0].text)
