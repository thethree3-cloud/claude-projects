import gzip
import io
import json
import tempfile
import unittest
from pathlib import Path

import backtest
import card_db
import portfolio
import price_history
import watchlist
from test_card_db import printing, write_bulk


def setUpModule():
    from unittest import mock
    patcher = mock.patch("tournaments.card_play", return_value={})
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def gz_json(path, data):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump({"meta": {"date": "2026-11-19"}, "data": data}, f)


class StreamTests(unittest.TestCase):
    def test_streams_every_entry_across_chunk_edges(self):
        data = {f"id-{i}": {"v": i, "s": "x" * (i % 7), "nested": {"a": [1, 2, {"b": "}"}]}} for i in range(500)}
        text = json.dumps({"meta": {"date": "d", "note": 'has "data" text'}, "data": data})
        old = price_history.CHUNK
        try:
            price_history.CHUNK = 37  # tiny chunks: entries split across reads
            got = dict(price_history.stream_data(io.StringIO(text)))
        finally:
            price_history.CHUNK = old
        self.assertEqual(got, data)

    def test_empty_and_broken(self):
        self.assertEqual(list(price_history.stream_data(io.StringIO('{"meta": {}, "data": {}}'))), [])
        with self.assertRaises(price_history.HistoryError):
            list(price_history.stream_data(io.StringIO('{"meta": {}}')))
        with self.assertRaises(price_history.HistoryError):
            list(price_history.stream_data(io.StringIO('{"data": {"a": {"x": ')))


class BackfillTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        bulk = self.dir / "bulk.jsonl.gz"
        write_bulk(bulk, [
            printing("sol", "Sol Ring", released_at="2015-01-01", prices={"usd": "2.00"}),
            printing("bolt", "Lightning Bolt", released_at="2010-01-01", prices={"usd": "3.00"}),
            printing("penny", "Penny Card", prices={"usd": "0.05"}),
        ])
        card_db.build_db(bulk, self.dir / "cards.sqlite", updated_at="2026-11-19T00:00:00Z")
        self.db = card_db.CardDB(self.dir / "cards.sqlite")
        self.addCleanup(self.db.close)
        self.wl = watchlist.WatchList(self.dir / "watch.sqlite")
        self.addCleanup(self.wl.close)
        sol, bolt = self.db.get("Sol Ring")["oracle_id"], self.db.get("Lightning Bolt")["oracle_id"]
        gz_json(self.dir / "ids.json.gz", {
            "u-sol-a": {"identifiers": {"scryfallOracleId": sol}, "availability": ["paper"]},
            "u-sol-b": {"identifiers": {"scryfallOracleId": sol}, "availability": ["paper"]},
            "u-sol-promo": {"identifiers": {"scryfallOracleId": sol}, "isPromo": True},
            "u-bolt": {"identifiers": {"scryfallOracleId": bolt}},
            "u-bolt-mtgo": {"identifiers": {"scryfallOracleId": bolt}, "isOnlineOnly": True},
        })

        def paper(retail=None, buy=None, eur=None, foil=None):
            return {"paper": {"tcgplayer": {"retail": {"normal": retail or {}, "foil": foil or {}}},
                              "cardkingdom": {"buylist": {"normal": buy or {}}},
                              "cardmarket": {"retail": {"normal": eur or {}}}}}
        gz_json(self.dir / "prices.json.gz", {
            "u-sol-a": paper({"2026-11-01": 1.50, "2026-11-19": 2.10}, {"2026-11-01": 0.80, "2026-11-19": 1.00},
                             {"2026-11-01": 1.20}),
            "u-sol-b": paper({"2026-11-01": 1.40}, {"2026-11-01": 0.70}, {"2026-11-01": 1.30}),
            "u-sol-promo": paper({"2026-11-01": 0.10}),  # promo: ignored
            "u-bolt": paper({"2026-11-01": 3.00}, foil={"2026-11-01": 0.50}),  # foil price ignored
            "u-bolt-mtgo": paper({"2026-11-01": 0.01}),
        })
        self.sol, self.bolt = sol, bolt

    def test_map_and_daily_prices(self):
        mapping = price_history.id_map(self.dir / "ids.json.gz", {self.sol, self.bolt})
        self.assertEqual(mapping, {"u-sol-a": self.sol, "u-sol-b": self.sol, "u-bolt": self.bolt})
        prices = price_history.daily_prices(self.dir / "prices.json.gz", mapping)
        self.assertEqual(prices[(self.sol, "2026-11-01")], (1.40, 0.70, 1.20))  # cheapest printing + its buylist
        self.assertEqual(prices[(self.bolt, "2026-11-01")], (3.00, None, None))

    def test_backfill_replaces_scryfall_days_and_adds_buylist(self):
        self.wl.snapshot(self.db)  # Scryfall day 2026-11-19: Sol Ring $2.00
        res = price_history.backfill(self.db, self.wl, self.dir / "prices.json.gz", self.dir / "ids.json.gz",
                                     log=lambda *_: None)
        self.assertEqual((res["from"], res["to"], res["days"]), ("2026-11-01", "2026-11-19", 2))
        self.assertEqual(self.wl.dates(), ["2026-11-01", "2026-11-19"])
        # One source for the whole history: MTGJSON replaces the Scryfall day (2.00 -> 2.10).
        self.assertEqual(self.wl.history(self.sol), [("2026-11-01", 1.4), ("2026-11-19", 2.1)])
        penny = self.db.get("Penny Card")["oracle_id"]
        self.assertEqual(self.wl.history(penny), [])  # not in MTGJSON and not tracked
        self.assertEqual(self.wl.buylist([self.sol])[self.sol], (1.0, "2026-11-19"))  # buylist added
        self.assertEqual(self.wl.get_meta("backfilled"), "2026-11-01..2026-11-19")
        n_rows = self.wl.conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        price_history.backfill(self.db, self.wl, self.dir / "prices.json.gz", self.dir / "ids.json.gz",
                               log=lambda *_: None)
        self.assertEqual(self.wl.conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], n_rows)  # no duplicates

    def test_buylist_in_portfolio(self):
        price_history.backfill(self.db, self.wl, self.dir / "prices.json.gz", self.dir / "ids.json.gz",
                               log=lambda *_: None)
        pf = portfolio.Portfolio(self.wl)
        pf.buy(self.db, "Sol Ring", 3, 0.50)
        row = pf.positions(self.db)[0]
        self.assertEqual((row["buylist_now"], row["profit_buylist"]), (3.0, 1.5))
        self.assertEqual(pf.summary(self.db)["open_buylist"], 3.0)


