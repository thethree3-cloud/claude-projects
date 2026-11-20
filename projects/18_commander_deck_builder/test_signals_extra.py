"""Watch-list ideas #4-9: EUR / price range, binder + buy log, digest + alerts,
combo spikes, backtest, Claude explanations."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import alerts
import backtest
import card_db
import combos
import explain
import portfolio
import watchlist
from collection import Collection
from test_card_db import printing, write_bulk
from test_llm_deck import FakeClient


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


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        bulk = self.dir / "bulk.jsonl.gz"
        write_bulk(bulk, [
            printing("ring", "The One Ring", set="ltr", released_at="2023-06-23",
                     prices={"usd": "100.00", "eur": "95.00"}),
            printing("ring", "The One Ring", set="lts", released_at="2023-07-01", collector_number="2",
                     prices={"usd": "180.00", "eur": "150.00"}),
            printing("sol", "Sol Ring", set="old", released_at="2015-01-01", prices={"usd": "1.50", "eur": "1.00"}),
            printing("bolt", "Lightning Bolt", set="lea", released_at="1993-08-05", color_identity=["R"],
                     prices={"usd": "2.00", "eur": "1.80"}),
            printing("penny", "Penny Card", set="pen", released_at="2016-01-01", prices={"usd": "0.10"}),
            printing("newc", "New Combo Card", set="nnn", released_at="2026-11-10", prices={"usd": "3.00"}),
            printing("soon", "Upcoming Card", set="fut", released_at="2027-01-15"),
        ])
        card_db.build_db(bulk, self.dir / "cards.sqlite", updated_at="2026-11-01T00:00:00Z")
        self.db = card_db.CardDB(self.dir / "cards.sqlite")
        self.addCleanup(self.db.close)
        self.wl = watchlist.WatchList(self.dir / "watch.sqlite")
        self.addCleanup(self.wl.close)

    def next_day(self, date, **prices):
        with self.db.conn:
            self.db.conn.execute("UPDATE meta SET value = ? WHERE key = 'updated_at'", (f"{date}T00:00:00Z",))
            for name, (usd, eur) in prices.items():
                self.db.conn.execute("UPDATE cards SET usd = ?, eur = ? WHERE name = ?",
                                     (usd, eur, name.replace("_", " ")))
        return self.wl.snapshot(self.db)


class PriceSignalTests(Case):
    def test_card_prices_and_range(self):
        ring = self.db.get("The One Ring")
        self.assertEqual((ring["usd"], ring["usd_max"], ring["eur"]), (100.0, 180.0, 95.0))
        self.assertEqual(self.db.printings("The One Ring")[0]["eur"], 150.0)

    def test_eur_snapshot_and_market_factor(self):
        self.wl.snapshot(self.db)
        self.next_day("2026-11-05", Lightning_Bolt=(2.00, 2.20), Sol_Ring=(1.80, 1.00))
        bolt = self.db.get("Lightning Bolt")["oracle_id"]
        sol = self.db.get("Sol Ring")["oracle_id"]
        self.assertEqual(self.wl.price_changes(7, "eur")[bolt], 22.2)
        self.assertEqual(self.wl.price_changes(7)[sol], 20.0)
        self.assertEqual(watchlist.market_factor(0, 22.2)[0], 1.15)
        self.assertIn("Cardmarket up first", watchlist.market_factor(0, 22.2)[1])
        self.assertEqual(watchlist.market_factor(20, 0), (1.0, "US up, EU flat (US +20%, EU +0%)"))
        self.assertEqual(watchlist.market_factor(None, 5), (1.0, None))

    def test_old_watchlist_files_are_migrated(self):
        import sqlite3
        path = self.dir / "old.sqlite"
        conn = sqlite3.connect(path)
        conn.executescript("CREATE TABLE snapshots (day INTEGER, card INTEGER, cents INTEGER, PRIMARY KEY (day, card)) "
                           "WITHOUT ROWID; CREATE TABLE watched (name TEXT PRIMARY KEY, oracle_id TEXT, added_at TEXT, "
                           "usd_when_added REAL, note TEXT DEFAULT '');")
        conn.close()
        wl = watchlist.WatchList(path)
        self.addCleanup(wl.close)
        self.assertIn("eur_cents", [r[1] for r in wl.conn.execute("PRAGMA table_info(snapshots)")])
        self.assertIn("target_above", [r[1] for r in wl.conn.execute("PRAGMA table_info(watched)")])


class PortfolioTests(Case):
    def test_buy_sell_and_profit_after_fees(self):
        pf = portfolio.Portfolio(self.wl)
        a = pf.buy(self.db, "lightning bolt", 4, 1.00, "2026-10-01")
        b = pf.buy(self.db, "The One Ring", 1, 80.00, "2026-10-02")
        self.assertTrue(pf.sell(b, 120.00, "2026-11-01"))
        self.assertFalse(pf.sell(b, 130.00))  # already sold
        rows = {r["id"]: r for r in pf.positions(self.db)}
        self.assertEqual(rows[a]["value_now"], 8.0)
        self.assertEqual(rows[a]["if_sold_now"], round(8.0 * 0.87 - 1.0, 2))
        self.assertEqual(rows[a]["profit"], round(8.0 * 0.87 - 1.0 - 4.0, 2))
        self.assertEqual(rows[b]["profit"], round(120 * 0.87 - 1.0 - 80, 2))
        s = pf.summary(self.db)
        self.assertEqual((s["open_cost"], s["open_value"]), (4.0, 8.0))
        self.assertEqual(s["realized"], rows[b]["profit"])
        self.assertTrue(pf.remove(a))
        with self.assertRaises(ValueError):
            pf.buy(self.db, "Sol Ring", 0, 1.0)
        with self.assertRaises(LookupError):
            pf.buy(self.db, "zzzqqq", 1, 1.0)

    def test_bought_and_owned_cards_are_always_tracked(self):
        col = Collection(self.dir / "col.sqlite")
        self.addCleanup(col.close)
        col.save_page("B", 1, [{"slot": 1, "name": "Penny Card"}, {"slot": 2, "name": "Lightning Bolt"}])
        col.set_quantity("B", 1, 2, 3)
        portfolio.track_owned(self.db, self.wl, col)
        self.wl.snapshot(self.db)
        penny = self.db.get("Penny Card")["oracle_id"]
        self.assertEqual(self.wl.history(penny), [("2026-11-01", 0.1)])  # under MIN_TRACK_USD but owned
        self.next_day("2026-11-08", Lightning_Bolt=(3.00, 2.00))
        b = portfolio.binder_value(self.db, self.wl, col)
        self.assertEqual(b["total"], round(0.1 + 3 * 3.0, 2))
        self.assertEqual(b["copies"], 4)
        self.assertEqual(b["history"], [("2026-11-01", 6.1), ("2026-11-08", 9.1)])
        self.assertEqual([c["name"] for c in b["risers"]], ["Lightning Bolt"])


class AlertTests(Case):
    def test_targets_digest_and_no_email_without_settings(self):
        self.wl.snapshot(self.db)
        self.wl.add(self.db, "Lightning Bolt")
        self.assertTrue(self.wl.set_target("Lightning Bolt", above=1.50))
        self.assertFalse(self.wl.set_target("Not Watched", above=1))
        [hit] = self.wl.target_hits(self.db)
        self.assertEqual((hit["name"], hit["direction"], hit["target"]), ("Lightning Bolt", "above", 1.5))
        spec = [{"name": "Sol Ring", "usd": 1.5, "score": 3.0, "reasons": ["EDHREC trend 3.0", "price flat (+0%)"]}]
        text = alerts.build_digest(self.db, self.wl, "2026-11-01", rising=[], spec=spec,
                                   risers={"from": None, "to": None, "rows": []},
                                   binder={"cards": 0, "total": 0.0, "risers": []})
        self.assertIn("**Lightning Bolt** is $2.00 (above your $1.50 target)", text)
        self.assertIn("1. **Sol Ring** $1.50, score 3.0: EDHREC trend 3.0; price flat (+0%)", text)
        self.assertIn("Not enough history yet.", text)
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch("alerts.build_digest", return_value="# digest"), \
                mock.patch("alerts.send_email") as send:
            path, _ = alerts.daily_digest(self.db, self.wl, "2026-11-01", out_dir=self.dir / "d", log=lambda *_: None)
            send.assert_not_called()
        self.assertEqual(path.read_text(), "# digest\n")
        self.assertEqual(self.wl.get_meta("digest_date"), "2026-11-01")

    def test_email_sent_once_when_configured(self):
        env = {"WATCH_SMTP_HOST": "smtp.test", "WATCH_SMTP_USER": "me@test", "WATCH_SMTP_PASSWORD": "pw",
               "WATCH_EMAIL_TO": "me@test"}
        self.assertEqual(alerts.email_settings(env)["port"], 587)
        self.assertIsNone(alerts.email_settings({**env, "WATCH_EMAIL_TO": ""}))
        with mock.patch.dict("os.environ", env, clear=True), \
                mock.patch("alerts.build_digest", return_value="# d"), \
                mock.patch("alerts.send_email") as send:
            alerts.daily_digest(self.db, self.wl, "2026-11-02", out_dir=self.dir / "d", log=lambda *_: None)
            alerts.daily_digest(self.db, self.wl, "2026-11-02", out_dir=self.dir / "d", log=lambda *_: None)
            self.assertEqual(send.call_count, 1)  # rebuilding the same day doesn't email again
        smtp = mock.MagicMock()
        alerts.send_email("s", "body", alerts.email_settings(env), smtp=smtp)
        server = smtp.return_value.__enter__.return_value
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("me@test", "pw")


class ComboSpikeTests(Case):
    def test_new_cards_and_older_partners(self):
        names = combos.new_cards(self.db, today="2026-11-19",
                                 rising=[{"name": "New Combo Card", "trend": 5.0}])
        self.assertEqual(names, ["Upcoming Card", "New Combo Card"])  # upcoming first
        found = {
            "New Combo Card": [{"id": "1-2", "uses": [{"card": {"name": "New Combo Card"}}, {"card": {"name": "Sol Ring"}}],
                                "produces": [{"feature": {"name": "Infinite mana"}}], "popularity": 50},
                               {"id": "1-3", "uses": [{"card": {"name": "New Combo Card"}},
                                                      {"card": {"name": "The One Ring"}}], "produces": [], "popularity": 5}],
            "Upcoming Card": [{"id": "4-2", "uses": [{"card": {"name": "Upcoming Card"}}, {"card": {"name": "Sol Ring"}},
                                                     {"card": {"name": "Unknown Card"}}],
                               "produces": [{"feature": {"name": "Win the game"}}], "popularity": 10}],
        }
        spikes = combos.combo_spikes(self.db, names, today="2026-11-19", variants=lambda n: found[n], max_usd=50)
        self.assertEqual([e["name"] for e in spikes], ["Sol Ring"])  # One Ring over max price; unknown dropped
        sol = spikes[0]
        self.assertEqual({c["new_card"] for c in sol["combos"]}, {"New Combo Card", "Upcoming Card"})
        self.assertEqual(sol["combos"][0]["produces"], ["Infinite mana"])  # most popular combo first
        self.assertEqual(sol["supply"], "1 printing, last 2015")

    def test_variants_cached(self):
        get = mock.Mock(return_value={"results": [{"id": "x"}]})
        with tempfile.TemporaryDirectory() as tmp, mock.patch("combos.time.sleep"):
            self.assertEqual(combos.variants_with("Sol Ring", cache_dir=tmp, get=get), [{"id": "x"}])
            combos.variants_with("Sol Ring", cache_dir=tmp, get=get)
            self.assertEqual(get.call_count, 1)
            self.assertEqual(get.call_args.args[1]["q"], 'card:"Sol Ring"')
            with self.assertRaises(combos.ComboError):
                combos.variants_with("Other", cache_dir=tmp, get=lambda u, p: {"oops": 1})


class BacktestTests(Case):
    def test_needs_history(self):
        res = backtest.run(self.db, self.wl, horizon=7, today="2026-11-19")
        self.assertIsNotNone(res["needed"])
        self.assertIn("Not enough history", backtest.format_report(res))

    def test_top_scores_vs_all(self):
        self.wl.snapshot(self.db)  # 2026-11-01 prices
        self.wl.snapshot_edhrec([view("Sol Ring", 10, 100, 9.0), view("Lightning Bolt", 10, 100, 1.0),
                                 view("The One Ring", 10, 100, 0.5)], date="2026-11-01")
        self.next_day("2026-11-08", Sol_Ring=(3.00, 1.0), Lightning_Bolt=(2.00, 1.8), The_One_Ring=(90.0, 95.0))
        res = backtest.run(self.db, self.wl, horizon=7, top=1, today="2026-11-19")
        self.assertIsNone(res["needed"])
        [day] = res["days"]
        self.assertEqual((day["from"], day["to"], day["cards"]), ("2026-11-01", "2026-11-08", 3))
        self.assertEqual(day["best_names"][0], "Sol Ring")  # highest trend x supply
        self.assertEqual(res["top"]["mean"], 100.0)
        self.assertEqual(res["all"]["n"], 3)
        self.assertEqual(res["all"]["hit_rate"], 33.3)
        self.assertIn("Edge of the top picks", backtest.format_report(res))


def claude_answer(lines):
    text = json.dumps({"explanations": [{"name": n, "why": w} for n, w in lines]})
    usage = SimpleNamespace(input_tokens=2000, output_tokens=400, cache_creation_input_tokens=0,
                            cache_read_input_tokens=0)
    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)], usage=usage)


class ExplainTests(unittest.TestCase):
    def test_facts_include_radar_and_combos(self):
        spec = [{"name": "Sol Ring", "usd": 1.5, "reasons": ["EDHREC trend 3.0"]}]
        radar = [{"commander": "Hot Commander", "trend": 12.0, "cards": [{"name": "Sol Ring", "synergy": 0.5}]}]
        spikes = [{"name": "Sol Ring", "combos": [{"new_card": "New Thing", "produces": ["Infinite mana"]}]}]
        facts = explain.card_facts(spec, radar, spikes)["Sol Ring"]
        self.assertEqual(facts[0], "price $1.50")
        self.assertTrue(any("Hot Commander" in f for f in facts))
        self.assertIn("completes a combo with new card New Thing (Infinite mana)", facts)

    def test_only_asked_cards_are_kept_and_cached(self):
        client = FakeClient([claude_answer([("Sol Ring", " Rising with Hot Commander. "), ("Made Up", "x")])])
        lines, usage, cost = explain.explain({"Sol Ring": ["price $1.50"]}, client)
        self.assertEqual(lines, {"Sol Ring": "Rising with Hot Commander."})
        self.assertEqual(cost, round(2000 * 4 / 1e6 + 400 * 20 / 1e6, 4))
        sent = client.requests[0]
        self.assertEqual(sent["output_config"]["format"]["schema"], explain.SCHEMA)
        self.assertIn("using ONLY the facts", sent["messages"][0]["content"])
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient([claude_answer([("Sol Ring", "why")])])
            spec_row = {"name": "Sol Ring", "usd": 1.5, "reasons": ["r"]}
            with mock.patch("watchlist.spec_signals", return_value=[spec_row]):
                first = explain.explain_today(None, None, client, date="2026-11-19", cache_dir=tmp,
                                              rising=[], radar=[], spikes=[])
                again = explain.explain_today(None, None, FakeClient([]), date="2026-11-19", cache_dir=tmp,
                                              rising=[], radar=[], spikes=[])
            self.assertFalse(first["cached"])
            self.assertTrue(again["cached"])
            self.assertEqual(again["rows"][0]["why"], "why")

    def test_bad_answers_raise(self):
        cut = claude_answer([])
        cut.stop_reason = "max_tokens"
        with self.assertRaises(explain.ScanError):
            explain.explain({"Sol Ring": ["f"]}, FakeClient([cut]))
        self.assertEqual(explain.explain({}, FakeClient([])), ({}, {}, 0.0))


if __name__ == "__main__":
    unittest.main()
