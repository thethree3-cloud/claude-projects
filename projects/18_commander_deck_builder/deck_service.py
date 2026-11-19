"""Logic behind the Streamlit app, kept free of Streamlit so it can be tested.

prepare()      commander -> candidate pool (with rules text and images) + price
build_code()   no-LLM baseline deck, validated
build_claude() Claude-picked deck (llm_deck), validated; None deck if it never passed
"""

import build_deck
import card_db
import commander_lookup
import edhrec_client
import llm_deck
from validate_deck import validate_text


def commander_names(db):
    """Every card that can lead a Commander deck, most often the commander first
    (EDHREC's 2-year ranking; card popularity if EDHREC can't be reached)."""
    return db.commander_names(edhrec_client.commander_popularity())


def partner_names(commander_name, db):
    """Cards that can be this commander's second commander (empty if none)."""
    card = db.get(commander_name)
    return db.partner_names(card) if card else []


def prepare(commander_name, db, owned=frozenset(), partner_name=None, max_card_price=None):
    """Commander row (combined for a pair), its checked candidate pool, and
    what the commander(s) cost you."""
    if db.get(commander_name) is None:
        raise LookupError(f"No card named {commander_name!r}.")
    loaded = commander_lookup.load_commanders(commander_name, db, partner_name, owned)
    commander = loaded["commander"]
    pool = build_deck.candidate_pool(commander, loaded["cards"], db, owned, max_card_price)
    oracle = db.get_many([c["name"] for c in pool])
    for c in pool:
        c["oracle_text"] = oracle[c["name"]]["oracle_text"]
    return {"commander": commander, "pool": pool, "commander_cost": loaded["commander_cost"],
            "warnings": loaded["warnings"], "max_card_price": max_card_price}


def _finish(prep, deck, budget, db, owned):
    deck["warnings"] = prep.get("warnings", []) + deck["warnings"]  # e.g. thin EDHREC data
    text = build_deck.import_text(prep["commander"], deck)
    check = validate_text(text, db, budget=budget, owned=owned, max_card_price=prep.get("max_card_price"),
                          **build_deck.commander_args(prep["commander"]))
    return {"deck": deck, "text": text, "check": check}


def build_code(prep, budget, db, owned=frozenset(), owned_mode=False):
    deck = build_deck.build_deck(prep["commander"], prep["pool"], budget, owned_mode=owned_mode,
                                 commander_cost=prep["commander_cost"])
    return _finish(prep, deck, budget, db, owned) | {"builder": "Code only"}


def build_claude(prep, budget, db, client, owned=frozenset(), model=llm_deck.MODEL):
    result = llm_deck.build_with_claude(prep["commander"], prep["pool"], budget, db, client, owned,
                                        prep["commander_cost"], model=model, log=lambda *_: None,
                                        max_card_price=prep.get("max_card_price"))
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
