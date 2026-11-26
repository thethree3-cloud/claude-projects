import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import card_db
import edhrec_client
import updater
import watchlist
from test_card_db import printing, write_bulk


class LockTests(unittest.TestCase):
    def test_lock_and_stale_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "update.lock"
            self.assertIsNone(updater.running(lock))
            self.assertTrue(updater._acquire(lock))
            self.assertEqual(updater.running(lock), os.getpid())
            self.assertFalse(updater._acquire(lock))  # second run refused
            updater._release(lock)
            self.assertFalse(lock.exists())
            lock.write_text("999999999 2026-01-01")  # a crashed run's lock
            self.assertIsNone(updater.running(lock))
            self.assertTrue(updater._acquire(lock))
            updater._release(lock)


class FakeArchidekt:
    def __init__(self, *a, **k):
        pass

    def sample(self, max_new, log):
        return 7

    def set_meta(self, k, v):
        pass

    def count(self):
        return 67

    def close(self):
        pass


class RunTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        bulk = self.dir / "bulk.jsonl.gz"
        write_bulk(bulk, [printing("sol", "Sol Ring", prices={"usd": "1.50"})])
        card_db.build_db(bulk, self.dir / "cards.sqlite", updated_at="2026-11-20T10:00:00Z")
        self.status = self.dir / "status.json"
        self.lock = self.dir / "update.lock"
        patches = [
            mock.patch("card_db.ensure_db", return_value=self.dir / "cards.sqlite"),
            mock.patch.object(watchlist, "DATA_DIR", self.dir),
            mock.patch("watchlist.fetch_top", side_effect=edhrec_client.EdhrecError("EDHREC down")),
            mock.patch("portfolio.track_owned", return_value=[1, 2]),
            mock.patch("price_history.update_buylist", return_value=5),
            mock.patch("archidekt.Archidekt", FakeArchidekt),
            mock.patch("tournaments.auto_import", return_value=["Big Open"]),
            mock.patch("scryfall_tags.is_stale", return_value=False),
            mock.patch("alerts.daily_digest", return_value=(self.dir / "2026-11-20.md", "# d")),
            mock.patch("export_scanner_data.export_all", return_value="1 cards, 0 commanders"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_once(self, force=False):
        return updater.run_update(force=force, log=lambda *_: None, status_path=self.status, lock=self.lock)

    def test_every_step_recorded_and_failures_dont_stop_the_rest(self):
        status = self.run_once()
        steps = status["steps"]
        self.assertEqual(set(steps), set(updater.STEPS))
        self.assertFalse(steps["popularity"]["ok"])
        self.assertIn("EDHREC down", steps["popularity"]["message"])
        self.assertTrue(steps["digest"]["ok"])  # ran after the failure
        self.assertEqual(steps["tournaments"]["message"], "imported Big Open")
        self.assertEqual(steps["prices"]["message"].split()[0], "2026-11-20")
        self.assertFalse(status["running"])
        self.assertFalse(self.lock.exists())
        self.assertEqual(json.loads(self.status.read_text())["steps"]["buylist"]["message"], "5 cards")

    def test_daily_steps_skip_unless_forced(self):
        import tournaments
        self.run_once()
        self.run_once()
        self.assertEqual(tournaments.auto_import.call_count, 1)  # already ran today
        self.run_once(force=True)
        self.assertEqual(tournaments.auto_import.call_count, 2)

    def test_refuses_while_another_runs(self):
        self.lock.write_text(f"{os.getpid()} now")
        self.assertIsNone(self.run_once())


if __name__ == "__main__":
    unittest.main()
