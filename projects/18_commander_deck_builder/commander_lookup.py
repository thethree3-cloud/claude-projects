"""Commander lookup: commander name in, ranked cards from other people's decks out.

Pulls EDHREC's aggregate of real decklists for a commander (inclusion %, synergy,
role), joins each card to its price and type from the local Scryfall bulk-data
database (card_db.py), and filters/ranks. The only network calls are EDHREC's
one page per commander and a daily bulk refresh. No LLM involved: this is the
deterministic baseline the deck-building agent has to beat.

Usage:
    python commander_lookup.py "Muldrotha, the Gravetide"
    python commander_lookup.py "Muldrotha" --max-price 5 --role "Mana Artifact"
    python commander_lookup.py "Atraxa, Praetors' Voice" --sort synergy --limit 25
    python commander_lookup.py thrasios --partner tymna
"""

import argparse
import json
import sys

import card_db
import edhrec_client

SORTS = ("inclusion", "synergy")
MIN_EDHREC_CARDS = 150  # fewer than this from EDHREC -> add staples in the commander's colors
STAPLE_POOL = 250


def resolve_commander(query, db, popularity=None):
    """Match a possibly-sloppy name to an exact card name using the local card database.

    An exact card name always wins. Otherwise cards that can be a commander are
    tried first (ties go to the commander EDHREC sees leading the most decks,
    ``popularity``; fetched and cached if not given), then any card, so a non-commander name still resolves and gets a
    clear "not a commander" error later.
    """
    exact = db.get(query)
    if exact:
        return exact["name"]
    popularity = edhrec_client.commander_popularity() if popularity is None else popularity
    name = db.find_commander(query, popularity=popularity) or db.find_name(query)
    if name is None:
        raise LookupError(f"No card matched '{query}'. Check the spelling.")
    return name


def resolve_pair(query, db, partner=None):
    """Commander card rows: ``[commander]`` or ``[commander, partner]``.

    ``partner`` is matched only among cards that can legally pair with the
    commander (a Background, a matching Partner, a Doctor...), so "giants" finds
    "Raised by Giants" for Halsin. Raises LookupError with the reason otherwise.
    """
    first = db.get(resolve_commander(query, db))
    if partner is None:
        if not card_db.can_be_commander(first):
            hint = " (a Background needs a commander with \"Choose a Background\")" \
                if ("background",) in card_db.pairing(first) else ""
            raise LookupError(f"{first['name']} can't be a commander on its own{hint}.")
        return [first]
    exact = db.get(partner)
    name = exact["name"] if exact else db.find_partner(first, partner)
    if name is None:
        options = db.partner_names(first)
        hint = f" Options include: {', '.join(options[:5])}." if options else f" {first['name']} has no partner ability."
        raise LookupError(f"No card that can pair with {first['name']} matched '{partner}'.{hint}")
    second = db.get(name)
    problem = card_db.pair_problem(first, second)
    if problem:
        raise LookupError(problem[0].upper() + problem[1:] + ".")
    if ("background",) in card_db.pairing(first):
        first, second = second, first  # the creature leads, the Background is second
    return [first, second]


def load_commanders(query, db, partner=None, owned=frozenset(), fetch=None):
    """Everything a builder needs about the commander(s), from one call.

    Returns ``{"commander", "cards", "commander_cost", "sources", "num_decks", "warnings"}``: the commander
    dict (combined for a pair, see ``card_db.combine_commanders``), EDHREC's
    cards for it, what the commander(s) cost you (owned ones are $0), and which
    EDHREC pages were used.
    """
    members = resolve_pair(query, db, partner)
    commander = card_db.combine_commanders(members)
    if not all(c["legal_commander"] for c in members):
        raise LookupError(f"{commander['name']} is not legal as a commander.")
    warnings = []
    try:
        data = edhrec_client.commander_cards([c["name"] for c in members], fetch)
    except edhrec_client.EdhrecError:
        # Brand-new or never-played commanders have no page: build from staples alone.
        data = {"commander": {"num_decks": 0, "legal_commander": True}, "cards": [], "sources": []}
        warnings.append(f"EDHREC has no data for {commander['name']} yet, so the deck uses popular cards "
                        "in these colors instead.")
    if not data["commander"]["legal_commander"]:
        raise LookupError(f"{commander['name']} is not legal as a commander.")
    cards = data["cards"]
    if len(cards) < MIN_EDHREC_CARDS:
        added = staple_cards(commander, db, {c["name"] for c in cards} | {m["name"] for m in members})
        if cards:
            warnings.append(f"EDHREC lists only {len(cards)} cards for {commander['name']}; "
                            f"{len(added)} popular cards in these colors were added as a fallback.")
        cards = cards + added
        data["sources"].append("staples")
    cost = sum(0.0 if c["name"] in owned else (c["usd"] or 0.0) for c in members)
    return {"commander": commander, "cards": cards, "commander_cost": round(cost, 2),
            "sources": data["sources"], "num_decks": data["commander"].get("num_decks", 0),
            "warnings": warnings}


