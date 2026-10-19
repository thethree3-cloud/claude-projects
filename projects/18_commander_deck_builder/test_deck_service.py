import tempfile
import unittest
from pathlib import Path
from unittest import mock

import card_db
import deck_service
from test_card_db import printing, write_bulk
from test_llm_deck import FakeClient, make_cards, message


class DeckServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        bulk = Path(cls.tmp.name) / "bulk.jsonl.gz"
        cards = make_cards() + [
            printing("pw", "Walker", type_line="Legendary Planeswalker — X", color_identity=["G"],
                     oracle_text="Walker can be your commander."),
            printing("lart", "Legendary Rock", type_line="Legendary Artifact", color_identity=[]),
        ]
        write_bulk(bulk, cards)
        card_db.build_db(bulk, Path(cls.tmp.name) / "cards.sqlite")
        cls.db = card_db.CardDB(Path(cls.tmp.name) / "cards.sqlite")
        page = {"commander": {"legal_commander": True},
                "cards": [{"name": f"Spell {i}", "inclusion": 0.5 - i / 200} for i in range(80)]}
        with mock.patch("deck_service.edhrec_client.fetch_commander_page", return_value={}), \
             mock.patch("deck_service.edhrec_client.parse_commander_page", return_value=page):
            cls.prep = deck_service.prepare("Green Commander", cls.db, owned={"Spell 3"})

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def test_commander_names(self):
        names = deck_service.commander_names(self.db)
        self.assertIn("Green Commander", names)
        self.assertIn("Walker", names)
        self.assertNotIn("Legendary Rock", names)  # legendary but not a creature

    def test_prepare_pool_has_rules_text_and_owned_flags(self):
        self.assertEqual(self.prep["commander_cost"], 2.0)
        by = {c["name"]: c for c in self.prep["pool"]}
        self.assertEqual(by["Spell 0"]["oracle_text"], "Draw a card.")
        self.assertTrue(by["Spell 3"]["owned"])

    def test_prepare_unknown_commander(self):
        with self.assertRaises(LookupError):
            deck_service.prepare("Nobody", self.db)

    def test_build_code_is_validated(self):
        result = deck_service.build_code(self.prep, 100, self.db, owned={"Spell 3"}, owned_mode=True)
        self.assertTrue(result["check"]["ok"], result["check"]["errors"])
        self.assertTrue(result["text"].startswith("1 Green Commander"))
        self.assertEqual(result["builder"], "Code only")
        roles = [role for role, _ in deck_service.grouped(result["deck"])]
        self.assertEqual(roles[0], "draw")

    def test_build_claude_valid_and_invalid(self):
        ids = [f"c{i}" for i in range(1, 63)]
        ok = deck_service.build_claude(self.prep, 100, self.db, FakeClient([message(ids)]))
        self.assertTrue(ok["check"]["ok"])
        self.assertEqual(ok["strategy"], "Go wide with elves.")
        bad = deck_service.build_claude(self.prep, 100, self.db, FakeClient([message(["c999"])] * 3))
        self.assertIsNone(bad["deck"])  # never handed over as a deck
        self.assertEqual(len(bad["attempts"]), 3)

    def test_price_label(self):
        self.assertEqual(deck_service.price_label({"owned": True, "usd": 3.0}), "owned")
        self.assertEqual(deck_service.price_label({"owned": False, "usd": 3.0}), "$3.00")
        self.assertEqual(deck_service.price_label({"owned": False, "usd": None}), "n/a")


if __name__ == "__main__":
    unittest.main()
