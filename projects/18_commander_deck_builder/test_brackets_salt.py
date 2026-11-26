import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import brackets
import build_deck
import card_db
import salt
import tournaments
from test_card_db import printing, write_bulk


def classified(cards, combos=(), tag="C"):
    return {"bracketTag": tag,
            "cards": [{"card": {"name": n}, "quantity": 1, "banned": f.get("banned", False),
                       "gameChanger": f.get("gc", False), "massLandDenial": f.get("mld", False),
                       "extraTurn": f.get("extra", False)} for n, f in cards],
            "combos": [{"combo": {"uses": [{"card": {"name": n}} for n in uses]}, "relevant": True,
                        "definitelyTwoCard": two, "extraTurn": chain, "massLandDenial": False}
                       for uses, two, chain in combos]}


class BracketTests(unittest.TestCase):
    def test_rules(self):
        b = brackets.official_bracket(classified([("Sol Ring", {})], tag="E"))
        self.assertEqual((b["lowest"], b["name"], b["spellbook_tag"]), (2, "Core", "Exhibition"))
        b = brackets.official_bracket(classified([("Rhystic Study", {"gc": True}), ("Bolt", {})]))
        self.assertEqual(b["lowest"], 3)
        self.assertIn("1 Game Changer: Rhystic Study", b["reasons"][0])
        many = [(f"GC {i}", {"gc": True}) for i in range(4)]
        self.assertEqual(brackets.official_bracket(classified(many))["lowest"], 4)
        two = brackets.official_bracket(classified([("A", {}), ("B", {})], combos=[(["A", "B"], True, False)]))
        self.assertEqual(two["lowest"], 3)
        self.assertIn("A + B", two["two_card_combos"])
        self.assertEqual(brackets.official_bracket(classified([("Armageddon", {"mld": True})]))["lowest"], 4)
        chain = brackets.official_bracket(classified([("Time Warp", {"extra": True})],
                                                     combos=[(["Time Warp", "X"], False, True)]))
        self.assertEqual(chain["lowest"], 4)
        single = brackets.official_bracket(classified([("Time Warp", {"extra": True})]))
        self.assertEqual(single["lowest"], 2)  # one extra turn, not chained
        self.assertTrue(any("extra-turn cards" in r for r in single["reasons"]))
        banned = brackets.official_bracket(classified([("Black Lotus", {"banned": True})], tag="B"))
        self.assertEqual((banned["lowest"], banned["name"]), (None, "not legal"))

    def test_classify_cached_and_shape_checked(self):
        post = mock.Mock(return_value=classified([("Sol Ring", {})]))
        with tempfile.TemporaryDirectory() as tmp:
            brackets.classify(["Hero"], [("Sol Ring", 1)], cache_dir=tmp, post=post)
            brackets.classify(["Hero"], [("Sol Ring", 1)], cache_dir=tmp, post=post)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.args[0]["main"], [{"card": "Sol Ring", "quantity": 1}])
            with self.assertRaises(brackets.BracketError):
                brackets.classify(["X"], [("Y", 1)], cache_dir=tmp, post=lambda b: {"nope": 1})


