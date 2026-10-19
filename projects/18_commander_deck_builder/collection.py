"""Owned-card collection: which cards you have and where they live.

Kept in its own SQLite file (``data/collection.sqlite``, gitignored) because
the card database is rebuilt from Scryfall every day and this must survive.

One row per binder pocket (binder, page, slot). Saving a scanned page
replaces whatever was stored for that page, so re-scanning never
double-counts. Quantity starts at 1: a photo only shows the front card of a
pocket, so copies stacked behind it are set by hand (``set-qty``).

Usage:
    python collection.py list                     # every card, total copies
    python collection.py find "Courser of Kruphix"
    python collection.py binders
    python collection.py set-qty "Born of the Gods" 5 2 4   # binder page slot qty
    python collection.py remove-page "Born of the Gods" 5
"""

import argparse
import sqlite3
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DB_NAME = "collection.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS owned (
    binder TEXT NOT NULL,
    page INTEGER NOT NULL,
    slot INTEGER NOT NULL,
    card_name TEXT NOT NULL,         -- exact name from the card database
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    source_image TEXT,               -- photo the card was scanned from
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (binder, page, slot)
);
CREATE INDEX IF NOT EXISTS idx_owned_name ON owned(card_name COLLATE NOCASE);
"""


class Collection:
    def __init__(self, path=None):
        self.path = Path(path) if path else DATA_DIR / DB_NAME
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    def save_page(self, binder, page, cards, source_image=None):
        """Store a scanned page, replacing anything saved for it before.

        ``cards`` are ``scan_binder.match_names`` results. Cards without a
        confirmed name (status ``unknown``) are skipped and returned.
        """
        saved, skipped = [], []
        with self.conn:
            self.conn.execute("DELETE FROM owned WHERE binder = ? AND page = ?", (binder, page))
            for card in cards:
                if not card.get("name"):
                    skipped.append(card)
                    continue
                self.conn.execute(
                    "INSERT INTO owned (binder, page, slot, card_name, source_image) VALUES (?, ?, ?, ?, ?)",
                    (binder, page, card["slot"], card["name"], source_image),
                )
                saved.append(card["name"])
        return {"saved": saved, "skipped": skipped}

    def remove_page(self, binder, page):
        with self.conn:
            return self.conn.execute("DELETE FROM owned WHERE binder = ? AND page = ?", (binder, page)).rowcount

    def set_quantity(self, binder, page, slot, quantity):
        """Set the copies in one pocket. Returns False if the pocket is empty."""
        if quantity < 1:
            raise ValueError("quantity must be at least 1 (use remove-page to clear a page)")
        with self.conn:
            cur = self.conn.execute(
                "UPDATE owned SET quantity = ? WHERE binder = ? AND page = ? AND slot = ?",
                (quantity, binder, page, slot),
            )
        return cur.rowcount == 1

    def cards(self):
        """``[{card_name, quantity}]`` totalled across all pockets, A-Z."""
        rows = self.conn.execute(
            "SELECT card_name, SUM(quantity) AS quantity FROM owned GROUP BY card_name ORDER BY card_name"
        )
        return [dict(r) for r in rows]

    def names(self):
        """Set of owned card names (the deck builder's owned pool)."""
        return {r[0] for r in self.conn.execute("SELECT DISTINCT card_name FROM owned")}

    def find(self, name):
        """Every pocket holding a card, matched case-insensitively."""
        rows = self.conn.execute(
            "SELECT binder, page, slot, card_name, quantity FROM owned "
            "WHERE card_name = ? COLLATE NOCASE ORDER BY binder, page, slot",
            (name,),
        )
        return [dict(r) for r in rows]

    def binders(self):
        """``[{binder, pages, cards}]`` where cards counts copies."""
        rows = self.conn.execute(
            "SELECT binder, COUNT(DISTINCT page) AS pages, SUM(quantity) AS cards "
            "FROM owned GROUP BY binder ORDER BY binder"
        )
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description="Your owned-card collection.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="every card with total copies")
    sub.add_parser("binders", help="pages and card counts per binder")
    find = sub.add_parser("find", help="where a card is stored")
    find.add_argument("name")
    qty = sub.add_parser("set-qty", help="set the copies in one pocket")
    qty.add_argument("binder")
    qty.add_argument("page", type=int)
    qty.add_argument("slot", type=int)
    qty.add_argument("quantity", type=int)
    rm = sub.add_parser("remove-page", help="forget one page")
    rm.add_argument("binder")
    rm.add_argument("page", type=int)
    args = parser.parse_args(argv)

    col = Collection()
    try:
        if args.command == "list":
            cards = col.cards()
            for c in cards:
                print(f"{c['quantity']:>3}  {c['card_name']}")
            print(f"\n{len(cards)} different cards, {sum(c['quantity'] for c in cards)} copies")
        elif args.command == "binders":
            for b in col.binders():
                print(f"{b['binder']}: {b['pages']} pages, {b['cards']} cards")
        elif args.command == "find":
            hits = col.find(args.name)
            if not hits:
                print(f"'{args.name}' is not in your collection.")
            for h in hits:
                print(f"{h['card_name']}: {h['binder']}, page {h['page']}, slot {h['slot']} (x{h['quantity']})")
        elif args.command == "set-qty":
            try:
                ok = col.set_quantity(args.binder, args.page, args.slot, args.quantity)
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
            if not ok:
                print(f"Nothing saved in {args.binder}, page {args.page}, slot {args.slot}.", file=sys.stderr)
                return 1
            print("Updated.")
        elif args.command == "remove-page":
            print(f"Removed {col.remove_page(args.binder, args.page)} cards.")
    finally:
        col.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
