import json

from client_profile import flatten_signals, load_client_profile
from web_search_agent import MODEL, get_client, search

HIGH_THRESHOLD = 70
MEDIUM_THRESHOLD = 40


def compute_score(matched_terms, flat_signals):
    """Sums the weights of matched terms, capped at 100.

    Any term Claude returns that isn't actually one of the profile's known
    signals is ignored -- a safety net independent of the JSON schema's enum
    constraint, so a bad/hallucinated term can never contribute weight.
    """
    weight_by_term = {s["term"]: s["weight"] for s in flat_signals}
    matched = set(matched_terms) & weight_by_term.keys()
    return min(100, sum(weight_by_term[term] for term in matched))


def compute_band(score, insufficient_information):
    """Unknown means not enough evidence gathered to judge fit at all --
    distinct from a genuinely low score, which means fit was judged and
    found weak."""
    if insufficient_information:
        return "Unknown"
    if score >= HIGH_THRESHOLD:
        return "High"
    if score >= MEDIUM_THRESHOLD:
        return "Medium"
    return "Low"


def _build_schema(known_terms):
    return {
        "type": "object",
        "properties": {
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "term": {"type": "string", "enum": known_terms},
                        "evidence": {
                            "type": "string",
                            "description": "Short quote from the research text supporting this match.",
                        },
                    },
                    "required": ["term", "evidence"],
                    "additionalProperties": False,
                },
            },
            "insufficient_information": {
                "type": "boolean",
                "description": (
                    "True if the research text doesn't contain enough real "
                    "company information to judge fit at all."
                ),
            },
        },
        "required": ["matches", "insufficient_information"],
        "additionalProperties": False,
    }


def score_fit(company_name, research_text, profile):
    """Scores one company's fit against a client profile.

    Claude's only job here is evidence-detection over the research text
    already gathered by web_search_agent.search() -- it has no tools and no
    ability to search further, so it cannot invent evidence beyond what's in
    that text. The actual score/band arithmetic happens in Python
    (compute_score/compute_band), not in the LLM call.
    """
    flat_signals = flatten_signals(profile)
    known_terms = [s["term"] for s in flat_signals]

    response = get_client().messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Research text about {company_name}:\n\n{research_text}\n\n"
                    "Signal terms to check for:\n"
                    + "\n".join(known_terms)
                    + "\n\nReturn only the terms that have actual supporting "
                    "evidence in the research text above, each with a short "
                    "quote from that text. Do not infer a term from context "
                    "or general knowledge about the company -- if the text "
                    "doesn't say it, don't include it. If the research text "
                    "doesn't contain enough real information about this "
                    "company to judge fit at all, set "
                    "insufficient_information to true."
                ),
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": _build_schema(known_terms)}},
    )

    parsed = json.loads(response.content[0].text)
    # dict.fromkeys dedupes while preserving order -- Claude can return the
    # same term more than once (e.g. citing separate pieces of evidence for
    # it), and without this matched_signals/fit_reason would list it
    # multiple times even though compute_score already dedupes internally.
    matched_terms = list(dict.fromkeys(m["term"] for m in parsed["matches"]))
    evidence_by_term = {m["term"]: m["evidence"] for m in parsed["matches"]}
    insufficient_information = parsed["insufficient_information"]

    score = compute_score(matched_terms, flat_signals)
    band = compute_band(score, insufficient_information)

    by_term = {s["term"]: s for s in flat_signals}
    matched_signals = [
        {
            "term": term,
            "industry": by_term[term]["industry"],
            "weight": by_term[term]["weight"],
            "evidence": evidence_by_term[term],
        }
        for term in matched_terms
        if term in by_term
    ]

    if insufficient_information:
        fit_reason = "Not enough information gathered to judge fit."
    elif matched_signals:
        fit_reason = (
            f"Matched {len(matched_signals)} of {len(flat_signals)} signals: "
            + ", ".join(s["term"] for s in matched_signals)
        )
    else:
        fit_reason = "No matching signals found in the research gathered."

    return {
        "company_name": company_name,
        "score": score,
        "band": band,
        "matched_signals": matched_signals,
        "fit_reason": fit_reason,
    }


def evaluate_company(query, client_profile_path):
    """Agent 1's core loop so far: search, then score.

    Salesperson/territory routing and the separate Agent 2 (CRM export)
    step are still deferred to a later slice.
    """
    profile = load_client_profile(client_profile_path)
    research_text = search(query)
    return score_fit(query, research_text, profile)