class PatternTests(unittest.TestCase):
    def test_momentum_and_supply_groups(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        bulk = d / "bulk.jsonl.gz"
        write_bulk(bulk, [printing("a", "Jumper", released_at="2015-01-01", prices={"usd": "2.00"}),
                          printing("b", "Steady", released_at="2015-01-01", prices={"usd": "2.00"})])
        card_db.build_db(bulk, d / "cards.sqlite")
        db = card_db.CardDB(d / "cards.sqlite")
        self.addCleanup(db.close)
        wl = watchlist.WatchList(d / "w.sqlite")
        self.addCleanup(wl.close)
        a, b = db.get("Jumper")["oracle_id"], db.get("Steady")["oracle_id"]
        series = {a: {"2026-10-01": 2.0, "2026-10-08": 3.0, "2026-10-22": 2.4},   # up 50%, then falls 20%
                  b: {"2026-10-01": 2.0, "2026-10-08": 2.0, "2026-10-22": 2.2}}   # flat, then +10%
        with wl.conn:
            for oid, days in series.items():
                cid = wl._card_id(oid)
                for date, usd in days.items():
                    wl.conn.execute("INSERT INTO snapshots (day, card, cents) VALUES (?, ?, ?)",
                                    (watchlist._day(date), cid, round(usd * 100)))
        res = backtest.price_patterns(db, wl, horizon=14, lookback=7, today="2026-11-19")
        self.assertEqual(res["starts"], ["2026-10-08"])
        mom = {r["group"]: r for r in res["momentum"]}
        self.assertEqual(mom["up 30%+"]["mean"], -20.0)
        self.assertEqual(mom["flat (-10% to +10%)"]["mean"], 10.0)
        self.assertEqual(mom["flat (-10% to +10%)"]["hit_rate"], 100.0)
        self.assertEqual(res["supply"][0]["group"], "1 printing (out of print)")
        self.assertIn("up 30%+", backtest.format_patterns(res))
        self.assertIsNotNone(backtest.price_patterns(db, wl, horizon=60)["needed"])


if __name__ == "__main__":
    unittest.main()
