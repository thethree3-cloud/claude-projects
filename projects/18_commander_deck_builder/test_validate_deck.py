import tempfile
import unittest
from pathlib import Path

import card_db
import validate_deck
from test_card_db import printing, write_bulk

LEGEND = "Legendary Creature — Elf"


def cards():
    out = [
        printing("cmd", "Green Commander", type_line=LEGEND, color_identity=["G"], cmc=3, prices={"usd": "2.00"}),
        printing("pw", "Walker Commander", type_line="Legendary Planeswalker — Test",
                 oracle_text="Walker Commander can be your commander.", color_identity=["G"]),
        printing("gri", "Grist Like", type_line="Legendary Planeswalker — Grist", color_identity=["G"],
                 oracle_text="As long as Grist Like isn't on the battlefield, it's a 1/1 Insect creature in addition to its other types."),
        printing("lpw", "Plain Walker", type_line="Legendary Planeswalker — Test", color_identity=["G"]),
        printing("ench", "Not A Commander", type_line="Enchantment", color_identity=["G"]),
        printing("for", "Forest", type_line="Basic Land — Forest", color_identity=["G"]),
        printing("isl", "Island", type_line="Basic Land — Island", color_identity=["U"]),
        printing("rats", "Relentless Rats", type_line="Creature — Rat", color_identity=["G"],
                 oracle_text="A deck can have any number of cards named Relentless Rats."),
        printing("dw", "Seven Dwarves", type_line="Creature — Dwarf", color_identity=["G"],
                 oracle_text="A deck can have up to seven cards named Seven Dwarves."),
        printing("ban", "Banned Card", color_identity=["G"], legalities={"commander": "banned"}),
        printing("blue", "Blue Card", color_identity=["U"]),
        printing("gc", "Big Changer", color_identity=["G"], game_changer=True, prices={"usd": "10.00"}),
        printing("np", "No Price Card", color_identity=["G"]),
        printing("fat", "Huge Spell", type_line="Sorcery", color_identity=["G"], cmc=9, prices={"usd": "1.00"}),
    ]
    roles = {
        "ramp": "{T}: Add {G}.",
        "draw": "Draw two cards.",
        "removal": "Destroy target creature.",
        "filler": "Trample.",
    }
    for i in range(30):
        out.append(printing(f"big{i}", f"Big {i}", type_line="Creature — Giant", color_identity=["G"], cmc=7))
    for role, text in roles.items():
        for i in range(70):
            out.append(printing(f"{role}{i}", f"{role.title()} {i}", type_line="Artifact" if role == "ramp" else "Sorcery",
                                oracle_text=text, color_identity=["G"], cmc=2, prices={"usd": "0.50"}))
    return out


def deck(*extra, commander="Green Commander", forests=36, ramp=10, draw=10, removal=8, filler=None):
    """A legal 100-card list by default; ``extra`` lines replace filler slots."""
    if filler is None:
        filler = 99 - forests - ramp - draw - removal - sum(n for n, _ in extra)
    lines = [f"1 {commander}", f"{forests} Forest"]
    lines += [f"1 Ramp {i}" for i in range(ramp)] + [f"1 Draw {i}" for i in range(draw)]
    lines += [f"1 Removal {i}" for i in range(removal)] + [f"1 Filler {i}" for i in range(filler)]
    lines += [f"{n} {name}" for n, name in extra]
    return "\n".join(lines)


class ValidateCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        bulk = Path(cls.tmp.name) / "bulk.jsonl.gz"
        write_bulk(bulk, cards())
        card_db.build_db(bulk, Path(cls.tmp.name) / "cards.sqlite")
        cls.db = card_db.CardDB(Path(cls.tmp.name) / "cards.sqlite")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def check(self, text, **kwargs):
        return validate_deck.validate_text(text, self.db, **kwargs)

    def assertError(self, result, fragment):
        self.assertFalse(result["ok"])
        self.assertTrue(any(fragment in e for e in result["errors"]), result["errors"])


class ParseTests(unittest.TestCase):
    def test_formats(self):
        text = """Commander
1 Green Commander
// a comment

Deck
1x Sol Ring (CMM) 1
1 Arcane Signet (C21) 12 *F*
Forest
10 Forest
Sideboard:
1 Not Counted"""
        self.assertEqual(validate_deck.parse_decklist(text), [
            (1, "Green Commander"), (1, "Sol Ring"), (1, "Arcane Signet"), (1, "Forest"), (10, "Forest"),
        ])

    def test_double_faced_name_kept_whole(self):
        self.assertEqual(validate_deck.parse_decklist("1 Esika, God of the Tree // The Prismatic Bridge"),
                         [(1, "Esika, God of the Tree // The Prismatic Bridge")])


