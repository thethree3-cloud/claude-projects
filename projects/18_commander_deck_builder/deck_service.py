"""Logic behind the Streamlit app, kept free of Streamlit so it can be tested.

prepare()      commander -> candidate pool (with rules text and images) + price
build_code()   no-LLM baseline deck, validated
build_claude() Claude-picked deck (llm_deck), validated; None deck if it never passed
"""

import build_deck
import card_db
import edhrec_client
import llm_deck
from validate_deck import can_be_commander, validate_text


def commander_names(db):
    """Every card that can lead a Commander deck, most-played first."""
    rows = db.conn.execute(
        "SELECT name, type_line, oracle_text FROM cards "
        "WHERE legal_commander = 1 AND (type_line LIKE '%Legendary%' OR oracle_text LIKE '%can be your commander%') "
        "ORDER BY edhrec_rank IS NULL, edhrec_rank, name"
    )
    return [r["name"] for r in rows if can_be_commander(r)]


def prepare(commander_name, db, owned=frozenset()):
    """Commander row, its checked candidate pool, and what the commander costs you."""
    commander = db.get(commander_name)
    if commander is None:
        raise LookupError(f"No card named {commander_name!r}.")
    page = edhrec_client.parse_commander_page(
        edhrec_client.fetch_commander_page(edhrec_client.slugify(commander["name"]))
    )
    if not page["commander"]["legal_commander"]:
        raise LookupError(f"{commander['name']} is not legal as a commander.")
    pool = build_deck.candidate_pool(commander, page["cards"], db, owned)
    oracle = db.get_many([c["name"] for c in pool])
    for c in pool:
        c["oracle_text"] = oracle[c["name"]]["oracle_text"]
    cost = 0.0 if commander["name"] in owned else (commander["usd"] or 0.0)
    return {"commander": commander, "pool": pool, "commander_cost": cost}


def _finish(prep, deck, budget, db, owned):
    text = build_deck.import_text(prep["commander"], deck)
    check = validate_text(text, db, budget=budget, owned=owned)
    return {"deck": deck, "text": text, "check": check}


def build_code(prep, budget, db, owned=frozenset(), owned_mode=False):
    deck = build_deck.build_deck(prep["commander"], prep["pool"], budget, owned_mode=owned_mode,
                                 commander_cost=prep["commander_cost"])
    return _finish(prep, deck, budget, db, owned) | {"builder": "Code only"}


def build_claude(prep, budget, db, client, owned=frozenset(), model=llm_deck.MODEL):
    result = llm_deck.build_with_claude(prep["commander"], prep["pool"], budget, db, client, owned,
                                        prep["commander_cost"], model=model, log=lambda *_: None)
    meta = {"builder": f"Claude ({model})", "attempts": result["attempts"], "cost_usd": result["cost_usd"]}
    if not result["ok"]:
        return {"deck": None, "text": None, "check": None, **meta}
    return _finish(prep, result["deck"], budget, db, owned) | meta | {"strategy": result["strategy"]}


def grouped(deck):
    """Deck cards grouped by role in display order, most popular first in each group."""
    groups = []
    for role in build_deck.ROLES:
        cards = sorted((c for c in deck["cards"] if c["role"] == role), key=lambda c: (-c["inclusion"], c["name"]))
        if cards:
            groups.append((role, cards))
    return groups


def price_label(card):
    if card.get("owned"):
        return "owned"
    return "n/a" if card.get("usd") is None else f"${card['usd']:.2f}"


def open_db():
    return card_db.CardDB(card_db.ensure_db(log=lambda *_: None))
