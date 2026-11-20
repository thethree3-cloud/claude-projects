"""Blind human review of the judge's deck pairs (Streamlit page).

Run:
    /home/t9/venv/bin/streamlit run review_decks.py

Shows a few Slice 6 cases as "Deck A" / "Deck B" (same blind lists the judge
read: card type groups, rules text, counted facts; no builder, prices or
reasons). You pick the deck you'd rather play. Who built which deck and what
the judge said stay hidden until every case is reviewed; then the page shows
how often you agreed with the judge. Picks are saved to
evals/judge/human_review.jsonl (one row per case, latest pick wins).
"""

import json
import random
import time

import streamlit as st

import card_db
import judge_decks

st.set_page_config(page_title="Blind deck review", page_icon=":material/balance:", layout="wide")

# Two per budget, including two cases the judge split on (atraxa-50, lathril-50).
REVIEW_CASES = ("atraxa-50", "lathril-50", "esika-150", "krenko-150", "muldrotha-500", "talrand-500")
SEED = 18
REVIEW_FILE = judge_decks.JUDGE_DIR / "human_review.jsonl"
JUDGE_FILE = judge_decks.JUDGE_DIR / judge_decks.JUDGE_MODEL / "results.jsonl"


@st.cache_data(show_spinner="Rebuilding the decks...")
def load_pairs():
    """``[{id, commander, oracle, budget, a_is, deck_a, deck_b}]`` with a fixed random A/B order."""
    cases = {c["id"]: c for c in judge_decks.eval_cases()}
    rng = random.Random(SEED)
    db = card_db.CardDB(card_db.ensure_db(log=lambda *_: None))
    try:
        pairs = []
        for cid in REVIEW_CASES:
            case = cases[cid]
            trace = json.loads(case["trace"].read_text())
            commander, claude, baseline = judge_decks.rebuild_decks(case, trace, db)
            a_is = rng.choice(("claude", "baseline"))
            first, second = (claude, baseline) if a_is == "claude" else (baseline, claude)
            pairs.append({
                "id": cid, "commander": commander["name"], "oracle": commander["oracle_text"],
                "budget": judge_decks.parse_trace(trace)["budget"], "a_is": a_is,
                "deck_a": judge_decks.deck_text(first, db), "deck_b": judge_decks.deck_text(second, db),
            })
        return pairs
    finally:
        db.close()


def load_picks():
    if not REVIEW_FILE.exists():
        return {}
    picks = {}
    for line in REVIEW_FILE.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            picks[row["prompt_id"]] = row  # latest pick wins
    return picks


def save_pick(pair, choice, note):
    winner = {"A": pair["a_is"], "B": "baseline" if pair["a_is"] == "claude" else "claude", "Tie": "tie"}[choice]
    REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW_FILE.open("a") as f:
        f.write(json.dumps({"prompt_id": pair["id"], "picked": choice, "winner": winner, "a_is": pair["a_is"],
                            "note": note, "time": time.time()}) + "\n")


def judge_verdicts():
    """Judge's case verdict: claude / baseline / split (both orders must agree)."""
    by_case = {}
    if JUDGE_FILE.exists():
        for line in JUDGE_FILE.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                by_case.setdefault(row["prompt_id"], set()).add(row["winner"])
    return {cid: (w.pop() if len(w) == 1 and "tie" not in w else "split") for cid, w in by_case.items()}


def deck_markdown(text):
    """The judge's plain list as markdown: group headers bold, facts as a caption line."""
    out = []
    for line in text.splitlines():
        if line.startswith("Facts:"):
            out.append(f"*{line}*")
        elif line.endswith(":") and not line.startswith("- "):
            out.append(f"\n**{line[:-1]}**\n")
        else:
            out.append(line)
    return "\n".join(out)


pairs = load_pairs()
picks = load_picks()
done = [p for p in pairs if p["id"] in picks]

st.title("Blind deck review")
st.caption("Which deck would you rather play? Builders stay hidden until all cases are reviewed.")
st.progress(len(done) / len(pairs), text=f"{len(done)} of {len(pairs)} reviewed")

labels = [f"{'✓ ' if p['id'] in picks else ''}{p['commander']} - ${p['budget']:.0f}" for p in pairs]
index = st.segmented_control("Case", range(len(pairs)), format_func=lambda i: labels[i], key="case",
                             default=next((i for i, p in enumerate(pairs) if p["id"] not in picks), 0),
                             required=True)
pair = pairs[index]

st.subheader(f"{pair['commander']} - ${pair['budget']:.0f} budget")
st.markdown(f"> {pair['oracle']}".replace("\n", "\n> "))

with st.form(f"pick-{pair['id']}", border=True):
    previous = picks.get(pair["id"])
    choice = st.segmented_control("Your pick", ["A", "Tie", "B"], key=f"choice-{pair['id']}",
                                  default=previous["picked"] if previous else None)
    note = st.text_input("Why (optional)", value=previous["note"] if previous else "", key=f"note-{pair['id']}")
    if st.form_submit_button("Save pick", type="primary", icon=":material/check:"):
        if choice is None:
            st.warning("Pick A, B or Tie first.", icon=":material/warning:")
        else:
            save_pick(pair, choice, note)
            st.rerun()

col_a, col_b = st.columns(2, border=True)
with col_a:
    st.markdown("### Deck A")
    st.markdown(deck_markdown(pair["deck_a"]))
with col_b:
    st.markdown("### Deck B")
    st.markdown(deck_markdown(pair["deck_b"]))

if len(done) == len(pairs):
    st.divider()
    st.subheader("Reveal: you vs the judge")
    verdicts = judge_verdicts()
    rows, agree = [], 0
    for p in pairs:
        mine, judge = picks[p["id"]]["winner"], verdicts.get(p["id"], "n/a")
        agree += mine == judge
        rows.append({"Case": f"{p['commander']} ${p['budget']:.0f}", "Deck A was": p["a_is"], "You": mine,
                     "Judge": judge, "Agree": mine == judge, "Your note": picks[p["id"]]["note"]})
    st.metric("Agreement with the judge", f"{agree} of {len(pairs)}", border=True)
    st.dataframe(rows, hide_index=True)
