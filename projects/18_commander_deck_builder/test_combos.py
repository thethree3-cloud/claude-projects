import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import card_db
import combos
import mcp_server
from test_card_db import printing, write_bulk


def variant(vid, cards, produces=("Infinite mana",), popularity=100):
    return {"id": vid, "uses": [{"card": {"name": c}} for c in cards],
            "produces": [{"feature": {"name": p}} for p in produces], "description": "Do the thing.\nRepeat.",
            "easyPrerequisites": "All permanents on the battlefield.", "notablePrerequisites": "",
            "popularity": popularity}


ANSWER = {"results": {
    "included": [variant("1-2", ["Kiki-Jiki, Mirror Breaker", "Zealous Conscripts"], popularity=50),
                 variant("3-4", ["Esika, God of the Tree", "Sol Ring"], popularity=900)],
    "almostIncluded": [variant("1-5", ["Kiki-Jiki, Mirror Breaker", "Pestermite"], popularity=10),
                       variant("1-6", ["Kiki-Jiki, Mirror Breaker", "Felidar Guardian"], popularity=70),
                       variant("7-8-9", ["Kiki-Jiki, Mirror Breaker", "Card X", "Card Y"])],
}}


class ComboTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        bulk = Path(cls.tmp.name) / "bulk.jsonl.gz"
        write_bulk(bulk, [
            printing("kiki", "Kiki-Jiki, Mirror Breaker", type_line="Legendary Creature — Goblin", prices={"usd": "8"}),
            printing("pest", "Pestermite", prices={"usd": "0.40"}),
            printing("esika", "Esika, God of the Tree // The Prismatic Bridge", layout="modal_dfc", type_line=None,
                     oracle_text=None, card_faces=[{"type_line": "Legendary Creature — God", "oracle_text": "x"},
                                                   {"type_line": "Legendary Artifact", "oracle_text": "y"}]),
        ])
        card_db.build_db(bulk, Path(cls.tmp.name) / "cards.sqlite")
        cls.db = card_db.CardDB(Path(cls.tmp.name) / "cards.sqlite")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def find(self, commanders, main, **kw):
        return combos.find_combos(commanders, main, self.db, fetch_fn=lambda c, m: ANSWER["results"], **kw)

    def test_in_deck_and_one_card_away(self):
        found = self.find(["Kiki-Jiki, Mirror Breaker"],
                          ["Zealous Conscripts", "Esika, God of the Tree // The Prismatic Bridge", "Sol Ring"])
        self.assertEqual([c["id"] for c in found["in_deck"]], ["3-4", "1-2"])  # most popular first
        self.assertEqual(found["in_deck"][1]["missing"], [])
        self.assertEqual(found["in_deck"][0]["missing"], [])  # Spellbook's front-face name still matches
        away = found["one_card_away"]
        self.assertEqual([c["missing"][0] for c in away], ["Felidar Guardian", "Pestermite"])  # 2-missing dropped
        self.assertIsNone(away[0]["missing_usd"])  # not in the card database
        self.assertEqual(away[1]["missing_usd"], 0.40)
        self.assertEqual(away[1]["url"], "https://commanderspellbook.com/combo/1-5/")

    def test_almost_limit_and_report(self):
        found = self.find(["Kiki-Jiki, Mirror Breaker"], ["Zealous Conscripts"], almost_limit=1)
        self.assertEqual(len(found["one_card_away"]), 1)
        text = combos.format_report(found)
        self.assertIn("- **Kiki-Jiki, Mirror Breaker + Zealous Conscripts**: Infinite mana", text)
        self.assertIn("- add **Felidar Guardian** (price unknown)", text)

    def test_fetch_caches_by_decklist_and_checks_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            post = mock.Mock(return_value=ANSWER)
            first = combos.fetch(["A"], ["B", "C"], cache_dir=tmp, post=post)
            again = combos.fetch(["A"], ["C", "B"], cache_dir=tmp, post=post)  # same cards, other order
            self.assertEqual(first, again)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.args[0]["main"], [{"card": "B"}, {"card": "C"}])
            with self.assertRaises(combos.ComboError):
                combos.fetch(["Z"], ["Y"], cache_dir=tmp, post=lambda body: {"oops": 1})

    def test_mcp_tool(self):
        with mock.patch.object(mcp_server, "_db", self.db), \
                mock.patch("combos.fetch", return_value=ANSWER["results"]):
            text = mcp_server.find_combos("1 Kiki-Jiki, Mirror Breaker\n1 Zealous Conscripts")
            self.assertIn("## Combos in this deck (2)", text)  # the fake answer lists both
            self.assertIn("needs the commander line", mcp_server.find_combos("1 Kiki-Jiki, Mirror Breaker"))


if __name__ == "__main__":
    unittest.main()
