"""Build a 100-card Commander deck from plain code (no LLM): the baseline.

Candidates come from EDHREC's list for the commander, checked against the
local card database (Commander-legal, inside the color identity, priced).
Each card gets one job from its rules text (land, ramp, draw, removal, wipe,
or synergy), then slots are filled most-popular-first within the budget:

    nonbasic lands -> wipes -> removal -> ramp -> draw -> synergy -> basics

Budget: a card is affordable only if (1) after buying it, enough money is
left to fill every remaining slot at ``RESERVE_PER_SLOT``, and (2) it costs
at most ``FAIR_SHARE_MULT`` x the money left per open slot, so popular but
pricey cards early (lands are picked first) can't eat the whole budget.
Basic lands are free (everyone has them).

Upgrade pass (on by default, ``--no-upgrade`` to skip): the cap above leaves
some money unspent, so afterwards the builder swaps cards for more popular
ones in the same role while the leftover covers the price difference. The
best swap (biggest inclusion gain) goes first, repeated until none fit. Role
counts and land count never change; in owned mode your EDHREC-listed cards
are never swapped out.

Owned mode (``--owned``): cards in your collection cost $0 and are picked
first within each job. Owned cards that EDHREC doesn't list for this
commander are used only if the deck can't be filled otherwise.

Usage:
    python build_deck.py "Kestia, the Cultivator" --budget 100
    python build_deck.py kestia --budget 50 --owned
    python build_deck.py kestia --budget 50 --owned --binder "Born of the Gods" --out kestia.txt
"""

import argparse
import json
import re
import sys
from pathlib import Path

import card_db
import commander_lookup
import edhrec_client
from collection import Collection

DECK_SIZE = 100
LAND_TARGET = 37
# Minimums for the 62 spells (wipes exactly: extra wipes hurt your own board); the rest = best remaining.
ROLE_TARGETS = {"wipe": 2, "removal": 8, "ramp": 10, "draw": 10}
NONBASIC_BY_COLORS = {0: 5, 1: 5, 2: 10, 3: 15, 4: 17, 5: 20}
RESERVE_PER_SLOT = 0.25  # money kept back per unfilled slot so the budget can't run dry
FAIR_SHARE_MULT = 4  # one card may cost at most this many times the money left per open slot
BASIC_BY_COLOR = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
ROLES = ("land", "ramp", "draw", "removal", "wipe", "synergy")

_WIPE = re.compile(r"\b(destroy|exile) all\b|\ball (other )?creatures get -|\beach creature\b.*\b(destroy|damage)", re.I)
_REMOVAL = re.compile(
    r"\b(destroy|exile) (target|up to (one|two|three) target)|\bcounter target\b"
    r"|\bdeals? \w+ damage to (any target|target creature)|\btarget (creature|player)'?s?\b.*\bsacrifices?\b"
    # Removal auras: neutralize a creature instead of killing it.
    r"|\benchanted (creature|permanent)\b[^.]*\b(loses all (other )?abilities|can't attack or block|is a colorless land)",
    re.I,
)
_RAMP = re.compile(
    r"\badd (\{|one mana|two mana|three mana|x mana|mana)|\bsearch your library for (a|up to \w+) (basic )?(land|forest|plains|island|swamp|mountain)",
    re.I,
)
_DRAW = re.compile(r"\bdraws? (a|two|three|four|x|that many) cards?\b", re.I)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


def card_role(card):
    """One job per card, from type line and rules text. First match wins."""
    front_type = card["type_line"].split(" // ")[0]
    if "Land" in front_type:
        return "land"
    text = card["oracle_text"]
    for role, pattern in (("wipe", _WIPE), ("removal", _REMOVAL), ("ramp", _RAMP), ("draw", _DRAW)):
        if pattern.search(text):
            return role
    return "synergy"


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


def candidate_pool(commander, edhrec_cards, db, owned=frozenset()):
    """Legal, priced-or-owned cards for this commander, with role and cost.

    EDHREC-listed cards come first (``listed=True``). Owned legal cards that
    EDHREC doesn't list are added with ``listed=False`` as a last resort.
    """
    identity = commander["color_identity"]
    pool, seen = [], {commander["name"]}

    def add(card, inclusion, listed):
        if card is None or card["name"] in seen or card["name"] in edhrec_client.BASIC_LANDS:
            return
        if not card["legal_commander"] or not card_db.identity_fits(card["color_identity"], identity):
            return
        is_owned = card["name"] in owned
        if card["usd"] is None and not is_owned:
            return  # can't price it, can't budget it
        seen.add(card["name"])
        pool.append({
            "name": card["name"],
            "role": card_role(card),
            "inclusion": inclusion,
            "usd": card["usd"],
            "owned": is_owned,
            "cost": 0.0 if is_owned else card["usd"],
            "color_identity": card["color_identity"],
            "listed": listed,
        })

    info = db.get_many([c["name"] for c in edhrec_cards])
    for c in edhrec_cards:
        add(info.get(c["name"]), c["inclusion"], True)
    for name in sorted(owned):
        add(db.get(name), 0.0, False)
    return pool


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _basics_split(identity, spells, count):
    """Split ``count`` basics by how many chosen spells use each color (largest remainder)."""
    if not identity:
        return {"Wastes": count} if count else {}
    weight = {c: 1 + sum(c in s["color_identity"] for s in spells) for c in identity}
    total = sum(weight.values())
    shares = {c: count * w / total for c, w in weight.items()}
    split = {c: int(s) for c, s in shares.items()}
    for c in sorted(shares, key=lambda c: shares[c] - split[c], reverse=True)[: count - sum(split.values())]:
        split[c] += 1
    return {BASIC_BY_COLOR[c]: n for c, n in split.items() if n}


