"""Tests for the Card Scanner export's EDHREC "top commanders" step (no network)."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import edhrec_client
import export_scanner_data


def card_page(*commanders):
    views = [{"name": n, "num_decks": d, "potential_decks": p} for n, d, p in commanders]
    return {"container": {"json_dict": {"cardlists": [
        {"header": "New Commanders", "cardviews": [{"name": "Brand New", "num_decks": 9, "potential_decks": 10}]},
        {"header": "Top Commanders", "cardviews": views},
        {"header": "Creatures", "cardviews": [{"name": "Some Creature"}]},
    ]}}}


class ParseTests(unittest.TestCase):
    def test_reads_only_top_commanders_most_decks_first(self):
        page = card_page(("B", 50, 100), ("A", 500, 1000), ("C", 5, 10))
        got = edhrec_client.parse_card_commanders(page, top=2)
        self.assertEqual([c["name"] for c in got], ["A", "B"])
        self.assertEqual(got[0], {"name": "A", "decks": 500, "potential": 1000})

    def test_unexpected_format_raises(self):
        with self.assertRaises(edhrec_client.EdhrecError):
            edhrec_client.parse_card_commanders({"nope": 1})


class ExportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name) / "cards"
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE cards (name TEXT, edhrec_rank INTEGER, type_line TEXT)")
        self.conn.executemany("INSERT INTO cards VALUES (?, ?, ?)", [
            ("Sol Ring", 1, "Artifact"), ("Forest", 2, "Basic Land — Forest"),
            ("Arcane Signet", 3, "Artifact"), ("Command Tower", 4, "Land")])
        self.calls = []

    def fetch(self, slug):
        self.calls.append(slug)
        if slug == "command-tower":
            raise edhrec_client.EdhrecError("no page")
        return card_page(("Atraxa, Praetors' Voice", 900, 1000))

    def run_export(self, **kw):
        return export_scanner_data.export_top_commanders(self.conn, cache_dir=self.cache, fetch=self.fetch,
                                                         log=lambda *_: None, **kw)

    def test_wanted_first_basics_skipped_budget_respected(self):
        out = self.run_export(wanted=["Arcane Signet"], budget=2)
        self.assertEqual(self.calls, ["arcane-signet", "sol-ring"])   # wanted first; Forest skipped; budget 2
        self.assertEqual(out["Sol Ring"], [["Atraxa, Praetors' Voice", 900, 1000]])
        self.assertNotIn("Command Tower", out)                          # not fetched yet

    def test_cache_reused_and_missing_pages_remembered(self):
        self.run_export(budget=10)
        first = list(self.calls)
        self.assertIn("command-tower", first)
        out = self.run_export(budget=10)
        self.assertEqual(self.calls, first)                             # second run: all from cache
        self.assertNotIn("Command Tower", out)                          # no page -> cached as empty, left out
        cached = json.loads((self.cache / "command-tower.json").read_text())
        self.assertEqual(cached["top"], [])


if __name__ == "__main__":
    unittest.main()
