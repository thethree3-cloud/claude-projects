"""Your cards as money: binder value over time, risers you own, and a buy log.

- **Binder value:** the scanned collection (``collection.py``) priced with the
  daily snapshots. Owned cards are always snapshotted, even cheap ones.
- **Risers you own:** owned cards up 10%+ over 7 days (possible sells).
- **Buylist:** Card Kingdom's offer per card (from MTGJSON, see
  ``price_history.py``): what a store would actually pay today, no fees.
- **Buy log:** what you bought (date, quantity, price each) and, once sold,
  the sale price. Profit counts selling costs: ``FEE_RATE`` of the sale
  (TCGplayer-style ~13% marketplace + payment fees) plus ``SHIPPING`` per sale.
  "If sold now" uses today's price, which is a market price, not a buylist
  offer; stores pay less.

Stored in the watch list database (``data/watchlist.sqlite``).

CLI:
    python portfolio.py buy "Doubling Season" --qty 1 --price 28.50
    python portfolio.py sell 3 --price 40
    python portfolio.py list
    python portfolio.py binder
"""

import argparse
import datetime as dt
import sys

import card_db
import watchlist
from collection import Collection

FEE_RATE = 0.13  # marketplace + payment fees on a sale
SHIPPING = 1.00  # per sale (a stamped envelope for one card)
OWNED_RISE_PCT = 10.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS buys (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    oracle_id TEXT NOT NULL,
    bought_on TEXT NOT NULL,
    qty INTEGER NOT NULL CHECK (qty > 0),
    price_each REAL NOT NULL CHECK (price_each >= 0),
    note TEXT NOT NULL DEFAULT '',
    sold_on TEXT,
    sold_each REAL
);
"""


def net_sale(price_each, qty, fee_rate=FEE_RATE, shipping=SHIPPING):
    """What you keep from selling ``qty`` at ``price_each`` in one sale."""
    return round(price_each * qty * (1 - fee_rate) - shipping, 2)


class Portfolio:
    def __init__(self, wl):
        self.wl = wl
        self.conn = wl.conn
        self.conn.executescript(SCHEMA)

    # -- buy log ---------------------------------------------------------------

    def buy(self, db, name, qty, price_each, bought_on=None, note=""):
        card = db.get(name) or (db.get(db.find_name(name)) if db.find_name(name) else None)
        if card is None:
            raise LookupError(f"No card matched {name!r}.")
        if qty < 1 or price_each < 0:
            raise ValueError("Quantity must be 1 or more and the price 0 or more.")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO buys (name, oracle_id, bought_on, qty, price_each, note) VALUES (?, ?, ?, ?, ?, ?)",
                (card["name"], card["oracle_id"], bought_on or dt.date.today().isoformat(), qty, price_each, note))
        self.wl.set_tracked([card["oracle_id"]], "bought")
        return cur.lastrowid

    def sell(self, buy_id, sold_each, sold_on=None):
        with self.conn:
            return self.conn.execute("UPDATE buys SET sold_on = ?, sold_each = ? WHERE id = ? AND sold_on IS NULL",
                                     (sold_on or dt.date.today().isoformat(), sold_each, buy_id)).rowcount > 0

    def remove(self, buy_id):
        with self.conn:
            return self.conn.execute("DELETE FROM buys WHERE id = ?", (buy_id,)).rowcount > 0

    def positions(self, db, fee_rate=FEE_RATE, shipping=SHIPPING):
        """Every buy with cost, value now, what you'd keep if sold now, and profit
        (realized for sold rows, unrealized otherwise)."""
        rows = []
        for b in self.conn.execute("SELECT * FROM buys ORDER BY bought_on DESC, id DESC"):
            card = db.get(b["name"])
            now = card["usd"] if card else None
            cost = round(b["qty"] * b["price_each"], 2)
            if b["sold_on"]:
                kept = net_sale(b["sold_each"], b["qty"], fee_rate, shipping)
                row = {"status": "sold", "value_now": None, "if_sold_now": None, "kept": kept,
                       "profit": round(kept - cost, 2)}
            else:
                value = round(now * b["qty"], 2) if now is not None else None
                if_sold = net_sale(now, b["qty"], fee_rate, shipping) if now is not None else None
                row = {"status": "open", "value_now": value, "if_sold_now": if_sold, "kept": None,
                       "profit": round(if_sold - cost, 2) if if_sold is not None else None}
            offer = self.wl.buylist([b["oracle_id"]]).get(b["oracle_id"])
            row["buylist_now"] = round(offer[0] * b["qty"], 2) if offer and b["sold_on"] is None else None
            row["profit_buylist"] = round(row["buylist_now"] - cost, 2) if row["buylist_now"] is not None else None
            row.update({"id": b["id"], "name": b["name"], "bought_on": b["bought_on"], "qty": b["qty"],
                        "price_each": b["price_each"], "cost": cost, "usd_now": now, "note": b["note"],
                        "sold_on": b["sold_on"], "sold_each": b["sold_each"],
                        "profit_pct": round(row["profit"] / cost * 100, 1) if cost and row["profit"] is not None
                        else None})
            rows.append(row)
        return rows

    def summary(self, db, **kwargs):
        rows = self.positions(db, **kwargs)
        open_rows = [r for r in rows if r["status"] == "open"]
        return {
            "open_cost": round(sum(r["cost"] for r in open_rows), 2),
            "open_value": round(sum(r["value_now"] or 0 for r in open_rows), 2),
            "unrealized": round(sum(r["profit"] or 0 for r in open_rows), 2),
            "realized": round(sum(r["profit"] for r in rows if r["status"] == "sold"), 2),
            "open_buylist": round(sum(r["buylist_now"] or 0 for r in open_rows), 2),
            "rows": rows,
        }


# ---------------------------------------------------------------------------
# Binder value
# ---------------------------------------------------------------------------


def owned_cards(db, collection=None):
    """``[{name, oracle_id, qty, usd}]`` for the scanned collection (cards the DB knows)."""
    own = collection or Collection()
    try:
        cards = own.cards()
    finally:
        if collection is None:
            own.close()
    out = []
    for c in cards:
        card = db.get(c["card_name"])
        if card:
            out.append({"name": card["name"], "oracle_id": card["oracle_id"], "qty": c["quantity"],
                        "usd": card["usd"]})
    return out


def track_owned(db, wl, collection=None):
    """Make the daily snapshot cover every owned card, however cheap."""
    owned = owned_cards(db, collection)
    wl.set_tracked([c["oracle_id"] for c in owned], "owned")
    return owned


def binder_value(db, wl, collection=None, days=7):
    """Collection value now and per snapshot day, plus owned cards that rose.

    History counts a card on a day only if that day's snapshot has it (cheap
    owned cards are tracked from the day ``track_owned`` first ran)."""
    owned = owned_cards(db, collection)
    total = round(sum((c["usd"] or 0) * c["qty"] for c in owned), 2)
    by_day = {}
    for c in owned:
        for date, usd in wl.history(c["oracle_id"]):
            by_day[date] = by_day.get(date, 0) + usd * c["qty"]
    changes = wl.price_changes(days)
    risers = sorted(
        ({**c, "change_pct": changes[c["oracle_id"]]} for c in owned
         if changes.get(c["oracle_id"]) is not None and changes[c["oracle_id"]] >= OWNED_RISE_PCT),
        key=lambda c: -c["change_pct"])
    offers = wl.buylist([c["oracle_id"] for c in owned])
    for c in owned:
        c["buylist"] = offers.get(c["oracle_id"], (None, None))[0]
    buylist_total = round(sum((c["buylist"] or 0) * c["qty"] for c in owned), 2)
    top = sorted(owned, key=lambda c: -((c["usd"] or 0) * c["qty"]))[:10]
    return {"total": total, "buylist_total": buylist_total,
            "buylist_cards": sum(1 for c in owned if c["buylist"] is not None), "cards": len(owned), "copies": sum(c["qty"] for c in owned),
            "history": sorted((d, round(v, 2)) for d, v in by_day.items()), "risers": risers, "top": top}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Binder value and buy log.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_buy = sub.add_parser("buy")
    p_buy.add_argument("name")
    p_buy.add_argument("--qty", type=int, default=1)
    p_buy.add_argument("--price", type=float, required=True, help="price paid per copy (USD)")
    p_buy.add_argument("--date", help="YYYY-MM-DD (default today)")
    p_buy.add_argument("--note", default="")
    p_sell = sub.add_parser("sell")
    p_sell.add_argument("id", type=int)
    p_sell.add_argument("--price", type=float, required=True, help="sale price per copy (USD)")
    p_rm = sub.add_parser("remove")
    p_rm.add_argument("id", type=int)
    sub.add_parser("list")
    sub.add_parser("binder")
    args = parser.parse_args(argv)

    db = card_db.open_db(log=lambda m: print(m, file=sys.stderr))
    wl = watchlist.WatchList()
    pf = Portfolio(wl)
    try:
        if args.command == "buy":
            print(f"Logged buy #{pf.buy(db, args.name, args.qty, args.price, args.date, args.note)}.")
        elif args.command == "sell":
            print("Marked sold." if pf.sell(args.id, args.price) else f"No open buy #{args.id}.")
        elif args.command == "remove":
            print("Removed." if pf.remove(args.id) else f"No buy #{args.id}.")
        elif args.command == "list":
            s = pf.summary(db)
            for r in s["rows"]:
                profit = "n/a" if r["profit"] is None else f"{r['profit']:+.2f}"
                print(f"#{r['id']} {r['status']:4} {r['qty']}x {r['name']} @ ${r['price_each']:.2f} -> profit {profit}")
            print(f"Open: cost ${s['open_cost']:.2f}, value ${s['open_value']:.2f}, "
                  f"if sold ${s['unrealized']:+.2f}; realized ${s['realized']:+.2f} (after {FEE_RATE:.0%} fees "
                  f"+ ${SHIPPING:.2f} shipping per sale)")
        elif args.command == "binder":
            track_owned(db, wl)
            b = binder_value(db, wl)
            print(f"{b['cards']} cards ({b['copies']} copies) worth ${b['total']:.2f} today; Card Kingdom would "
                  f"pay ${b['buylist_total']:.2f} for the {b['buylist_cards']} it buys.")
            for c in b["top"]:
                print(f"  ${(c['usd'] or 0) * c['qty']:8.2f}  {c['qty']}x {c['name']}")
            for c in b["risers"]:
                print(f"  rising: {c['name']} {c['change_pct']:+.1f}% (7 days)")
    except (LookupError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        wl.close()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
