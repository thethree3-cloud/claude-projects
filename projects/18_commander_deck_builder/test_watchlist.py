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


if __name__ == "__main__":
    unittest.main()
