import os
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

# .env lives at the repo root, three levels up from this script.
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH)

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise RuntimeError(f"ANTHROPIC_API_KEY not found. Checked: {ENV_PATH}")

client = Anthropic(api_key=api_key)

response = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=100,
    temperature=0.0,
    messages=[
        {"role": "user", "content": "Reply with exactly: Handshake successful."}
    ],
)

print(response.content[0].text)
print(f"Tokens used — input: {response.usage.input_tokens}, output: {response.usage.output_tokens}")