def upgrade_pass(chosen, pool, leftover, owned_mode=False):
    """Swap chosen cards for more popular same-role cards using leftover money.

    Mutates ``chosen``. Returns the swaps made, best first:
    ``[{"out": name, "in": name, "role": ..., "gain": float, "extra": float}]``.
    """
    swaps = []
    while True:
        names = {c["name"] for c in chosen}
        best = None
        for out in chosen:
            if owned_mode and out["owned"] and out["listed"]:
                continue  # never trade away a card you own that the commander wants
            for new in pool:
                if new["name"] in names or not new["listed"] or new["role"] != out["role"]:
                    continue
                gain = new["inclusion"] - out["inclusion"]
                extra = new["cost"] - out["cost"]
                if gain <= 0 or extra > leftover + 1e-9:
                    continue
                key = (gain, -extra)
                if best is None or key > best[0]:
                    best = (key, out, new)
        if best is None:
            return swaps
        _, out, new = best
        chosen[chosen.index(out)] = new
        leftover -= new["cost"] - out["cost"]
        swaps.append({"out": out["name"], "in": new["name"], "role": new["role"],
                      "gain": round(new["inclusion"] - out["inclusion"], 4),
                      "extra": round(new["cost"] - out["cost"], 2)})


def build_deck(commander, pool, budget, owned_mode=False, upgrade=True):
    """Pick 99 cards. Returns ``{"cards", "basics", "warnings", "spent", "upgrades"}``."""
    identity = commander["color_identity"]
    nonbasic_target = min(NONBASIC_BY_COLORS[len(identity)], LAND_TARGET)
    spell_target = DECK_SIZE - 1 - LAND_TARGET
    chosen, warnings = [], []
    spent = 0.0

    def rank(cards):
        # Owned-and-listed first in owned mode, then by popularity; unlisted owned cards last.
        return sorted(cards, key=lambda c: (not c["listed"], not (owned_mode and c["owned"]), -c["inclusion"], c["name"]))

    def open_paid_slots():
        # Basics are free, so only nonbasic land + spell slots need money kept back.
        lands = sum(c["role"] == "land" for c in chosen)
        spells = len(chosen) - lands
        return max(nonbasic_target - lands, 0) + max(spell_target - spells, 0)

    def take(cards, limit, listed_only=True):
        nonlocal spent
        taken = 0
        for c in rank(cards):
            if taken >= limit:
                break
            if c in chosen or (listed_only and not c["listed"]):
                continue
            if c["cost"]:
                left, slots = budget - spent, open_paid_slots()
                if c["cost"] > left - RESERVE_PER_SLOT * (slots - 1) or c["cost"] > FAIR_SHARE_MULT * left / slots:
                    continue
            chosen.append(c)
            spent += c["cost"]
            taken += 1
        return taken

    take([c for c in pool if c["role"] == "land"], nonbasic_target)
    for role, target in ROLE_TARGETS.items():
        got = take([c for c in pool if c["role"] == role], target)
        if got < target:
            warnings.append(f"Only {got} of {target} {role} cards fit (pool or budget).")

    def spells():
        return [c for c in chosen if c["role"] != "land"]

    fill = [c for c in pool if c["role"] not in ("land", "wipe")]
    take(fill, spell_target - len(spells()))

    short = spell_target - len(spells())
    if short and owned_mode:
        added = take(fill, short, listed_only=False)
        if added:
            warnings.append(f"{added} owned cards that EDHREC doesn't list for this commander were used to fill the deck.")
        short -= added
    if short:
        warnings.append(f"{short} spell slots couldn't be filled within budget; extra basic lands used instead.")

    upgrades = upgrade_pass(chosen, pool, budget - spent, owned_mode) if upgrade else []
    spent += sum(u["extra"] for u in upgrades)

    basics_count = DECK_SIZE - 1 - len(chosen)
    return {
        "cards": chosen,
        "basics": _basics_split(identity, spells(), basics_count),
        "warnings": warnings,
        "spent": round(spent, 2),
        "upgrades": upgrades,
    }


