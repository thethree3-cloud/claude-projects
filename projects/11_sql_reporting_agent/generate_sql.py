"""Natural-language question -> T-SQL SELECT statement.

First LLM call in the reporting pipeline: takes the schema context built by
schema.py plus a plain-English question, and asks Claude for a single T-SQL
SELECT that answers it. Produces a *candidate* query only -- it is not
trusted yet. validate_sql.py (step 4) checks it before anything is executed.
"""
import os
import re
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_CONTEXT_PATH = BASE_DIR / "data" / "schema_context.txt"
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
MODEL = "claude-haiku-4-5-20251001"

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


def load_schema_context():
    if not SCHEMA_CONTEXT_PATH.exists():
        raise RuntimeError(f"Schema context not found at {SCHEMA_CONTEXT_PATH}. Run schema.py first.")
    return SCHEMA_CONTEXT_PATH.read_text()


def extract_sql(raw_text):
    """Strip markdown code fencing if the model added it despite being told not to."""
    match = re.search(r"```(?:sql)?\s*(.*?)```", raw_text, re.DOTALL)
    sql = match.group(1) if match else raw_text
    return sql.strip().rstrip(";").strip()


def generate_sql(question, schema_context=None):
    schema_context = schema_context or load_schema_context()
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=500,
        temperature=0.0,
        messages=[
            {
                "role": "user",
                "content": (
                    "Here is the schema of a SQL Server database (AdventureWorks):\n\n"
                    f"{schema_context}\n\n"
                    f"Question: {question}\n\n"
                    "Write a single T-SQL SELECT statement that answers this question. Rules:\n"
                    "- Only a SELECT statement. Never INSERT, UPDATE, DELETE, DROP, ALTER, EXEC, "
                    "or any other statement type.\n"
                    "- Exactly one statement. No semicolons chaining multiple statements.\n"
                    "- Use only tables and columns that appear in the schema above.\n"
                    "- Bracket-quote any identifier containing a space, e.g. [Database Version].\n"
                    "- Prefer TOP N over SELECT * for \"top\"/\"best\"/\"most\" questions, and "
                    "give aggregate columns a clear alias.\n"
                    "Reply with only the SQL statement. No explanation, no markdown fencing."
                ),
            }
        ],
    )
    return extract_sql(response.content[0].text)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {Path(__file__).name} \"<question>\"")
        sys.exit(1)
    question = " ".join(sys.argv[1:])
    print(generate_sql(question))


if __name__ == "__main__":
    main()
