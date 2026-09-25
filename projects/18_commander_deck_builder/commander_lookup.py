"""Commander lookup: commander name in, ranked cards from other people's decks out.

Pulls EDHREC's aggregate of real decklists for a commander (inclusion %, synergy,
role), joins each card to its price and type from Scryfall, and filters/ranks.
No LLM involved: this is the deterministic baseline the deck-building agent
has to beat.

Usage:
    python commander_lookup.py "Muldrotha, the Gravetide"
    python commander_lookup.py "Muldrotha" --max-price 5 --role "Mana Artifact"
    python commander_lookup.py "Atraxa, Praetors' Voice" --sort synergy --limit 25
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse

import edhrec_client
import scryfall_prices

SORTS = ("inclusion", "synergy")


def resolve_commander(query):
    """Match a possibly-sloppy name to an exact card name via Scryfall fuzzy search."""
    url = f"{scryfall_prices.API}/cards/named?" + urllib.parse.urlencode({"fuzzy": query})
    try:
        card = scryfall_prices._request(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise LookupError(f"No card matched '{query}'. Check the spelling.") from exc
        raise
    return card["name"]


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
        f"# {commander['name']} — top cards from {commander['num_decks']:,} decks",
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


def lookup(commander_query, **rank_options):
    """Full lookup. Returns ``(commander_info, ranked_rows)``."""
    refresh = rank_options.pop("refresh", False)
    name = resolve_commander(commander_query)
    page = edhrec_client.fetch_commander_page(edhrec_client.slugify(name), refresh=refresh)
    parsed = edhrec_client.parse_commander_page(page)
    if not parsed["commander"]["legal_commander"]:
        raise LookupError(f"{name} is not legal as a commander.")

    info = scryfall_prices.lookup_cards([c["name"] for c in parsed["cards"]], refresh=refresh)
    rows = build_rows(parsed["cards"], info)
    return parsed["commander"], rank_rows(rows, **rank_options)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("commander", help="commander card name (fuzzy match is fine)")
    parser.add_argument("--max-price", type=float, help="max USD per card")
    parser.add_argument("--min-inclusion", type=float, default=0.0, help="0-1, e.g. 0.25")
    parser.add_argument("--role", help='e.g. "Creature", "Mana Artifact", "Utility Land"')
    parser.add_argument("--sort", choices=SORTS, default="inclusion")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--include-basics", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="ignore cached data")
    parser.add_argument("--json", action="store_true", help="output JSON instead of a table")
    args = parser.parse_args(argv)

    try:
        commander, rows = lookup(
            args.commander,
            sort=args.sort,
            max_price=args.max_price,
            min_inclusion=args.min_inclusion,
            role=args.role,
            limit=args.limit,
            include_basics=args.include_basics,
            refresh=args.refresh,
        )
    except (LookupError, edhrec_client.EdhrecError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"commander": commander, "cards": rows}, indent=2))
    else:
        print(format_table(commander, rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