def check_deck(commander, deck, budget):
    """Quick sanity checks (the full validator is Slice 4). Returns a list of problems."""
    names = [c["name"] for c in deck["cards"]]
    problems = []
    total = 1 + len(names) + sum(deck["basics"].values())
    if total != DECK_SIZE:
        problems.append(f"deck has {total} cards, not {DECK_SIZE}")
    if len(set(names)) != len(names) or commander["name"] in names:
        problems.append("a card appears more than once")
    if any(not card_db.identity_fits(c["color_identity"], commander["color_identity"]) for c in deck["cards"]):
        problems.append("a card is outside the color identity")
    if deck["spent"] > budget + 1e-9:
        problems.append(f"spent ${deck['spent']:.2f}, over the ${budget:.2f} budget")
    return problems


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def import_text(commander, deck):
    """Moxfield / Archidekt import format: '1 Card Name' per line, commander first."""
    lines = [f"1 {commander['name']}"]
    lines += [f"1 {c['name']}" for c in sorted(deck["cards"], key=lambda c: c["name"])]
    lines += [f"{n} {name}" for name, n in sorted(deck["basics"].items())]
    return "\n".join(lines)


def format_report(commander, deck, budget, owned_mode):
    cards = deck["cards"]
    owned = [c for c in cards if c["owned"]]
    lines = [
        f"# {commander['name']} - ${budget:.0f} budget{' (using your cards)' if owned_mode else ''}",
        "",
        f"Cost to buy: ${deck['spent']:.2f} of ${budget:.2f}.",
    ]
    if owned_mode:
        value = sum(c["usd"] or 0 for c in owned)
        lines.append(f"From your collection: {len(owned)} cards (${value:.2f} you don't have to buy).")
    lines.append(f"Basic lands (free): {', '.join(f'{n} {b}' for b, n in sorted(deck['basics'].items()))}.")
    for w in deck["warnings"]:
        lines.append(f"Note: {w}")
    if deck.get("upgrades"):
        lines += ["", f"## Upgrades with leftover money ({len(deck['upgrades'])})", ""]
        for u in deck["upgrades"]:
            lines.append(f"- {u['in']} replaces {u['out']} ({u['role']}, +{u['gain']:.0%} inclusion, {u['extra']:+.2f} USD)")

    for role in ROLES:
        group = [c for c in cards if c["role"] == role]
        if not group:
            continue
        lines += ["", f"## {role.capitalize()} ({len(group)})", ""]
        for c in sorted(group, key=lambda c: -c["inclusion"]):
            price = "owned" if c["owned"] else f"${c['usd']:.2f}"
            inc = f"{c['inclusion']:.0%}" if c["listed"] else "not on EDHREC list"
            lines.append(f"- {c['name']} ({inc}, {price})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a Commander deck within a budget (no LLM).")
    parser.add_argument("commander", help="commander name (fuzzy match is fine)")
    parser.add_argument("--budget", type=float, required=True, help="max USD to spend on cards you don't own")
    parser.add_argument("--owned", action="store_true", help="use cards from your collection first ($0)")
    parser.add_argument("--binder", help="with --owned: only this binder")
    parser.add_argument("--no-upgrade", action="store_true", help="skip the leftover-money upgrade pass")
    parser.add_argument("--out", type=Path, help="write the import list to this file")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.budget < 0:
        parser.error("--budget must be 0 or more")

    owned = set()
    if args.owned:
        col = Collection()
        try:
            owned = col.names(binder=args.binder)
        finally:
            col.close()
        if not owned:
            print("Note: your collection is empty, so nothing is owned.", file=sys.stderr)

    try:
        db = card_db.open_db()
        commander = db.get(commander_lookup.resolve_commander(args.commander, db))
        page = edhrec_client.parse_commander_page(
            edhrec_client.fetch_commander_page(edhrec_client.slugify(commander["name"]))
        )
        if not page["commander"]["legal_commander"]:
            raise LookupError(f"{commander['name']} is not legal as a commander.")
    except (LookupError, edhrec_client.EdhrecError, card_db.BulkDataError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    pool = candidate_pool(commander, page["cards"], db, owned)
    deck = build_deck(commander, pool, args.budget, owned_mode=args.owned, upgrade=not args.no_upgrade)
    problems = check_deck(commander, deck, args.budget)
    if problems:
        print("Error: built deck failed checks: " + "; ".join(problems), file=sys.stderr)
        return 1

    text = import_text(commander, deck)
    if args.out:
        args.out.write_text(text + "\n")
    if args.json:
        print(json.dumps({"commander": commander["name"], "budget": args.budget, **deck}, indent=2))
    else:
        print(format_report(commander, deck, args.budget, args.owned))
        if args.out:
            print(f"\nImport list written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
