import tempfile
import unittest
from pathlib import Path

import build_deck
import card_db
from test_card_db import printing, write_bulk

COMMANDER = {"name": "Test Commander", "color_identity": "WG"}


def role_of(type_line, text):
    return build_deck.card_role({"type_line": type_line, "oracle_text": text})


class CardRoleTests(unittest.TestCase):
    def test_roles_from_rules_text(self):
        cases = {
            ("Land", "{T}: Add {G}."): "land",
            ("Sorcery", "Destroy all creatures. They can't be regenerated."): "wipe",
            ("Instant", "Exile target creature. Its controller gains life."): "removal",
            ("Instant", "Counter target spell."): "removal",
            ("Enchantment — Aura", "Enchanted creature loses all other abilities."): "removal",
            ("Artifact", "{T}: Add {C}{C}."): "ramp",
            ("Sorcery", "Search your library for up to two basic land cards."): "ramp",
            ("Enchantment", "Whenever you cast an enchantment spell, draw a card."): "draw",
            ("Enchantment — Aura", "Enchanted creature gets +2/+2 and has trample."): "synergy",
        }
        for (type_line, text), want in cases.items():
            self.assertEqual(role_of(type_line, text), want, text)

    def test_land_checked_on_front_face_only(self):
        self.assertEqual(role_of("Sorcery // Land", "Search your library for a basic land card."), "ramp")


def card(name, role, usd, inclusion=0.5, owned=False, listed=True, identity="G"):
    return {"name": name, "role": role, "inclusion": inclusion, "usd": usd, "owned": owned,
            "cost": 0.0 if owned else usd, "color_identity": identity, "listed": listed}


def big_pool(price=0.10):
    """Enough cheap cards of every role to fill a deck."""
    pool = [card(f"Land {i}", "land", price, 0.9 - i / 100) for i in range(20)]
    for role, n in (("wipe", 3), ("removal", 10), ("ramp", 12), ("draw", 12), ("synergy", 40)):
        pool += [card(f"{role} {i}", role, price, 0.8 - i / 100, identity="GW" if i % 2 else "G") for i in range(n)]
    return pool


class BuildDeckTests(unittest.TestCase):
    def build(self, pool, budget=100, owned_mode=False):
        deck = build_deck.build_deck(COMMANDER, pool, budget, owned_mode)
        self.assertEqual(build_deck.check_deck(COMMANDER, deck, budget), [])
        return deck

    def test_full_deck_meets_role_targets(self):
        deck = self.build(big_pool())
        roles = [c["role"] for c in deck["cards"]]
        self.assertEqual(roles.count("land"), 10)  # two colors -> 10 nonbasics
        self.assertEqual(roles.count("wipe"), 2)  # exactly: extras never fill other slots
        for role in ("removal", "ramp", "draw"):
            self.assertGreaterEqual(roles.count(role), build_deck.ROLE_TARGETS[role])
        self.assertEqual(sum(deck["basics"].values()), 27)
        self.assertEqual(set(deck["basics"]), {"Plains", "Forest"})
        self.assertEqual(deck["warnings"], [])

    def test_never_over_budget_and_fills_with_cheap_cards(self):
        pool = big_pool(price=0.10) + [card("Pricey Bomb", "synergy", 50.0, inclusion=0.99)]
        deck = self.build(pool, budget=10)
        self.assertNotIn("Pricey Bomb", [c["name"] for c in deck["cards"]])
        self.assertLessEqual(deck["spent"], 10)

    def test_fair_share_cap_stops_early_pricey_lands(self):
        pool = big_pool() + [card("Fancy Land", "land", 15.0, inclusion=0.95)]
        deck = self.build(pool, budget=30)
        self.assertNotIn("Fancy Land", [c["name"] for c in deck["cards"]])

    def test_owned_cards_free_and_preferred_within_a_role(self):
        pool = big_pool() + [card("My Removal", "removal", 20.0, inclusion=0.05, owned=True)]
        deck = self.build(pool, budget=5, owned_mode=True)
        mine = next(c for c in deck["cards"] if c["name"] == "My Removal")
        self.assertEqual(mine["cost"], 0.0)

    def test_owned_preference_only_in_owned_mode(self):
        pool = big_pool() + [card("My Removal", "removal", 0.10, inclusion=0.01, owned=False)]
        deck = self.build(pool)
        self.assertNotIn("My Removal", [c["name"] for c in deck["cards"]])

    def test_unlisted_owned_cards_only_used_when_short(self):
        pool = big_pool() + [card("Binder Filler", "synergy", 0.0, inclusion=0.0, owned=True, listed=False)]
        self.assertNotIn("Binder Filler", [c["name"] for c in self.build(pool, owned_mode=True)["cards"]])

        tiny = [card(f"Land {i}", "land", 0.1) for i in range(10)] + [
            card("Binder Filler", "synergy", 0.0, inclusion=0.0, owned=True, listed=False)]
        deck = self.build(tiny, budget=100, owned_mode=True)
        self.assertIn("Binder Filler", [c["name"] for c in deck["cards"]])
        self.assertTrue(any("EDHREC doesn't list" in w for w in deck["warnings"]))
        self.assertTrue(any("extra basic lands" in w for w in deck["warnings"]))

    def test_zero_budget_still_makes_100_cards(self):
        deck = self.build(big_pool(), budget=0)
        self.assertEqual(deck["cards"], [])
        self.assertEqual(sum(deck["basics"].values()), 99)


