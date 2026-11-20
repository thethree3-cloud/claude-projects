import json
import tempfile
import unittest
from pathlib import Path

import card_db
import edhrec_client
import watchlist
from test_card_db import printing, write_bulk


def view(name, num, potential, z=None):
    return {"name": name, "num_decks": num, "potential_decks": potential, "trend_zscore": z}


def setUpModule():
    """Keep tests independent of tournaments saved on this machine."""
    from unittest import mock as _mock
    patcher = _mock.patch("tournaments.card_play", return_value={})
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)
    patcher = _mock.patch("archidekt.card_trend", return_value={})
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


class FetchTopTests(unittest.TestCase):
    def test_pages_are_followed_and_cached(self):
        pages = {
            "top/week": {"container": {"json_dict": {"cardlists": [
                {"cardviews": [{"name": "A", "num_decks": 5, "potential_decks": 10, "trend_zscore": 1.5}],
                 "more": "top/week-pastweek-1.json"}]}}},
            "top/week-pastweek-1": {"cardviews": [{"name": "B", "num_decks": 1, "potential_decks": 10}],
                                    "more": None},
        }
        calls = []

        def get(path):
            calls.append(path)
            return pages[path]
        with tempfile.TemporaryDirectory() as tmp:
            got = watchlist.fetch_top("week", pages=5, cache_dir=tmp, get=get)
            self.assertEqual([v["name"] for v in got], ["A", "B"])
            self.assertEqual(got[0]["trend_zscore"], 1.5)
            self.assertEqual(calls, ["top/week", "top/week-pastweek-1"])
            watchlist.fetch_top("week", pages=5, cache_dir=tmp, get=lambda p: self.fail("not cached"))

    def test_bad_shape_raises(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(edhrec_client.EdhrecError):
            watchlist.fetch_top("week", cache_dir=tmp, get=lambda p: {"container": {"json_dict": {}}})


class WatchCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        bulk = self.dir / "bulk.jsonl.gz"
        write_bulk(bulk, [
            printing("ring", "The One Ring", color_identity=[], prices={"usd": "100.00"}),
            printing("sol", "Sol Ring", prices={"usd": "1.50"}),
            printing("bolt", "Lightning Bolt", color_identity=["R"], prices={"usd": "2.00"}),
            printing("penny", "Penny Card", prices={"usd": "0.10"}),
        ])
        card_db.build_db(bulk, self.dir / "cards.sqlite", updated_at="2026-11-01T00:00:00Z")
        self.db = card_db.CardDB(self.dir / "cards.sqlite")
        self.addCleanup(self.db.close)
        self.wl = watchlist.WatchList(self.dir / "watch.sqlite")
        self.addCleanup(self.wl.close)

    def next_day(self, date, **prices):
        """Pretend Scryfall's next daily file arrived with new prices."""
        with self.db.conn:
            self.db.conn.execute("UPDATE meta SET value = ? WHERE key = 'updated_at'", (f"{date}T00:00:00Z",))
            for name, usd in prices.items():
                self.db.conn.execute("UPDATE cards SET usd = ? WHERE name = ?", (usd, name.replace("_", " ")))
        return self.wl.snapshot(self.db)


class RisingTests(WatchCase):
    def test_rising_order_inclusion_and_new_arrivals(self):
        week = [view("Sol Ring", 90, 100, -0.1), view("Lightning Bolt", 30, 100, 4.0), view("Spoiler", 5, 50, 9.0)]
        year = [view("Sol Ring", 85, 100), view("Lightning Bolt", 20, 100)]
        rows = watchlist.rising_cards(self.db, week, year)
        self.assertEqual([r["name"] for r in rows], ["Spoiler", "Lightning Bolt", "Sol Ring"])  # by trend
        bolt = rows[1]
        self.assertEqual((bolt["change_pts"], bolt["new"], bolt["usd"], bolt["week_rank"]), (10.0, False, 2.0, 2))
        spoiler = rows[0]
        self.assertTrue(spoiler["new"])
        self.assertIsNone(spoiler["usd"])  # not in the card database yet
        self.assertAlmostEqual(spoiler["week_inclusion"], 0.1)


class SnapshotTests(WatchCase):
    def test_once_per_day_and_cheap_cards_skipped(self):
        self.assertEqual(self.wl.snapshot(self.db), ("2026-11-01", True))
        self.assertEqual(self.wl.snapshot(self.db), ("2026-11-01", False))
        ring = self.db.get("The One Ring")["oracle_id"]
        penny = self.db.get("Penny Card")["oracle_id"]
        self.assertEqual(self.wl.history(ring), [("2026-11-01", 100.0)])
        self.assertEqual(self.wl.history(penny), [])  # under MIN_TRACK_USD

    def test_price_risers_need_two_days(self):
        self.wl.snapshot(self.db)
        self.assertEqual(self.wl.price_risers(self.db)["rows"], [])
        self.next_day("2026-11-05", Sol_Ring=3.00, Lightning_Bolt=2.20, The_One_Ring=90.0)
        found = self.wl.price_risers(self.db, days=7, min_usd=1.0)
        self.assertEqual((found["from"], found["to"]), ("2026-11-01", "2026-11-05"))  # history shorter than 7 days
        self.assertEqual([(r["name"], r["change_pct"]) for r in found["rows"]],
                         [("Sol Ring", 100.0), ("Lightning Bolt", 10.0)])  # the falling Ring is left out
        self.assertEqual(self.wl.price_risers(self.db, min_usd=2.5)["rows"][0]["name"], "Sol Ring")

    def test_old_snapshots_pruned_except_watched(self):
        self.wl.snapshot(self.db)
        self.wl.add(self.db, "sol ring")
        self.next_day("2026-12-31")
        self.next_day("2027-06-01")  # > KEEP_DAYS after the first two
        ring = self.db.get("The One Ring")["oracle_id"]
        sol = self.db.get("Sol Ring")["oracle_id"]
        self.assertEqual([d for d, _ in self.wl.history(ring)], ["2027-06-01"])
        self.assertEqual(len(self.wl.history(sol)), 3)  # watched: kept for good


class WatchedTests(WatchCase):
    def test_add_remove_and_changes(self):
        self.wl.snapshot(self.db)
        self.assertEqual(self.wl.add(self.db, "penny card", note="cheap"), "Penny Card")
        self.assertTrue(self.wl.is_watched("Penny Card"))
        penny = self.db.get("Penny Card")["oracle_id"]
        self.assertEqual(self.wl.history(penny), [("2026-11-01", 0.1)])  # history starts at once when watched
        self.wl.add(self.db, "Lightning Bolt")
        self.next_day("2026-11-09", Lightning_Bolt=3.00, Penny_Card=0.20)
        rising = [{"name": "Lightning Bolt", "trend": 4.0, "week_inclusion": 0.3}]
        rows = {r["name"]: r for r in self.wl.watched(self.db, rising)}
        bolt = rows["Lightning Bolt"]
        self.assertEqual((bolt["usd"], bolt["change_7d_pct"], bolt["since_added_pct"], bolt["trend"]),
                         (3.0, 50.0, 50.0, 4.0))
        self.assertIsNone(bolt["change_30d_pct"])  # no snapshot 30 days back
        self.assertEqual(rows["Penny Card"]["change_7d_pct"], 100.0)  # tracked although under MIN_TRACK_USD
        self.assertEqual(rows["Penny Card"]["note"], "cheap")
        self.assertTrue(self.wl.remove("Penny Card"))
        self.assertFalse(self.wl.remove("Penny Card"))
        with self.assertRaises(LookupError):
            self.wl.add(self.db, "zzzzqqq")



class SupplyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bulk = Path(tmp.name) / "bulk.jsonl.gz"
        write_bulk(bulk, [
            printing("old", "Old Gem", set="aaa", released_at="2015-01-01", prices={"usd": "3.00"}),
            printing("rl", "Reserved Thing", set="bbb", released_at="1995-01-01", reserved=True,
                     prices={"usd": "50.00"}),
            printing("rep", "Reprinted Soon", set="ccc", released_at="2018-01-01", prices={"usd": "4.00"}),
            printing("rep", "Reprinted Soon", set="zzz", set_name="Future Set", released_at="2027-02-01"),
            printing("many", "Common Staple", set="d1", released_at="2010-01-01", prices={"usd": "1.00"}),
            *[printing("many", "Common Staple", set=f"d{i}", released_at=f"201{i}-01-01") for i in range(2, 10)],
            printing("many", "Common Staple", set="p1", promo=True, released_at="2019-05-01"),
            printing("fresh", "Fresh Card", set="new", released_at="2026-11-10", prices={"usd": "2.00"}),
            printing("inp", "In Print Card", set="ipr", released_at="2026-06-01", prices={"usd": "2.00"}),
        ])
        card_db.build_db(bulk, Path(tmp.name) / "cards.sqlite")
        self.db = card_db.CardDB(Path(tmp.name) / "cards.sqlite")
        self.addCleanup(self.db.close)
        self.today = "2026-11-19"
        self.sup = self.db.supply(["Old Gem", "Reserved Thing", "Reprinted Soon", "Common Staple", "Fresh Card",
                                   "In Print Card", "Nope"], self.today)

    def test_supply_facts(self):
        self.assertNotIn("Nope", self.sup)
        self.assertEqual(self.sup["Common Staple"]["printings"], 9)  # the promo is counted apart
        self.assertEqual(self.sup["Common Staple"]["promos"], 1)
        self.assertTrue(self.sup["Reserved Thing"]["reserved"])
        self.assertEqual(self.sup["Reprinted Soon"]["upcoming"], ["Future Set"])
        self.assertEqual(self.sup["Reprinted Soon"]["last"], "2018-01-01")  # future printing isn't out yet

    def test_supply_factor_order(self):
        f = {n: watchlist.supply_factor(v, self.today) for n, v in self.sup.items()}
        self.assertEqual(f["Reserved Thing"], (1.1, "Reserved List"))
        self.assertEqual(f["Reprinted Soon"][0], 0.7)
        self.assertIn("reprint coming: Future Set", f["Reprinted Soon"][1])
        self.assertEqual(f["Old Gem"], (1.0, "1 printing, last 2015"))
        self.assertEqual(f["Common Staple"][0], 1.0)
        self.assertEqual(f["In Print Card"][0], 0.75)  # the backtest's clearest pattern
        self.assertIn("in print", f["In Print Card"][1])

    def test_price_factor(self):
        self.assertEqual(watchlist.price_factor(None)[0], 1.0)
        self.assertEqual(watchlist.price_factor(5)[0], 1.0)
        self.assertEqual(watchlist.price_factor(20)[0], 0.8)
        self.assertEqual(watchlist.price_factor(80), (0.5, "price already up +80%"))
        self.assertEqual(watchlist.price_factor(-20), (0.8, "price falling (-20%)"))

    def test_spec_signals(self):
        wl = watchlist.WatchList(Path(self.db.path).with_name("w.sqlite"))
        self.addCleanup(wl.close)
        rising = [
            {"name": n, "trend": t, "usd": u, "new": False, "change_pts": 1.0}
            for n, t, u in [("Old Gem", 5.0, 3.0), ("Common Staple", 6.0, 1.0), ("Reprinted Soon", 9.0, 4.0),
                            ("Fresh Card", 20.0, 2.0), ("Reserved Thing", 2.0, 50.0), ("Falling", -1.0, 3.0),
                            ("Penny", 4.0, 0.1)]
        ]
        rows = watchlist.spec_signals(self.db, wl, rising, today=self.today)
        names = [r["name"] for r in rows]
        self.assertNotIn("Fresh Card", names)   # new-set hype hidden by default
        self.assertNotIn("Falling", names)      # trend <= 0
        self.assertNotIn("Penny", names)        # under min price
        self.assertEqual(names[:3], ["Reprinted Soon", "Common Staple", "Old Gem"])  # 9 x 0.7, 6 x 1.0, 5 x 1.0
        self.assertEqual(rows[0]["score"], 6.3)
        self.assertIn("1 printing, last 2015", rows[2]["reasons"])
        self.assertIn("Fresh Card", [r["name"] for r in watchlist.spec_signals(
            self.db, wl, rising, include_new=True, today=self.today)])
        oop = [r["name"] for r in watchlist.spec_signals(self.db, wl, rising, today=self.today,
                                                          out_of_print_only=True)]
        self.assertNotIn("Reprinted Soon", oop)  # reprint on the way
        self.assertIn("Old Gem", oop)
        self.assertEqual(watchlist.spec_signals(self.db, wl, rising, max_usd=2, today=self.today)[0]["name"],
                         "Common Staple")


class PopularityHistoryTests(WatchCase):
    def test_edhrec_snapshot_and_change(self):
        week1 = [view("Sol Ring", 80, 100, 0.5), view("Lightning Bolt", 10, 100, 2.0)]
        week2 = [view("Sol Ring", 81, 100, 0.4), view("Lightning Bolt", 14, 100, 3.0)]
        self.assertTrue(self.wl.snapshot_edhrec(week1, date="2026-11-01"))
        self.assertFalse(self.wl.snapshot_edhrec(week1, date="2026-11-01"))
        self.assertEqual(self.wl.popularity_change(), (None, None, {}))
        self.wl.snapshot_edhrec(week2, date="2026-11-08")
        old, new, change = self.wl.popularity_change(7)
        self.assertEqual((old, new), ("2026-11-01", "2026-11-08"))
        self.assertEqual(change, {"Sol Ring": 1.0, "Lightning Bolt": 4.0})

    def test_spec_uses_popularity_and_price_history(self):
        self.wl.snapshot(self.db)
        self.wl.snapshot_edhrec([view("Lightning Bolt", 10, 100, 2.0)], date="2026-11-01")
        self.wl.snapshot_edhrec([view("Lightning Bolt", 14, 100, 3.0)], date="2026-11-08")
        self.next_day("2026-11-08", Lightning_Bolt=3.00)  # price +50%
        rising = [{"name": "Lightning Bolt", "trend": 3.0, "usd": 3.0, "new": False, "change_pts": 4.0}]
        [row] = watchlist.spec_signals(self.db, self.wl, rising, today="2026-11-19")
        self.assertEqual(row["pop_change_pts"], 4.0)
        self.assertEqual(row["price_change_pct"], 50.0)
        # (3.0 + 4.0 x 5) x 1.0 supply (1 printing) x 0.5 price already up
        self.assertEqual(row["score"], round((3.0 + 20.0) * 1.0 * 0.5, 1))
        self.assertIn("price already up +50%", row["reasons"])


class RadarTests(WatchCase):
    def test_rising_commanders_and_their_cheap_synergy_cards(self):
        week = [{"name": "Hot Commander", "num_decks": 500, "trend_zscore": 12.0},
                {"name": "Cold Commander", "num_decks": 900, "trend_zscore": -1.0},
                {"name": "Warm Commander", "num_decks": 50, "trend_zscore": 3.0}]
        cmdrs = watchlist.rising_commanders(week=week)
        self.assertEqual([c["name"] for c in cmdrs], ["Hot Commander", "Warm Commander"])
        cards = {"Hot Commander": [
            {"name": "Lightning Bolt", "synergy": 0.5, "inclusion": 0.6},
            {"name": "Sol Ring", "synergy": 0.05, "inclusion": 0.9},             # low synergy: left out
            {"name": "The One Ring", "synergy": 0.7, "inclusion": 0.3},          # over max price
            {"name": "Unknown Spoiler", "synergy": 0.9, "inclusion": 0.1},       # not in the card database
        ]}

        def cards_for(name):
            if name not in cards:
                raise edhrec_client.EdhrecError("no page")
            return cards[name]
        radar = watchlist.commander_radar(self.db, commanders=cmdrs, cards_for=cards_for, max_usd=10)
        self.assertEqual([c["commander"] for c in radar], ["Hot Commander"])  # Warm's page failed: skipped
        self.assertEqual([x["name"] for x in radar[0]["cards"]], ["Lightning Bolt"])
        self.assertEqual(radar[0]["trend"], 12.0)


if __name__ == "__main__":
    unittest.main()