def staple_cards(commander, db, skip=frozenset(), limit=STAPLE_POOL):
    """Most-played cards in the commander's colors (Scryfall's EDHREC rank), as
    EDHREC-style entries ranked below every real EDHREC card (inclusion 0.001-0.01)."""
    rows = [r for r in db.candidates(commander["color_identity"], limit=limit + len(skip))
            if r["name"] not in skip and r["name"] not in edhrec_client.BASIC_LANDS][:limit]
    return [{"name": r["name"], "role": None, "inclusion": round(0.01 - 0.009 * i / max(len(rows), 1), 5),
             "synergy": 0.0, "num_decks": 0, "potential_decks": 0, "high_synergy": False,
             "game_changer": bool(r["game_changer"]), "staple": True} for i, r in enumerate(rows)]


def role_from_type_line(type_line):
    """Fallback role for cards that only appear in EDHREC's cross-cut lists."""
    for kind in ("Creature", "Planeswalker", "Instant", "Sorcery", "Enchantment", "Artifact", "Land"):
        if kind in type_line:
            return kind
    return "Other"


def build_rows(cards, info_by_name):
    """Join EDHREC cards with Scryfall price/type info. Cards Scryfall can't find are dropped."""
    rows = []
    for card in cards:
        info = info_by_name.get(card["name"])
        if info is None:
            continue
        rows.append(
            {
                **card,
                "usd": info["usd"],
                "price_source": info["price_source"],
                "role": card["role"] or role_from_type_line(info["type_line"]),
            }
        )
    return rows


def rank_rows(
    rows,
    *,
    sort="inclusion",
    max_price=None,
    min_inclusion=0.0,
    role=None,
    limit=40,
    include_basics=False,
):
    """Filter and rank rows. Unpriced cards are excluded whenever max_price is set."""
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {SORTS}, got {sort!r}")

    kept = []
    for row in rows:
        if not include_basics and row["name"] in edhrec_client.BASIC_LANDS:
            continue
        if row["inclusion"] < min_inclusion:
            continue
        if role and row["role"].lower() != role.lower():
            continue
        if max_price is not None and (row["usd"] is None or row["usd"] > max_price):
            continue
        kept.append(row)

    kept.sort(key=lambda r: r[sort], reverse=True)
    return kept[:limit]


def format_table(commander, rows):
    """Render the ranked rows as a markdown report."""
    lines = [
        f"# {commander['name']} — top cards from {commander['num_decks']:,} decks"
        + (f" (EDHREC pages: {', '.join(commander['sources'])})" if len(commander.get("sources", [])) > 1 else ""),
        f"Color identity: {''.join(commander['color_identity']) or 'C'}",
        "",
        "| # | Card | Role | Inclusion | Synergy | Price | Notes |",
        "|--:|---|---|--:|--:|--:|---|",
    ]
    for i, row in enumerate(rows, 1):
        price = f"${row['usd']:.2f}" if row["usd"] is not None else "n/a"
        notes = ", ".join(
            n for n in ("game changer" if row["game_changer"] else "", "high synergy" if row["high_synergy"] else "") if n
        )
        lines.append(
            f"| {i} | {row['name']} | {row['role']} | {row['inclusion']:.0%} "
            f"| {row['synergy']:+.0%} | {price} | {notes} |"
        )
    priced = [r["usd"] for r in rows if r["usd"] is not None]
    lines += ["", f"Total for listed cards: ${sum(priced):.2f} ({len(rows) - len(priced)} unpriced)"]
    return "\n".join(lines)


def lookup(commander_query, db=None, partner=None, **rank_options):
    """Full lookup. Returns ``(commander_info, ranked_rows)``.

    ``db`` is an open ``card_db.CardDB``; if omitted, the local database is
    opened (and downloaded/refreshed if needed) and closed afterwards.
    """
    refresh = rank_options.pop("refresh", False)
    owns_db = db is None
    if owns_db:
        db = card_db.open_db(refresh=refresh)
    try:
        fetch = lambda slug: edhrec_client.fetch_commander_page(slug, refresh=refresh)  # noqa: E731
        loaded = load_commanders(commander_query, db, partner, fetch=fetch)
        commander = loaded["commander"]
        edhrec_only = [c for c in loaded["cards"] if not c.get("staple")]  # this report is EDHREC's data
        info = db.get_many([c["name"] for c in edhrec_only])
        rows = build_rows(edhrec_only, info)
        header = {"name": commander["name"], "color_identity": list(commander["color_identity"]),
                  "num_decks": loaded["num_decks"], "sources": loaded["sources"]}
        return header, rank_rows(rows, **rank_options)
    finally:
        if owns_db:
            db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("commander", help="commander card name (fuzzy match is fine)")
    parser.add_argument("--partner", help="second commander: a partner, Background, Doctor... (fuzzy)")
    parser.add_argument("--max-price", type=float, help="max USD per card")
    parser.add_argument("--min-inclusion", type=float, default=0.0, help="0-1, e.g. 0.25")
    parser.add_argument("--role", help='e.g. "Creature", "Mana Artifact", "Utility Land"')
    parser.add_argument("--sort", choices=SORTS, default="inclusion")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--include-basics", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="re-download card data and EDHREC page")
    parser.add_argument("--json", action="store_true", help="output JSON instead of a table")
    args = parser.parse_args(argv)

    try:
        commander, rows = lookup(
            args.commander,
            partner=args.partner,
            sort=args.sort,
            max_price=args.max_price,
            min_inclusion=args.min_inclusion,
            role=args.role,
            limit=args.limit,
            include_basics=args.include_basics,
            refresh=args.refresh,
        )
    except (LookupError, edhrec_client.EdhrecError, card_db.BulkDataError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"commander": commander, "cards": rows}, indent=2))
    else:
        print(format_table(commander, rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
