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
        page = {"commander": {"legal_commander": True, "num_decks": 100},
                "cards": [{"name": f"Spell {i}", "inclusion": 0.5 - i / 200} for i in range(80)]}
        with mock.patch("edhrec_client.fetch_commander_page", return_value={}), \
             mock.patch("edhrec_client.parse_commander_page", return_value=page):
            cls.prep = deck_service.prepare("Green Commander", cls.db, owned={"Spell 3"})

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def test_commander_names(self):
        with mock.patch("edhrec_client.commander_popularity", return_value={"Walker": 10}):
            names = deck_service.commander_names(self.db)
        self.assertEqual(names[0], "Walker")  # most-led commander first
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

    def test_card_type_uses_the_front_face(self):
        t = deck_service.card_type
        self.assertEqual(t({"type_line": "Artifact Creature — Golem"}), "Creature")
        self.assertEqual(t({"type_line": "Artifact Land"}), "Land")
        self.assertEqual(t({"type_line": "Sorcery // Land"}), "Sorcery")
        self.assertEqual(t({"type_line": "Legendary Enchantment — Background"}), "Enchantment")
        self.assertEqual(t({}), "Other")

    def test_alternates_and_swap(self):
        result = deck_service.build_code(self.prep, 100, self.db)
        deck = result["deck"]
        alts = deck_service.alternates(self.prep, deck, "Sorcery")
        in_deck = {c["name"] for c in deck["cards"]}
        self.assertTrue(alts)
        self.assertLessEqual(len(alts), 15)
        self.assertFalse(in_deck & {a["name"] for a in alts})
        self.assertEqual(alts, sorted(alts, key=lambda a: (not a["listed"], -a["inclusion"], a["cost"], a["name"])))
        self.assertEqual(deck_service.alternates(self.prep, deck, "Planeswalker"), [])

        out = deck_service.replace_options(deck, "Sorcery")[0]  # least played first
        self.assertEqual(out["inclusion"], min(c["inclusion"] for c in deck["cards"]))
        new, errors = deck_service.swap(self.prep, result, out["name"], alts[0]["name"], 100, self.db)
        self.assertEqual(errors, [])
        names = {c["name"] for c in new["deck"]["cards"]}
        self.assertIn(alts[0]["name"], names)
        self.assertNotIn(out["name"], names)
        self.assertTrue(new["check"]["ok"])
        self.assertIn(f"1 {alts[0]['name']}", new["text"])
        self.assertEqual(new["swaps"][0]["out"], out["name"])
        self.assertEqual(len(new["deck"]["cards"]) + sum(new["deck"]["basics"].values()), 99)
        self.assertNotIn(alts[0]["name"], {c["name"] for c in result["deck"]["cards"]})  # original untouched

    def test_swap_refused_when_it_breaks_the_deck(self):
        result = deck_service.build_code(self.prep, 40, self.db)
        out = result["deck"]["cards"][0]["name"]
        pricey = next(c["name"] for c in self.prep["pool"] if c["name"] == "Pricey Spell")
        new, errors = deck_service.swap(self.prep, result, out, pricey, 40, self.db)
        self.assertIsNone(new)
        self.assertTrue(any("budget" in e for e in errors), errors)
        already = result["deck"]["cards"][1]["name"]
        self.assertEqual(deck_service.swap(self.prep, result, out, already, 40, self.db)[1],
                         [f"{already} is already in the deck."])

    def test_combo_removal_can_be_turned_off(self):
        page = {"commander": {"legal_commander": True, "num_decks": 100},
                "cards": [{"name": f"Spell {i}", "inclusion": 0.5 - i / 200} for i in range(80)]}
        with mock.patch("edhrec_client.fetch_commander_page", return_value={}), \
             mock.patch("edhrec_client.parse_commander_page", return_value=page), \
             mock.patch("brackets.cut_combos", side_effect=lambda c, pool, b: (pool[1:], ["Spell 0 (two-card combo)"])) as cut:
            on = deck_service.prepare("Green Commander", self.db, bracket=2)
            off = deck_service.prepare("Green Commander", self.db, bracket=2, cut_combos=False)
        self.assertEqual(cut.call_count, 1)  # only the "on" build asked Spellbook
        self.assertIn("Spell 0 (two-card combo)", on["bracket_notes"])
        self.assertEqual(len(off["pool"]), len(on["pool"]) + 1)
        self.assertFalse(off["cut_combos"])

    def test_price_label(self):
        self.assertEqual(deck_service.price_label({"owned": True, "usd": 3.0}), "owned")
        self.assertEqual(deck_service.price_label({"owned": False, "usd": 3.0}), "$3.00")
        self.assertEqual(deck_service.price_label({"owned": False, "usd": None}), "n/a")


if __name__ == "__main__":
    unittest.main()
