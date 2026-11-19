"""MCP tool server for the Commander deck builder (Project 06's pattern).

Lets any MCP client (Claude Code, Claude Desktop...) look up commanders,
build a budget deck with the no-LLM builder, and check any decklist with the
validator. Every tool returns text; facts come from the local card database
and EDHREC, never from the model calling the tool.

The deck tool uses the code-only builder on purpose: the client is already an
LLM, so a second paid Claude call inside a tool would be hidden cost.

stdio transport: stdout carries JSON-RPC, so nothing here may print to it
(card-data refresh messages go to stderr).

Run / register:
    /home/t9/venv/bin/python mcp_server.py
    claude mcp add commander-deck-builder -- /home/t9/venv/bin/python \\
        /home/t9/claude-projects/projects/18_commander_deck_builder/mcp_server.py
"""

import sys

from mcp.server.fastmcp import FastMCP

import build_deck
import card_db
import combos
import commander_lookup
import edhrec_client
import validate_deck
from collection import Collection

mcp = FastMCP("commander-deck-builder")
_db = None


def db():
    """One shared card database, refreshed daily; progress goes to stderr."""
    global _db
    if _db is None:
        _db = card_db.CardDB(card_db.ensure_db(log=lambda m: print(m, file=sys.stderr)))
    return _db


def _owned(use_collection, binder=None):
    if not use_collection:
        return set()
    col = Collection()
    try:
        return col.names(binder=binder)
    finally:
        col.close()


@mcp.tool()
def find_commander(name: str) -> str:
    """Resolve a (possibly sloppy) commander name, e.g. "krenko" or "ur dragon".

    Returns the exact card name, color identity, price, rules text, and which
    cards can be its second commander (partners, Backgrounds, Doctors), if any.
    """
    try:
        card = db().get(commander_lookup.resolve_commander(name, db()))
    except LookupError as exc:
        return f"Error: {exc}"
    lines = [
        card["name"],
        f"Color identity: {card['color_identity'] or 'colorless'}; price ${card['usd'] or 0:.2f}",
        f"Can be a commander: {'yes' if card_db.can_be_commander(card) else 'no (only as half of a pair)'}",
        "",
        card["oracle_text"],
    ]
    partners = db().partner_names(card)
    if partners:
        lines += ["", f"Can pair with {len(partners)} cards, most played first: {', '.join(partners[:10])}"
                  + (" ..." if len(partners) > 10 else "")]
    return "\n".join(lines)


@mcp.tool()
def commander_cards(commander: str, partner: str = "", max_price: float | None = None, role: str = "",
                    limit: int = 30) -> str:
    """Most-played cards for a commander from EDHREC (inclusion %, synergy, price).

    Args:
        commander: commander name (fuzzy).
        partner: optional second commander (partner / Background / Doctor).
        max_price: only cards at or under this USD price.
        role: EDHREC list, e.g. "Creature", "Instant", "Mana Artifact", "Utility Land".
        limit: how many cards to return (default 30).
    """
    try:
        info, rows = commander_lookup.lookup(commander, db(), partner=partner or None, max_price=max_price,
                                             role=role or None, limit=limit)
    except (LookupError, edhrec_client.EdhrecError) as exc:
        return f"Error: {exc}"
    return commander_lookup.format_table(info, rows)


@mcp.tool()
def build_commander_deck(commander: str, budget: float, partner: str = "", max_card_price: float | None = None,
                         use_collection: bool = False, binder: str = "") -> str:
    """Build a legal 100-card Commander deck within a USD budget (no LLM: popularity
    per role from EDHREC, checked by the full validator).

    Args:
        commander: commander name (fuzzy).
        budget: total USD to spend, commander included.
        partner: optional second commander (partner / Background / Doctor).
        max_card_price: optional per-card limit for cards you'd buy.
        use_collection: treat cards in the scanned collection as owned ($0).
        binder: with use_collection, only this binder.

    Returns a report followed by a Moxfield/Archidekt import list.
    """
    if budget < 0:
        return "Error: budget must be 0 or more."
    owned = _owned(use_collection, binder or None)
    try:
        loaded = commander_lookup.load_commanders(commander, db(), partner or None, owned)
    except (LookupError, edhrec_client.EdhrecError) as exc:
        return f"Error: {exc}"
    cmd, cost = loaded["commander"], loaded["commander_cost"]
    if cost > budget:
        return f"Error: {cmd['name']} alone costs ${cost:.2f}, over the ${budget:.2f} budget."
    pool = build_deck.candidate_pool(cmd, loaded["cards"], db(), owned, max_card_price)
    deck = build_deck.build_deck(cmd, pool, budget, owned_mode=bool(owned), commander_cost=cost)
    text = build_deck.import_text(cmd, deck)
    check = validate_deck.validate_text(text, db(), budget=budget, owned=owned, max_card_price=max_card_price,
                                        **build_deck.commander_args(cmd))
    if not check["ok"]:
        return "Error: the built deck failed validation: " + "; ".join(check["errors"])
    deck["warnings"] = loaded["warnings"] + deck["warnings"] + [f"Validator: {w}" for w in check["warnings"]]
    report = build_deck.format_report(cmd, deck, budget, bool(owned))
    return f"{report}\n\n## Import list\n\n{text}"


@mcp.tool()
def validate_commander_deck(decklist: str, budget: float | None = None, commander: str = "", partner: str = "",
                            max_card_price: float | None = None, bracket: int | None = None) -> str:
    """Check a Commander decklist against the format rules.

    Errors: unknown cards, illegal commander or pair, not 100 cards, duplicates,
    colors outside the identity, banned cards, over budget / per-card limit,
    too many Game Changers for the bracket. Warnings: land count, ramp/draw/
    removal counts, high average mana value.

    Args:
        decklist: one card per line, "1 Sol Ring" or "Sol Ring" (Moxfield/Archidekt export works).
        budget: optional USD limit for the whole deck.
        commander: commander name if it isn't the first line.
        partner: second commander if it isn't the second line.
        max_card_price: optional per-card USD limit.
        bracket: 1-5; checks the Game Changers limit for brackets 1-3.
    """
    if bracket is not None and bracket not in range(1, 6):
        return "Error: bracket must be 1-5."
    result = validate_deck.validate_text(decklist, db(), commander_name=commander or None,
                                         partner_name=partner or None, budget=budget,
                                         max_card_price=max_card_price, bracket=bracket)
    return validate_deck.format_report(result)


@mcp.tool()
def find_combos(decklist: str, two_commanders: bool = False, one_card_away: int = 5) -> str:
    """Combos in a Commander decklist, from Commander Spellbook: combos already in
    the deck, and combos one card away (inside the deck's colors) with that
    card's price.

    Args:
        decklist: one card per line; the first line is the commander.
        two_commanders: the second line is a second commander (partners / Background).
        one_card_away: how many near-miss combos to list (default 5).
    """
    try:
        names = [name for _, name in validate_deck.parse_decklist(decklist)]
    except ValueError as exc:
        return f"Error: {exc}"
    n = 2 if two_commanders else 1
    if len(names) <= n:
        return "Error: the decklist needs the commander line(s) and at least one more card."
    try:
        return combos.format_report(combos.find_combos(names[:n], names[n:], db(), almost_limit=one_card_away))
    except combos.ComboError as exc:
        return f"Error: {exc}"


if __name__ == "__main__":
    mcp.run()