class BasicsTests(unittest.TestCase):
    def test_split_follows_spell_colors(self):
        spells = [{"color_identity": "G"}] * 6 + [{"color_identity": "W"}] * 2
        split = build_deck._basics_split("WG", spells, 20)
        self.assertEqual(sum(split.values()), 20)
        self.assertGreater(split["Forest"], split["Plains"])

    def test_colorless_commander_gets_wastes(self):
        self.assertEqual(build_deck._basics_split("", [], 30), {"Wastes": 30})


class CheckDeckTests(unittest.TestCase):
    def test_detects_problems(self):
        deck = {"cards": [card("A", "ramp", 1.0, identity="B"), card("A", "ramp", 1.0)], "basics": {}, "spent": 9.0}
        problems = " ".join(build_deck.check_deck(COMMANDER, deck, budget=5))
        for text in ("not 100", "more than once", "color identity", "over the"):
            self.assertIn(text, problems)


class CandidatePoolTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bulk = Path(tmp.name) / "bulk.jsonl.gz"
        write_bulk(bulk, [
            printing("cmd", "Test Commander", color_identity=["G", "W"], prices={"usd": "1.00"}),
            printing("a", "Green Card", color_identity=["G"], prices={"usd": "0.50"}),
            printing("b", "Black Card", color_identity=["B"], prices={"usd": "0.50"}),
            printing("c", "Unpriced Card", color_identity=["G"]),
            printing("d", "Banned Card", color_identity=["G"], legalities={"commander": "banned"}, prices={"usd": "1"}),
            printing("f", "Forest", type_line="Basic Land — Forest", color_identity=["G"], prices={"usd": "0.05"}),
            printing("o", "Owned Unpriced", color_identity=["W"]),
        ])
        card_db.build_db(bulk, Path(tmp.name) / "cards.sqlite")
        self.db = card_db.CardDB(Path(tmp.name) / "cards.sqlite")
        self.addCleanup(self.db.close)

    def test_filters_and_owned_flags(self):
        edhrec = [{"name": n, "inclusion": 0.5} for n in
                  ("Test Commander", "Green Card", "Black Card", "Unpriced Card", "Banned Card", "Forest")]
        commander = self.db.get("Test Commander")
        pool = build_deck.candidate_pool(commander, edhrec, self.db, owned={"Green Card", "Owned Unpriced"})
        by = {c["name"]: c for c in pool}
        self.assertEqual(set(by), {"Green Card", "Owned Unpriced"})
        self.assertEqual((by["Green Card"]["cost"], by["Green Card"]["listed"]), (0.0, True))
        self.assertEqual((by["Owned Unpriced"]["cost"], by["Owned Unpriced"]["listed"]), (0.0, False))


if __name__ == "__main__":
    unittest.main()
