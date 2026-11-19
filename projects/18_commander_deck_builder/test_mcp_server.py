import tempfile
import unittest
from pathlib import Path
from unittest import mock

import card_db
import mcp_server
from test_card_db import write_bulk
from test_pairs import cards as pair_cards


class McpToolTests(unittest.TestCase):
    """The tools are plain functions; the stdio protocol itself is smoke-tested by hand (see README)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        bulk = Path(cls.tmp.name) / "bulk.jsonl.gz"
        write_bulk(bulk, pair_cards())
        card_db.build_db(bulk, Path(cls.tmp.name) / "cards.sqlite")
        mcp_server._db = card_db.CardDB(Path(cls.tmp.name) / "cards.sqlite")
        patcher = mock.patch("edhrec_client.commander_popularity", return_value={})
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        page = {"commander": {"legal_commander": True, "num_decks": 500},
                "cards": [{"name": f"{c} Spell {i}", "inclusion": 0.5, "role": "Sorcery", "synergy": 0.1,
                           "high_synergy": False, "game_changer": False}
                          for i in range(70) for c in ("Green", "Blue")]}
        patcher = mock.patch("edhrec_client.commander_cards", return_value={**page, "sources": ["x"]})
        patcher.start()
        cls.addClassCleanup(patcher.stop)

    @classmethod
    def tearDownClass(cls):
        mcp_server._db.close()
        mcp_server._db = None
        cls.tmp.cleanup()

    def test_find_commander_lists_partners(self):
        text = mcp_server.find_commander("green partner")
        self.assertTrue(text.startswith("Green Partner\nColor identity: G"))
        self.assertIn("Can pair with 1 cards, most played first: Blue Partner", text)
        self.assertIn("No card matched", mcp_server.find_commander("zzzzqq"))

    def test_build_pair_deck_is_valid_and_has_import_list(self):
        text = mcp_server.build_commander_deck("green partner", 100, partner="blue")
        self.assertIn("# Green Partner + Blue Partner - $100 budget", text)
        imports = text.split("## Import list\n\n", 1)[1].splitlines()
        self.assertEqual(imports[:2], ["1 Green Partner", "1 Blue Partner"])
        self.assertEqual(sum(int(line.split(" ", 1)[0]) for line in imports), 100)

    def test_build_errors_are_text(self):
        self.assertIn("over the $1.00 budget", mcp_server.build_commander_deck("green partner", 1))
        self.assertIn("budget must be 0 or more", mcp_server.build_commander_deck("green partner", -5))
        self.assertIn("has no partner ability", mcp_server.build_commander_deck("lone legend", 50, partner="x"))

    def test_validate(self):
        ok = mcp_server.validate_commander_deck("1 Green Partner\n99 Forest")
        self.assertTrue(ok.startswith("PASS: Green Partner"))
        bad = mcp_server.validate_commander_deck("1 Green Partner\n1 Blue Spell 0\n98 Forest")
        self.assertIn("ERROR: Blue Spell 0 is outside", bad)
        self.assertIn("bracket must be 1-5", mcp_server.validate_commander_deck("1 Green Partner", bracket=9))

    def test_commander_cards_table(self):
        text = mcp_server.commander_cards("green partner", limit=2)
        self.assertIn("| 1 | Green Spell 0 |", text)


if __name__ == "__main__":
    unittest.main()
