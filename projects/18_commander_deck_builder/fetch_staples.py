"""Fetch universal Commander staples: colorless + each mono color, ranked by
EDHREC popularity (via Scryfall's ``edhrec_rank``) and priced at the cheapest
USD printing.

Writes staples/staples.json and staples/STAPLES.md. Uses ~50 Scryfall requests
with a delay between each (Scryfall asks for < 10/sec and a User-Agent).

Why cheapest printing: Scryfall's default printing of some very popular cards
(Sol Ring, Command Tower, Arcane Signet) has no USD price, so a naive price
filter would silently drop them.

Run:  python fetch_staples.py
"""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

HEADERS = {"User-Agent": "commander-deck-builder/0.1", "Accept": "application/json"}
OUT_DIR = Path(__file__).parent / "staples"
PAGES = 2  # 175 cards per page
REPRICE_TOP = 150  # only reprice unpriced cards this deep into each list
DELAY = 0.5

GROUPS = {
    "colorless": ("id:c", "Colorless"),
    "w": ("id=w", "White"),
    "u": ("id=u", "Blue"),
    "b": ("id=b", "Black"),
    "r": ("id=r", "Red"),
    "g": ("id=g", "Green"),
}
TIERS = [("Under $2", 0, 2), ("$2-10", 2, 10), ("$10+", 10, float("inf"))]


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS)) as resp:
        return json.load(resp)


def search(query, unique="cards", pages=PAGES):
    params = {"q": query, "unique": unique, "order": "edhrec"}
    url = "https://api.scryfall.com/cards/search?" + urllib.parse.urlencode(params)
    cards = []
    for _ in range(pages):
        page = get(url)
        cards += page["data"]
        time.sleep(DELAY)
        if not page.get("has_more"):
            break
        url = page["next_page"]
    return cards


def default_usd(card):
    prices = card["prices"]
    usd = prices.get("usd") or prices.get("usd_foil") or prices.get("usd_etched")
    return float(usd) if usd else None


def cheapest_usd(name):
    """Lowest USD across every printing of a card, or None."""
    prints = search(f'!"{name}"', unique="prints", pages=1)
    prices = [float(p["prices"]["usd"]) for p in prints if p["prices"].get("usd")]
    return min(prices) if prices else None


def build_group(base_query):
    cards = search(f"f:commander -is:funny {base_query}")
    rows = [
        {
            "name": c["name"],
            "rank": c.get("edhrec_rank"),
            "usd": default_usd(c),
            "type": c["type_line"],
        }
        for c in cards
    ]
    for row in rows[:REPRICE_TOP]:
        if row["usd"] is None:
            row["usd"] = cheapest_usd(row["name"])
            row["repriced"] = True
            time.sleep(DELAY)
    return rows


def render_markdown(data):
    lines = [
        "# Universal Commander staples",
        "",
        "Ranked by EDHREC popularity (Scryfall `edhrec_rank`), priced at the cheapest",
        "USD printing. Colorless cards fit any deck; mono-color cards fit any deck",
        "that includes that color. Regenerate with `python fetch_staples.py`.",
        "",
    ]
    for key, (_, label) in GROUPS.items():
        priced = [r for r in data[key][:REPRICE_TOP] if r["usd"] is not None]
        lines += [f"## {label}", "", "| Tier | Top cards (price) |", "|---|---|"]
        for tier, lo, hi in TIERS:
            picks = [r for r in priced if lo <= r["usd"] < hi][:8]
            cell = "; ".join(f"{r['name']} ${r['usd']:.2f}" for r in picks) or "-"
            lines.append(f"| {tier} | {cell} |")
        lines.append("")
    return "\n".join(lines)


def main():
    OUT_DIR.mkdir(exist_ok=True)
    data = {}
    for key, (query, label) in GROUPS.items():
        data[key] = build_group(query)
        print(f"{label}: {len(data[key])} cards")
    (OUT_DIR / "staples.json").write_text(json.dumps(data, indent=1))
    (OUT_DIR / "STAPLES.md").write_text(render_markdown(data))
    print(f"Wrote {OUT_DIR}/staples.json and STAPLES.md")


if __name__ == "__main__":
    main()
