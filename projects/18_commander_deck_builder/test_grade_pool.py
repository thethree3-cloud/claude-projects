import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import card_db
import grade_pool
from collection import Collection
from test_card_db import printing, write_bulk

CARDS = [
    printing("kes", "Kestia, the Cultivator", type_line="Legendary Enchantment Creature — Nymph",
             color_identity=["G", "W", "U"], oracle_text="Whenever an enchanted creature attacks, draw a card."),
    printing("eid", "Eidolon of Countless Battles", color_identity=["W"], prices={"usd": "1.00"}),
    printing("cou", "Courser of Kruphix", color_identity=["G"], prices={"usd": "2.50"}),
    printing("str", "Stratus Walk", color_identity=["U"], prices={"usd": "0.10"}),
    printing("arc", "Archetype of Courage", color_identity=["W"]),
    printing("gou", "Eye Gouge", color_identity=["B"], prices={"usd": "0.05"}),
    printing("bng", "Banned Thing", color_identity=["G"], legalities={"commander": "banned"}),
    printing("rhy", "Rhystic Study", color_identity=["U"], game_changer=True, prices={"usd": "30.00"}),
]

EDHREC = [
    {"name": "Eidolon of Countless Battles", "inclusion": 0.53, "synergy": 0.53, "high_synergy": True},
    {"name": "Courser of Kruphix", "inclusion": 0.21, "synergy": 0.20, "high_synergy": False},
    {"name": "Archetype of Courage", "inclusion": 0.10, "synergy": 0.09, "high_synergy": False},
    {"name": "Rhystic Study", "inclusion": 0.30, "synergy": -0.05, "high_synergy": False},
]

OWNED = ["Kestia, the Cultivator", "Eidolon of Countless Battles", "Courser of Kruphix", "Stratus Walk",
         "Archetype of Courage", "Eye Gouge", "Banned Thing", "Rhystic Study", "Not A Real Card"]


def fake_client(text=None, stop_reason="end_turn"):
    block = SimpleNamespace(type="text", text=text or json.dumps({"reasons": []}))
    create = mock.Mock(return_value=SimpleNamespace(stop_reason=stop_reason, content=[block]))
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


class GradeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        bulk = self.dir / "bulk.jsonl.gz"
        write_bulk(bulk, CARDS)
        card_db.build_db(bulk, self.dir / "cards.sqlite")
        self.db = card_db.CardDB(self.dir / "cards.sqlite")
        self.addCleanup(self.db.close)
        self.kestia = self.db.get("Kestia, the Cultivator")

    def grade(self, bracket=None):
        return grade_pool.grade_pool(self.kestia, OWNED, self.db, EDHREC, bracket)

    def tier_of(self, result, name):
        return next(c["tier"] for c in result["cards"] if c["name"] == name)


