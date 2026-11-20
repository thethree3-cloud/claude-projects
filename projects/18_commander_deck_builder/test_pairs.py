"""Two commanders: partners, "Partner with", Partner variants, Backgrounds, Doctors."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import build_deck
import card_db
import commander_lookup
import edhrec_client
import llm_deck
import validate_deck
from test_card_db import printing, write_bulk

LEGEND = "Legendary Creature — Human"
PARTNER = "Partner (You can have two commanders if both have partner.)"


def cards():
    out = [
        printing("pa", "Green Partner", type_line=LEGEND, color_identity=["G"], oracle_text=PARTNER,
                 edhrec_rank=10, prices={"usd": "3.00"}),
        printing("pb", "Blue Partner", type_line=LEGEND, color_identity=["U"], oracle_text="Flying\n" + PARTNER,
                 edhrec_rank=20, prices={"usd": "1.50"}),
        printing("px", "Xan, Twin", type_line=LEGEND, color_identity=["G"], edhrec_rank=30,
                 oracle_text="Partner with Yul, Twin (When this creature enters, target player may put Yul into their hand.)"),
        printing("py", "Yul, Twin", type_line=LEGEND, color_identity=["W"], edhrec_rank=31,
                 oracle_text="Partner with Xan, Twin (When this creature enters, target player may put Xan into their hand.)"),
        printing("ff1", "Friend One", type_line=LEGEND, color_identity=["G"], edhrec_rank=40,
                 oracle_text="Partner—Friends forever (You can have two commanders if both have this ability.)"),
        printing("ff2", "Friend Two", type_line=LEGEND, color_identity=["W"], edhrec_rank=41,
                 oracle_text="Partner—Friends forever (You can have two commanders if both have this ability.)"),
        printing("ch", "Bg Chooser", type_line=LEGEND, color_identity=["G"], edhrec_rank=50,
                 oracle_text="Choose a Background (You can have a Background as a second commander.)"),
        printing("bg", "Raised Somewhere", type_line="Legendary Enchantment — Background", color_identity=["W"],
                 oracle_text="Commander creatures you own have trample.", edhrec_rank=51, prices={"usd": "0.25"}),
        printing("bg2", "Other Background", type_line="Legendary Enchantment — Background", color_identity=["U"],
                 edhrec_rank=52),
        printing("comp", "Companion Person", type_line=LEGEND, color_identity=["U"], edhrec_rank=60,
                 oracle_text="Doctor's companion (You can have two commanders if the other is the Doctor.)"),
        printing("doc", "The Test Doctor", type_line="Legendary Creature — Time Lord Doctor", color_identity=["R"],
                 edhrec_rank=61),
        printing("leg", "Lone Legend", type_line=LEGEND, color_identity=["G"], edhrec_rank=70),
        printing("banp", "Banned Partner", type_line=LEGEND, color_identity=["G"], oracle_text=PARTNER,
                 legalities={"commander": "banned"}),
        printing("for", "Forest", type_line="Basic Land — Forest", color_identity=["G"]),
        printing("isl", "Island", type_line="Basic Land — Island", color_identity=["U"]),
    ]
    for i in range(70):
        out.append(printing(f"g{i}", f"Green Spell {i}", type_line="Sorcery", color_identity=["G"],
                            oracle_text="Draw a card.", cmc=2, prices={"usd": "0.50"}))
        out.append(printing(f"u{i}", f"Blue Spell {i}", type_line="Instant", color_identity=["U"],
                            oracle_text="Draw a card.", cmc=2, prices={"usd": "0.50"}))
    return out


class PairDBCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        patcher = mock.patch("edhrec_client.commander_popularity", return_value={})
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        cls.tmp = tempfile.TemporaryDirectory()
        bulk = Path(cls.tmp.name) / "bulk.jsonl.gz"
        write_bulk(bulk, cards())
        card_db.build_db(bulk, Path(cls.tmp.name) / "cards.sqlite")
        cls.db = card_db.CardDB(Path(cls.tmp.name) / "cards.sqlite")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def card(self, name):
        return self.db.get(name)


class PairRuleTests(PairDBCase):
    def test_pairing_tags(self):
        self.assertEqual(card_db.pairing(self.card("Green Partner")), {("partner",)})
        self.assertEqual(card_db.pairing(self.card("Blue Partner")), {("partner",)})  # keyword on a later line
        self.assertEqual(card_db.pairing(self.card("Xan, Twin")), {("with", "Yul, Twin")})
        self.assertEqual(card_db.pairing(self.card("Friend One")), {("variant", "friends forever")})
        self.assertEqual(card_db.pairing(self.card("Bg Chooser")), {("wants_background",)})
        self.assertEqual(card_db.pairing(self.card("Raised Somewhere")), {("background",)})
        self.assertEqual(card_db.pairing(self.card("Companion Person")), {("companion",)})
        self.assertEqual(card_db.pairing(self.card("The Test Doctor")), {("doctor",)})
        self.assertEqual(card_db.pairing(self.card("Lone Legend")), set())

    def test_legal_pairs(self):
        for a, b in [("Green Partner", "Blue Partner"), ("Xan, Twin", "Yul, Twin"), ("Friend One", "Friend Two"),
                     ("Bg Chooser", "Raised Somewhere"), ("Raised Somewhere", "Bg Chooser"),
                     ("Companion Person", "The Test Doctor")]:
            self.assertIsNone(card_db.pair_problem(self.card(a), self.card(b)), (a, b))

    def test_illegal_pairs(self):
        for a, b in [("Green Partner", "Lone Legend"), ("Xan, Twin", "Green Partner"),
                     ("Friend One", "Green Partner"), ("Raised Somewhere", "Other Background"),
                     ("Green Partner", "Raised Somewhere"), ("Green Partner", "Green Partner"),
                     ("Green Partner", "Banned Partner"), ("Companion Person", "Green Partner")]:
            self.assertIsNotNone(card_db.pair_problem(self.card(a), self.card(b)), (a, b))

    def test_partner_names(self):
        self.assertEqual(self.db.partner_names(self.card("Green Partner")), ["Blue Partner"])
        self.assertEqual(self.db.partner_names(self.card("Xan, Twin")), ["Yul, Twin"])
        self.assertEqual(self.db.partner_names(self.card("Bg Chooser")), ["Raised Somewhere", "Other Background"])
        self.assertEqual(self.db.partner_names(self.card("Raised Somewhere")), ["Bg Chooser"])
        self.assertEqual(self.db.partner_names(self.card("Lone Legend")), [])

    def test_combine(self):
        pair = card_db.combine_commanders([self.card("Green Partner"), self.card("Blue Partner")])
        self.assertEqual(pair["name"], "Green Partner + Blue Partner")
        self.assertEqual(pair["color_identity"], "UG")  # WUBRG order
        self.assertEqual(pair["usd"], 4.5)
        self.assertEqual([c["name"] for c in card_db.commander_members(pair)], ["Green Partner", "Blue Partner"])
        self.assertIn("Blue Partner: Flying", pair["oracle_text"])
        single = self.card("Lone Legend")
        self.assertIs(card_db.combine_commanders([single]), single)
        self.assertEqual(card_db.commander_members(single), [single])


class ResolvePairTests(PairDBCase):
    def test_fuzzy_partner_and_background_goes_second(self):
        names = [c["name"] for c in commander_lookup.resolve_pair("green partner", self.db, "blue")]
        self.assertEqual(names, ["Green Partner", "Blue Partner"])
        names = [c["name"] for c in commander_lookup.resolve_pair("Raised Somewhere", self.db, "chooser")]
        self.assertEqual(names, ["Bg Chooser", "Raised Somewhere"])

    def test_errors(self):
        with self.assertRaisesRegex(LookupError, "has no partner ability"):
            commander_lookup.resolve_pair("Lone Legend", self.db, "blue partner x")
        with self.assertRaisesRegex(LookupError, "can't be commanders together"):
            commander_lookup.resolve_pair("Green Partner", self.db, "Lone Legend")  # exact name, wrong kind
        with self.assertRaisesRegex(LookupError, "can't be a commander on its own"):
            commander_lookup.resolve_pair("Raised Somewhere", self.db)

    def test_load_commanders_costs_and_owned(self):
        page = {"commander": {"legal_commander": True, "num_decks": 500}, "cards": []}
        with mock.patch("edhrec_client.parse_commander_page", return_value=page):
            loaded = commander_lookup.load_commanders("Green Partner", self.db, "Blue Partner",
                                                      owned={"Blue Partner"}, fetch=lambda slug: {})
        self.assertEqual(loaded["commander_cost"], 3.0)  # Blue Partner owned
        self.assertEqual(loaded["sources"], ["blue-partner-green-partner", "staples"])  # empty page -> staples

    def test_thin_page_gets_staples_in_the_commanders_colors(self):
        page = {"commander": {"legal_commander": True, "num_decks": 3},
                "cards": [{"name": "Green Spell 0", "inclusion": 0.6}]}
        with mock.patch("edhrec_client.parse_commander_page", return_value=page):
            loaded = commander_lookup.load_commanders("Lone Legend", self.db, fetch=lambda slug: {})
        names = [c["name"] for c in loaded["cards"]]
        self.assertEqual(names[0], "Green Spell 0")  # real EDHREC card stays first
        staples = [c for c in loaded["cards"] if c.get("staple")]
        self.assertTrue(staples)
        self.assertNotIn("Green Spell 0", [c["name"] for c in staples])
        self.assertNotIn("Lone Legend", names)
        self.assertNotIn("Blue Spell 0", names)  # outside green
        self.assertTrue(all(c["inclusion"] <= 0.01 for c in staples))
        self.assertIn("EDHREC lists only 1 cards", loaded["warnings"][0])

    def test_missing_page_builds_from_staples_alone(self):
        def missing(slug):
            raise edhrec_client.EdhrecError("No EDHREC page for 'lone-legend'")
        loaded = commander_lookup.load_commanders("Lone Legend", self.db, fetch=missing)
        self.assertEqual(loaded["sources"], ["staples"])
        self.assertTrue(loaded["cards"])
        self.assertIn("EDHREC has no data for Lone Legend", loaded["warnings"][0])
        pool = build_deck.candidate_pool(loaded["commander"], loaded["cards"], self.db)
        deck = build_deck.build_deck(loaded["commander"], pool, 100)
        self.assertEqual(build_deck.check_deck(loaded["commander"], deck, 100), [])


def _page(name, cards, num_decks=100):
    views = [{"name": n, "num_decks": int(inc * 100), "potential_decks": 100} for n, inc in cards]
    return {"container": {"json_dict": {
        "card": {"name": name, "num_decks": num_decks, "legal_commander": True},
        "cardlists": [{"header": "Creatures", "cardviews": views}],
    }}}


class EdhrecPairTests(unittest.TestCase):
    def test_pair_slug_is_alphabetical(self):
        self.assertEqual(edhrec_client.pair_slug(["Tymna the Weaver", "Thrasios, Triton Hero"]),
                         "thrasios-triton-hero-tymna-the-weaver")

    def test_big_pair_page_used_alone(self):
        pages = {"a-b": _page("A // B", [("X", 0.5)], num_decks=500), "a": _page("A", [("Y", 0.9)])}
        got = edhrec_client.commander_cards(["A", "B"], fetch=lambda slug: pages[slug])
        self.assertEqual([c["name"] for c in got["cards"]], ["X"])
        self.assertEqual(got["sources"], ["a-b"])

    def test_thin_pair_page_mixes_in_single_pages(self):
        pages = {
            "a-b": _page("A // B", [("X", 0.5)], num_decks=8),
            "a": _page("A", [("X", 0.9), ("Y", 0.2)]),
            "b": _page("B", [("Y", 0.4), ("Z", 0.1)]),
        }
        got = edhrec_client.commander_cards(["A", "B"], fetch=lambda slug: pages[slug])
        inc = {c["name"]: c["inclusion"] for c in got["cards"]}
        self.assertEqual(inc, {"X": 0.5, "Y": 0.4, "Z": 0.1})  # pair page wins X; best single page for Y
        self.assertEqual(got["sources"], ["a-b", "a", "b"])

    def test_missing_pages_are_skipped_and_none_is_an_error(self):
        def fetch(slug):
            if slug == "a":
                return _page("A", [("Y", 0.2)])
            raise edhrec_client.EdhrecError("missing")  # no pair page, B is a Background
        got = edhrec_client.commander_cards(["A", "B"], fetch=fetch)
        self.assertEqual(got["sources"], ["a"])
        self.assertEqual(got["commander"]["num_decks"], 0)
        with self.assertRaises(edhrec_client.EdhrecError):
            edhrec_client.commander_cards(["A", "B"], fetch=lambda slug: (_ for _ in ()).throw(
                edhrec_client.EdhrecError("x")))

    def test_redirect_is_followed_and_cached(self):
        real = _page("A // B", [("X", 0.5)])
        answers = {"https://json.edhrec.com/pages/commanders/b-a.json": {"redirect": "/commanders/a-b"},
                   "https://json.edhrec.com/pages/commanders/a-b.json": real}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("edhrec_client._get_json", side_effect=lambda url, slug: answers[url]) as get:
            self.assertEqual(edhrec_client.fetch_commander_page("b-a", cache_dir=tmp), real)
            self.assertEqual(json.loads((Path(tmp) / "edhrec_b-a.json").read_text()), real)
            self.assertEqual(get.call_count, 2)


class PairDeckTests(PairDBCase):
    def pair(self):
        return card_db.combine_commanders([self.card("Green Partner"), self.card("Blue Partner")])

    def pool(self, commander):
        edhrec = [{"name": f"{color} Spell {i}", "inclusion": 0.5} for i in range(70) for color in ("Green", "Blue")]
        edhrec.append({"name": "Blue Partner", "inclusion": 0.9})  # a commander never lands in the 99
        return build_deck.candidate_pool(commander, edhrec, self.db)

    def test_pool_holds_both_colors_but_not_the_commanders(self):
        names = {c["name"] for c in self.pool(self.pair())}
        self.assertIn("Blue Spell 0", names)
        self.assertNotIn("Blue Partner", names)

    def test_build_has_98_cards_plus_two_commanders_and_validates(self):
        commander = self.pair()
        deck = build_deck.build_deck(commander, self.pool(commander), 100, commander_cost=4.5)
        self.assertEqual(len(deck["cards"]) + sum(deck["basics"].values()), 98)
        self.assertEqual(build_deck.check_deck(commander, deck, 100), [])
        text = build_deck.import_text(commander, deck)
        self.assertEqual(text.splitlines()[:2], ["1 Green Partner", "1 Blue Partner"])
        result = validate_deck.validate_text(text, self.db, budget=100)  # pair found from the list itself
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["commander"], "Green Partner + Blue Partner")
        self.assertEqual(result["stats"]["cards"], 100)

    def test_llm_assemble_fills_98(self):
        commander = self.pair()
        by_id = {"c1": {"name": "Green Spell 0", "role": "draw", "cost": 0.5, "color_identity": "G"}}
        picks = [SimpleNamespace(id="c1", reason="ok")]
        deck, problems = llm_deck.assemble(commander, by_id, picks)
        self.assertEqual(problems, [])
        self.assertEqual(len(deck["cards"]) + sum(deck["basics"].values()), 98)
        self.assertIn("partners", llm_deck.first_prompt(commander, 100, 4.5, "table"))
        self.assertIn("98 cards plus the commanders", llm_deck.first_prompt(commander, 100, 4.5, "table"))
        self.assertIn("The commanders cost $4.50, so", llm_deck.first_prompt(commander, 100, 4.5, "table"))
        single = self.card("Lone Legend")
        self.assertIn("The commander costs $1.00, so", llm_deck.first_prompt(single, 100, 1.0, "table"))


class PairValidatorTests(PairDBCase):
    def text(self, first, second, spells=98, forests=30):
        lines = [f"1 {first}", f"1 {second}", f"{forests} Forest"]
        lines += [f"1 Green Spell {i}" for i in range(spells - forests)]
        return "\n".join(lines)

    def test_background_pair_passes(self):
        result = validate_deck.validate_text(self.text("Bg Chooser", "Raised Somewhere"), self.db)
        self.assertTrue(result["ok"], result["errors"])

    def test_second_card_not_a_partner_stays_in_the_99(self):
        result = validate_deck.validate_text(self.text("Green Partner", "Green Spell 69"), self.db)
        self.assertEqual(result["commander"], "Green Partner")
        self.assertTrue(result["ok"], result["errors"])

    def test_explicit_illegal_partner_is_an_error(self):
        result = validate_deck.validate_text(self.text("Green Partner", "Lone Legend"), self.db,
                                             commander_name="Green Partner", partner_name="Lone Legend")
        self.assertFalse(result["ok"])
        self.assertTrue(any("can't be commanders together" in e for e in result["errors"]), result["errors"])

    def test_explicit_commander_turns_off_pair_guessing(self):
        result = validate_deck.validate_text(self.text("Green Partner", "Blue Partner"), self.db,
                                             commander_name="Green Partner")
        self.assertFalse(result["ok"])  # Blue Partner is then a blue card in a green deck
        self.assertTrue(any("outside" in e for e in result["errors"]), result["errors"])

    def test_second_commander_colors_allowed(self):
        lines = self.text("Green Partner", "Blue Partner").splitlines()
        lines[-1] = "1 Blue Spell 0"
        result = validate_deck.validate_text("\n".join(lines), self.db)
        self.assertTrue(result["ok"], result["errors"])


if __name__ == "__main__":
    unittest.main()