class SaltTests(unittest.TestCase):
    def test_fetch_pages_and_cache(self):
        pages = {"top/salt": {"container": {"json_dict": {"cardlists": [{"cardviews": [
                    {"name": "Stasis", "salt": 3.053}], "more": "top/salt--1.json"}]}}},
                 "top/salt--1": {"cardviews": [{"name": "Sol Ring", "salt": 1.59}], "more": None}}
        with tempfile.TemporaryDirectory() as tmp:
            got = salt.fetch(get=lambda p: pages[p], cache=Path(tmp) / "s.json")
            self.assertEqual(got, {"Stasis": 3.05, "Sol Ring": 1.59})
            self.assertEqual(salt.fetch(get=lambda p: self.fail("not cached"), cache=Path(tmp) / "s.json"), got)

    def test_deck_salt_and_front_face(self):
        edhrec = {"Stasis": 3.05, "Esika, God of the Tree": 1.2}
        s = salt.deck_salt(["Stasis", "Esika, God of the Tree // The Prismatic Bridge", "Plain Card"], edhrec=edhrec)
        self.assertEqual(s["total"], 4.2)
        self.assertEqual(s["saltiest"][0], ("Stasis", 3.05))
        self.assertEqual(s["per_card"]["Plain Card"], 0.0)

    def test_pool_drops_salty_cards_and_extra_game_changers(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bulk = Path(tmp.name) / "bulk.jsonl.gz"
        cards = [printing("cmd", "Hero", type_line="Legendary Creature — Elf", color_identity=["G"])]
        cards += [printing(f"g{i}", f"GC {i}", color_identity=["G"], game_changer=True, prices={"usd": "1.00"})
                  for i in range(5)]
        cards += [printing("salty", "Salty Card", color_identity=["G"], prices={"usd": "1.00"}),
                  printing("nice", "Nice Card", color_identity=["G"], prices={"usd": "1.00"})]
        write_bulk(bulk, cards)
        card_db.build_db(bulk, Path(tmp.name) / "c.sqlite")
        db = card_db.CardDB(Path(tmp.name) / "c.sqlite")
        self.addCleanup(db.close)
        hero = db.get("Hero")
        edhrec = [{"name": n, "inclusion": 0.9 - i / 10} for i, n in
                  enumerate([f"GC {i}" for i in range(5)] + ["Salty Card", "Nice Card"])]
        names = lambda pool: [c["name"] for c in pool]  # noqa: E731
        self.assertEqual(len(build_deck.candidate_pool(hero, edhrec, db)), 7)
        self.assertNotIn("Salty Card", names(build_deck.candidate_pool(hero, edhrec, db, max_salt=2.0,
                                                                        salt={"Salty Card": 2.5})))
        b3 = names(build_deck.candidate_pool(hero, edhrec, db, bracket=3))
        self.assertEqual([n for n in b3 if n.startswith("GC")], ["GC 0", "GC 1", "GC 2"])  # 3 most played
        self.assertFalse([n for n in names(build_deck.candidate_pool(hero, edhrec, db, bracket=2)) if n.startswith("GC")])


class BracketPoolTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bulk = Path(tmp.name) / "bulk.jsonl.gz"
        write_bulk(bulk, [printing("cmd", "Hero", type_line="Legendary Creature — Elf", color_identity=["G"]),
                          *[printing(n.lower(), n, color_identity=["G"], prices={"usd": "1.00"})
                            for n in ("Armageddon", "Time Warp", "Combo A", "Combo B", "Late A", "Late B", "Solo", "Plain")]])
        tags = {"armageddon": "wipe,mld", "time warp": "extra_turn"}
        card_db.build_db(bulk, Path(tmp.name) / "c.sqlite", tags=tags)
        self.db = card_db.CardDB(Path(tmp.name) / "c.sqlite")
        self.addCleanup(self.db.close)
        self.hero = self.db.get("Hero")
        names = ["Armageddon", "Time Warp", "Combo A", "Combo B", "Late A", "Late B", "Solo", "Plain"]
        self.edhrec = [{"name": n, "inclusion": 0.9 - i / 20} for i, n in enumerate(names)]

    def pool(self, bracket):
        return build_deck.candidate_pool(self.hero, self.edhrec, self.db, bracket=bracket)

    def test_land_denial_and_extra_turns_out_for_brackets_1_to_3(self):
        for b in (1, 2, 3):
            names = {c["name"] for c in self.pool(b)}
            self.assertFalse({"Armageddon", "Time Warp"} & names, b)
        self.assertTrue({"Armageddon", "Time Warp"} <= {c["name"] for c in self.pool(4)})

    def test_two_card_combos_cut_by_bracket(self):
        raw = {"bracketTag": "S", "cards": [], "combos": [
            {"combo": {"uses": [{"card": {"name": "Combo A"}}, {"card": {"name": "Combo B"}}]},
             "definitelyTwoCard": True, "speed": 5},
            {"combo": {"uses": [{"card": {"name": "Late A"}}, {"card": {"name": "Late B"}}]},
             "definitelyTwoCard": True, "speed": 2},
            {"combo": {"uses": [{"card": {"name": "Hero"}}, {"card": {"name": "Solo"}}]},
             "definitelyTwoCard": True, "speed": 5},
            {"combo": {"uses": [{"card": {"name": "Plain"}}, {"card": {"name": "Combo A"}}, {"card": {"name": "X"}}]},
             "definitelyTwoCard": False, "speed": 5},
        ]}
        fake = lambda members, main, **k: raw  # noqa: E731
        pool2, notes2 = brackets.cut_combos(self.hero, self.pool(2), 2, classify_fn=fake)
        out2 = {c["name"] for c in self.pool(2)} - {c["name"] for c in pool2}
        self.assertEqual(out2, {"Combo B", "Late B", "Solo"})  # less-played piece; never the commander
        self.assertTrue(any("Solo (two-card combo with Hero" in n for n in notes2))
        pool3, notes3 = brackets.cut_combos(self.hero, self.pool(3), 3, classify_fn=fake)
        out3 = {c["name"] for c in self.pool(3)} - {c["name"] for c in pool3}
        self.assertEqual(out3, {"Combo B", "Solo"})  # the slow (speed 2) combo may stay in bracket 3
        self.assertIn("fast: speed 5", notes3[0])
        self.assertEqual(brackets.cut_combos(self.hero, self.pool(4), 4, classify_fn=fake)[1], [])

    def test_claude_is_told_the_bracket(self):
        import llm_deck
        hero = {"name": "Hero", "oracle_text": "x", "color_identity": "G"}
        text = llm_deck.first_prompt(hero, 100, 1.0, "T", bracket=3)
        self.assertIn("Target power level: bracket 3 (Upgraded: at most 3 Game Changers", text)
        self.assertNotIn("Target power level", llm_deck.first_prompt(hero, 100, 1.0, "T"))
        self.assertEqual(llm_deck.bracket_text(None), "")


class AutoImportTests(unittest.TestCase):
    def test_recent_big_events_skip_tests_and_saved(self):
        nodes = [("big-new", "Big New Open", 120, "2026-11-15"), ("small", "Small Thing", 20, "2026-11-15"),
                 ("old", "Old Open", 200, "2026-09-01"), ("t", "TEST event", 99, "2026-11-18"),
                 ("saved-one", "Saved Open", 80, "2026-11-10")]
        listing = "<html>" + "".join(
            f'{{"node":{{"id":"x","TID":"{t}","name":{json.dumps(n)},"size":{s},"tournamentDate":"{d}T10:00:00.000Z"}}}}'
            for t, n, s, d in nodes) + "</html>"
        with tempfile.TemporaryDirectory() as tmp:
            got = tournaments.recent_events(fetch=lambda url: listing, today="2026-11-20", cache_dir=tmp)
            self.assertEqual([e["tid"] for e in got], ["big-new", "saved-one"])
            data = Path(tmp) / "t"
            data.mkdir()
            (data / "saved-one.json").write_text(json.dumps({"tid": "saved-one", "name": "Saved Open", "date": "2026-11-10",
                                                             "size": 80, "entries": []}))
            imported = []
            with mock.patch("tournaments.import_event", side_effect=lambda tid, **k: imported.append(tid) or {"name": tid}):
                names = tournaments.auto_import(max_events=5, data_dir=data, fetch=lambda url: listing,
                                                today="2026-11-20", cache_dir=tmp, log=lambda *_: None)
            self.assertEqual(imported, ["big-new"])
            self.assertEqual(names, ["big-new"])


if __name__ == "__main__":
    unittest.main()
