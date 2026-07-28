"""Second LLM call: turn a raw SQL result set into a plain-language answer.

Mirrors the two-call pattern used in Project 01 (route, then answer) and
Project 04 (extract, then verdict) -- one call to get structured data,
one call to turn it into something a person actually reads.
"""
import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
MODEL = "claude-haiku-4-5-20251001"
MAX_ROWS_IN_PROMPT = 200

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


def format_result_table(columns, rows):
    if not rows:
        return "(no rows returned)"
    lines = [" | ".join(columns)]
    for row in rows[:MAX_ROWS_IN_PROMPT]:
        lines.append(" | ".join(str(value) for value in row))
    return "\n".join(lines)


def summarize(question, columns, rows, truncated, sql=None):
    table = format_result_table(columns, rows)
    truncation_note = (
        f"\n\nNote: results were capped at {len(rows)} rows; more rows matched the query."
        if truncated else ""
    )
    # The query is included so the model understands *why* these rows were
    # returned (e.g. a WHERE/NOT IN clause already filtered for the
    # condition the question asked about, even if that condition isn't a
    # literal column in the result). It's grounding context only -- the
    # model is still told not to expose it in the answer.
    sql_context = f"\n\nThis query produced the result below:\n{sql}" if sql else ""
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=500,
        temperature=0.0,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Question: {question}{sql_context}\n\n"
                    f"Query result:\n{table}{truncation_note}\n\n"
                    "Answer the question in plain, natural language using this "
                    "data. Use the query above only to understand what the result "
                    "represents (e.g. filters already applied) -- do not assume "
                    "you need a column that isn't there if the query's WHERE/JOIN "
                    "logic already accounts for it. If the result is genuinely "
                    "empty, say so plainly rather than guessing. Do not mention "
                    "SQL, queries, or databases in your answer -- just answer as "
                    "if you already knew the answer."
                ),
            }
        ],
    )
    return response.content[0].text.strip()


def main():
    import sys
    if len(sys.argv) < 2:
        print(f"Usage: python {Path(__file__).name} \"<question>\"")
        sys.exit(1)
    from execute_sql import execute_query
    from generate_sql import generate_sql

    question = " ".join(sys.argv[1:])
    sql = generate_sql(question)
    columns, rows, truncated = execute_query(sql)
    print(summarize(question, columns, rows, truncated, sql=sql))


if __name__ == "__main__":
    main()
