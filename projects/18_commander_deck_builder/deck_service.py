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
        c["type_line"] = oracle[c["name"]]["type_line"]
        c["cmc"] = oracle[c["name"]]["cmc"]
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


# ---------------------------------------------------------------------------
# Alternates: the next-best cards by type, and validated swaps
# ---------------------------------------------------------------------------

CARD_TYPES = ("Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Battle", "Land")
_TYPE_ORDER = ("Land", "Creature", "Planeswalker", "Battle", "Instant", "Sorcery", "Artifact", "Enchantment")


def card_type(card):
    """One main type per card, from the front face: an Artifact Creature is a
    Creature, an Artifact Land is a Land."""
    front = (card.get("type_line") or "").split(" // ")[0]
    return next((t for t in _TYPE_ORDER if t in front), "Other")


def type_counts(deck):
    counts = {}
    for c in deck["cards"]:
        counts[card_type(c)] = counts.get(card_type(c), 0) + 1
    return counts


def alternates(prep, deck, kind, limit=15):
    """Top ``limit`` cards of type ``kind`` from the checked pool that aren't in
    the deck: EDHREC-listed first, then most played, then cheapest."""
    in_deck = {c["name"] for c in deck["cards"]}
    found = [c for c in prep["pool"] if c["name"] not in in_deck and card_type(c) == kind]
    found.sort(key=lambda c: (not c["listed"], -c["inclusion"], c["cost"], c["name"]))
    return found[:limit]


def replace_options(deck, kind=None):
    """Deck cards that could make room, least played first (same type when ``kind`` is set)."""
    cards = [c for c in deck["cards"] if kind is None or card_type(c) == kind]
    return sorted(cards, key=lambda c: (c["inclusion"], -c["cost"], c["name"]))


def swap(prep, result, out_name, in_name, budget, db, owned=frozenset()):
    """Replace one deck card with a pool card and re-run the validator.

    Returns ``(new_result, errors)``. The swap is applied only when the deck
    stays valid (legal, in budget, under the per-card cap); otherwise
    ``new_result`` is None and ``errors`` says why."""
    deck = result["deck"]
    out = next((c for c in deck["cards"] if c["name"] == out_name), None)
    new = next((c for c in prep["pool"] if c["name"] == in_name), None)
    if out is None or new is None:
        return None, [f"{out_name if out is None else in_name} isn't available to swap."]
    if any(c["name"] == in_name for c in deck["cards"]):
        return None, [f"{in_name} is already in the deck."]
    new = {**new, "reason": "Swapped in by you"} if any(c.get("reason") for c in deck["cards"]) else dict(new)
    cards = [new if c["name"] == out_name else c for c in deck["cards"]]
    new_deck = {**deck, "cards": cards, "spent": round(deck["spent"] - out["cost"] + new["cost"], 2)}
    text = build_deck.import_text(prep["commander"], new_deck)
    check = validate_text(text, db, budget=budget, owned=owned, max_card_price=prep.get("max_card_price"),
                          **build_deck.commander_args(prep["commander"]))
    if not check["ok"]:
        return None, check["errors"]
    swaps = result.get("swaps", []) + [{"out": out_name, "in": in_name, "extra": round(new["cost"] - out["cost"], 2)}]
    return {**result, "deck": new_deck, "text": text, "check": check, "swaps": swaps}, []


def deck_combos(commander, deck, db):
    """Combos in a built deck (Commander Spellbook); raises combos.ComboError."""
    import combos
    return combos.deck_combos(commander, deck, db)


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