class LegalDeckTests(ValidateCase):
    def test_legal_deck_passes_with_stats(self):
        r = self.check(deck())
        self.assertTrue(r["ok"], r["errors"])
        self.assertEqual(r["warnings"], [])
        self.assertEqual((r["stats"]["cards"], r["stats"]["lands"]), (100, 36))
        self.assertEqual(r["commander"], "Green Commander")

    def test_commander_flag_when_list_has_no_commander_line(self):
        text = deck().split("\n", 1)[1]  # drop the commander line
        self.assertTrue(self.check(text, commander_name="Green Commander")["ok"])

    def test_planeswalker_that_says_it_can_be_commander(self):
        self.assertTrue(self.check(deck(commander="Walker Commander"))["ok"])

    def test_planeswalker_that_is_a_creature_off_the_battlefield(self):
        self.assertTrue(self.check(deck(commander="Grist Like"))["ok"])

    def test_any_number_and_up_to_seven(self):
        self.assertTrue(self.check(deck((20, "Relentless Rats"), (7, "Seven Dwarves")))["ok"])


class ErrorTests(ValidateCase):
    def test_unknown_card_with_suggestion(self):
        self.assertError(self.check(deck((1, "Relentles Rats"))), "did you mean 'Relentless Rats'")

    def test_not_a_commander(self):
        self.assertError(self.check(deck(commander="Not A Commander")), "can't be a commander")
        self.assertError(self.check(deck(commander="Plain Walker")), "can't be a commander")

    def test_wrong_size(self):
        self.assertError(self.check(deck(filler=0)), "exactly 100")
        self.assertError(self.check(deck((1, "Huge Spell"), filler=35)), "101 cards")

    def test_duplicates(self):
        self.assertError(self.check(deck((2, "Big 0"))), "2 copies of Big 0")
        self.assertError(self.check(deck((8, "Seven Dwarves"))), "only 7 allowed")

    def test_off_color_including_basics(self):
        self.assertError(self.check(deck((1, "Blue Card"))), "Blue Card is outside")
        self.assertError(self.check(deck((1, "Island"))), "Island is outside")

    def test_banned(self):
        self.assertError(self.check(deck((1, "Banned Card"))), "banned in Commander")

    def test_budget_counts_commander_and_skips_owned_and_basics(self):
        # 2.00 commander + 63 spells x 0.50 = 33.50; basics free.
        self.assertTrue(self.check(deck(), budget=33.50)["ok"])
        self.assertError(self.check(deck(), budget=33.49), "Costs $33.50")
        self.assertTrue(self.check(deck(), budget=31.50, owned={"Green Commander"})["ok"])

    def test_bracket_game_changers(self):
        text = deck((1, "Big Changer"))
        self.assertError(self.check(text, bracket=2), "bracket 2 allows 0")
        self.assertTrue(self.check(text, bracket=3)["ok"])
        self.assertEqual(self.check(text)["stats"]["lowest_bracket"], "3")

    def test_empty_list(self):
        self.assertError(self.check(""), "empty")


class WarningTests(ValidateCase):
    def warnings(self, text, **kwargs):
        r = self.check(text, **kwargs)
        self.assertTrue(r["ok"], r["errors"])
        return " ".join(r["warnings"])

    def test_land_count(self):
        self.assertIn("30 lands", self.warnings(deck(forests=30)))

    def test_low_roles(self):
        w = self.warnings(deck(ramp=2, draw=3, removal=1))
        for text in ("Only 2 ramp", "Only 3 draw", "Only 1 removal"):
            self.assertIn(text, w)

    def test_high_curve(self):
        # 30 seven-drops + 33 two-drops -> average 4.38 (over 4).
        heavy = deck(*[(1, f"Big {i}") for i in range(30)], ramp=0, draw=0, removal=0)
        self.assertIn("Average mana value 4.38", self.warnings(heavy))
        self.assertNotIn("mana value", self.warnings(deck()))

    def test_unpriced_cards_with_budget(self):
        self.assertIn("No price known for 1 cards", self.warnings(deck((1, "No Price Card")), budget=100))


if __name__ == "__main__":
    unittest.main()