class GradePoolTests(GradeCase):
    def test_tiers_follow_inclusion_thresholds(self):
        r = self.grade()
        self.assertEqual(self.tier_of(r, "Eidolon of Countless Battles"), "Core")
        self.assertEqual(self.tier_of(r, "Courser of Kruphix"), "Strong")
        self.assertEqual(self.tier_of(r, "Archetype of Courage"), "Playable")
        self.assertEqual(self.tier_of(r, "Stratus Walk"), "Filler")  # legal, not on EDHREC

    def test_off_color_and_banned_are_not_legal_with_reason(self):
        r = self.grade()
        gouge = next(c for c in r["cards"] if c["name"] == "Eye Gouge")
        self.assertEqual(gouge["tier"], "Not legal")
        self.assertIn("needs black", gouge["notes"][0])
        self.assertEqual(self.tier_of(r, "Banned Thing"), "Not legal")

    def test_commander_excluded_and_unknown_names_reported(self):
        r = self.grade()
        self.assertNotIn("Kestia, the Cultivator", [c["name"] for c in r["cards"]])
        self.assertEqual(r["missing"], ["Not A Real Card"])

    def test_sorted_best_tier_first(self):
        tiers = [c["tier"] for c in self.grade()["cards"]]
        self.assertEqual(tiers, sorted(tiers, key=grade_pool.TIERS.index))

    def test_summary_counts_value_and_bracket(self):
        s = self.grade()["summary"]
        self.assertEqual((s["owned"], s["legal"]), (7, 5))
        self.assertEqual(s["by_tier"]["Not legal"], 2)
        self.assertEqual(s["legal_value_usd"], 33.60)  # banned / off-color cards don't count
        self.assertEqual((s["game_changers"], s["lowest_bracket"]), (["Rhystic Study"], "3"))

    def test_game_changer_flagged_for_low_bracket(self):
        rhystic = next(c for c in self.grade(bracket=2)["cards"] if c["name"] == "Rhystic Study")
        self.assertIn("Game Changer - not allowed in bracket 2", rhystic["notes"])

    def test_bracket_fit_thresholds(self):
        legal_gc = {"game_changer": True, "tier": "Core"}
        self.assertEqual(grade_pool.bracket_fit([])["lowest_bracket"], "1-2")
        self.assertEqual(grade_pool.bracket_fit([dict(legal_gc, name=str(i)) for i in range(4)])["lowest_bracket"], "4-5")
        off_color_gc = {"name": "x", "game_changer": True, "tier": "Not legal"}
        self.assertEqual(grade_pool.bracket_fit([off_color_gc])["lowest_bracket"], "1-2")


class AddReasonsTests(GradeCase):
    def test_reasons_only_for_legal_cards_sent_and_unknown_names_ignored(self):
        r = self.grade()
        client = fake_client(json.dumps({"reasons": [
            {"name": "Courser of Kruphix", "reason": "Enchantment creature that draws with Kestia. "},
            {"name": "Made Up Card", "reason": "should be ignored"},
            {"name": "Eye Gouge", "reason": "not sent, so ignored"},
        ]}))
        self.assertEqual(grade_pool.add_reasons(r, client), 1)
        by = {c["name"]: c for c in r["cards"]}
        self.assertEqual(by["Courser of Kruphix"]["reason"], "Enchantment creature that draws with Kestia.")
        self.assertIsNone(by["Eye Gouge"]["reason"])
        self.assertIsNone(by["Stratus Walk"]["reason"])  # missing reason is left empty, not invented

        prompt = client.beta.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("Stratus Walk", prompt)
        self.assertNotIn("Eye Gouge", prompt)  # not-legal cards never sent

    def test_bad_answer_raises(self):
        with self.assertRaises(grade_pool.ScanError):
            grade_pool.add_reasons(self.grade(), fake_client("not json"))
        with self.assertRaises(grade_pool.ScanError):
            grade_pool.add_reasons(self.grade(), fake_client(stop_reason="refusal"))


class ReportTests(GradeCase):
    def test_report_has_summary_tiers_and_notes(self):
        report = grade_pool.format_report(self.grade(bracket=2))
        self.assertIn("5 of 7 owned cards are legal", report)
        self.assertIn("## Core (1)", report)
        self.assertIn("| Eidolon of Countless Battles | 53% | +53% | $1.00 |", report)
        self.assertIn("Eye Gouge (outside the commander's colors (needs black))", report)
        self.assertIn("bracket 3 or higher", report)


class CollectionBinderFilterTests(unittest.TestCase):
    def test_names_by_binder(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = Collection(Path(tmp) / "c.sqlite")
            col.save_page("A", 1, [{"slot": 1, "name": "X"}])
            col.save_page("B", 1, [{"slot": 1, "name": "Y"}])
            self.assertEqual(col.names(binder="A"), {"X"})
            self.assertEqual(col.names(), {"X", "Y"})
            col.close()


if __name__ == "__main__":
    unittest.main()
