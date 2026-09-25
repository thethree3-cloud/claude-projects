"""Universal Commander staples: colorless + mono + two/three/four-color identities,
ranked by EDHREC popularity (``edhrec_rank``) and priced at the cheapest printing.

Reads the local card database (card_db.py, built from Scryfall bulk data), so
it makes no per-card API calls. The database refreshes itself daily.

Groups use exact identity, so a deck combines its own list with the lists of
every smaller identity inside it, plus colorless. Four-color groups hold only
2-12 cards (commanders and the Nephilim), so they add no staples of their own.

Writes staples/staples.json and staples/STAPLES.md.

Run:  python fetch_staples.py
"""

import json
from pathlib import Path

import card_db

OUT_DIR = Path(__file__).parent / "staples"
LIST_SIZE = 350  # cards kept per group
TABLE_DEPTH = 150  # how deep into each list the readable tables look

GROUPS = {
    "colorless": ("", "Colorless"),
    "w": ("W", "White"),
    "u": ("U", "Blue"),
    "b": ("B", "Black"),
    "r": ("R", "Red"),
    "g": ("G", "Green"),
    "wu": ("WU", "Azorius (WU)"),
    "ub": ("UB", "Dimir (UB)"),
    "br": ("BR", "Rakdos (BR)"),
    "rg": ("RG", "Gruul (RG)"),
    "gw": ("GW", "Selesnya (GW)"),
    "wb": ("WB", "Orzhov (WB)"),
    "ur": ("UR", "Izzet (UR)"),
    "bg": ("BG", "Golgari (BG)"),
    "rw": ("RW", "Boros (RW)"),
    "gu": ("GU", "Simic (GU)"),
    "wub": ("WUB", "Esper (WUB)"),
    "ubr": ("UBR", "Grixis (UBR)"),
    "brg": ("BRG", "Jund (BRG)"),
    "rgw": ("RGW", "Naya (RGW)"),
    "gwu": ("GWU", "Bant (GWU)"),
    "rwb": ("RWB", "Mardu (RWB)"),
    "gur": ("GUR", "Temur (GUR)"),
    "wbg": ("WBG", "Abzan (WBG)"),
    "urw": ("URW", "Jeskai (URW)"),
    "bgu": ("BGU", "Sultai (BGU)"),
    "wubr": ("WUBR", "Non-Green (WUBR)"),
    "ubrg": ("UBRG", "Non-White (UBRG)"),
    "brgw": ("BRGW", "Non-Blue (BRGW)"),
    "rgwu": ("RGWU", "Non-Black (RGWU)"),
    "gwub": ("GWUB", "Non-Red (GWUB)"),
}
TIERS = [("Under $2", 0, 2), ("$2-10", 2, 10), ("$10+", 10, float("inf"))]


def normalize_identity(colors):
    """Any order of color letters -> the database's WUBRG order ('' = colorless)."""
    return "".join(c for c in card_db.WUBRG if c in set(colors.upper()))


def build_group(db, identity):
    """Top cards with exactly this color identity, most popular first."""
    rows = db.conn.execute(
        "SELECT name, edhrec_rank, usd, type_line FROM cards "
        "WHERE color_identity = ? AND legal_commander = 1 AND edhrec_rank IS NOT NULL "
        "ORDER BY edhrec_rank LIMIT ?",
        (normalize_identity(identity), LIST_SIZE),
    ).fetchall()
    return [{"name": n, "rank": rank, "usd": usd, "type": type_line} for n, rank, usd, type_line in rows]


def render_markdown(data):
    lines = [
        "# Universal Commander staples",
        "",
        "Ranked by EDHREC popularity (Scryfall `edhrec_rank`), priced at the cheapest",
        "USD printing. Colorless cards fit any deck; mono-color cards fit any deck",
        "that includes that color. Legendary creatures are left out of these tables",
        "(they rank as commanders); they remain in staples.json.",
        "Regenerate with `python fetch_staples.py`.",
        "",
    ]
    for key, (_, label) in GROUPS.items():
        # Legendary creatures rank high as commanders, not as staples for other decks.
        priced = [
            r
            for r in data[key][:TABLE_DEPTH]
            if r["usd"] is not None
            and not ("Legendary" in r["type"] and "Creature" in r["type"])
        ]
        lines += [f"## {label}", "", "| Tier | Top cards (price) |", "|---|---|"]
        for tier, lo, hi in TIERS:
            picks = [r for r in priced if lo <= r["usd"] < hi][:8]
            cell = "; ".join(f"{r['name']} ${r['usd']:.2f}" for r in picks) or "-"
            lines.append(f"| {tier} | {cell} |")
        lines.append("")
    return "\n".join(lines)


def main():
    OUT_DIR.mkdir(exist_ok=True)
    db = card_db.open_db()
    try:
        data = {}
        for key, (identity, label) in GROUPS.items():
            data[key] = build_group(db, identity)
            print(f"{label}: {len(data[key])} cards")
    finally:
        db.close()
    (OUT_DIR / "staples.json").write_text(json.dumps(data, indent=1))
    (OUT_DIR / "STAPLES.md").write_text(render_markdown(data))
    print(f"Wrote {OUT_DIR}/staples.json and STAPLES.md")


if __name__ == "__main__":
    main()
