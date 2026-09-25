import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import edhrec_client

FIXTURE = Path(__file__).parent / "fixtures" / "edhrec_muldrotha_trimmed.json"


def _view(name, num, potential, synergy=0.0):
    return {"name": name, "num_decks": num, "potential_decks": potential, "synergy": synergy}


def _page(cardlists, card=None):
    card = card or {"name": "Test Commander", "color_identity": ["G"], "num_decks": 100}
    return {"container": {"json_dict": {"card": card, "cardlists": cardlists}}}


class SlugifyTests(unittest.TestCase):
    def test_comma_and_spaces(self):
        self.assertEqual(
            edhrec_client.slugify("Muldrotha, the Gravetide"), "muldrotha-the-gravetide"
        )

    def test_apostrophes_removed(self):
        self.assertEqual(
            edhrec_client.slugify("Atraxa, Praetors' Voice"), "atraxa-praetors-voice"
        )
        self.assertEqual(edhrec_client.slugify("Kaya’s Wrath"), "kayas-wrath")

    def test_double_faced_uses_front_face(self):
        self.assertEqual(
            edhrec_client.slugify("Esika, God of the Tree // The Prismatic Bridge"),
            "esika-god-of-the-tree",
        )

    def test_accents_stripped(self):
        self.assertEqual(edhrec_client.slugify("Lim-Dûl the Necromancer"), "lim-dul-the-necromancer")


class ParseTests(unittest.TestCase):
    def test_inclusion_is_num_over_potential(self):
        page = _page([{"header": "Creatures", "cardviews": [_view("Eternal Witness", 13200, 25251)]}])
        card = edhrec_client.parse_commander_page(page)["cards"][0]
        self.assertAlmostEqual(card["inclusion"], 13200 / 25251)
        self.assertEqual(card["role"], "Creature")

    def test_zero_potential_decks_does_not_crash(self):
        page = _page([{"header": "Creatures", "cardviews": [_view("Odd Card", 0, 0)]}])
        self.assertEqual(edhrec_client.parse_commander_page(page)["cards"][0]["inclusion"], 0.0)

    def test_merges_cards_across_lists_and_sets_flags(self):
        page = _page(
            [
                {"header": "High Synergy Cards", "cardviews": [_view("Rhystic Study", 50, 100, 0.3)]},
                {"header": "Game Changers", "cardviews": [_view("Rhystic Study", 50, 100, 0.3)]},
                {"header": "Enchantments", "cardviews": [_view("Rhystic Study", 50, 100, 0.3)]},
            ]
        )
        cards = edhrec_client.parse_commander_page(page)["cards"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["role"], "Enchantment")
        self.assertTrue(cards[0]["high_synergy"])
        self.assertTrue(cards[0]["game_changer"])

    def test_card_only_in_cross_cut_list_has_no_role(self):
        page = _page([{"header": "Top Cards", "cardviews": [_view("Mystery", 10, 100)]}])
        self.assertIsNone(edhrec_client.parse_commander_page(page)["cards"][0]["role"])

    def test_bad_format_raises(self):
        with self.assertRaises(edhrec_client.EdhrecError):
            edhrec_client.parse_commander_page({"unexpected": True})

    def test_real_page_shape(self):
        parsed = edhrec_client.parse_commander_page(json.loads(FIXTURE.read_text()))
        self.assertEqual(parsed["commander"]["name"], "Muldrotha, the Gravetide")
        self.assertEqual(sorted(parsed["commander"]["color_identity"]), ["B", "G", "U"])
        self.assertTrue(parsed["cards"])
        for card in parsed["cards"]:
            self.assertTrue(0.0 <= card["inclusion"] <= 1.0, card)


class FetchCacheTests(unittest.TestCase):
    def test_fresh_cache_skips_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "edhrec_foo.json").write_text(json.dumps({"cached": True}))
            with mock.patch("urllib.request.urlopen") as urlopen:
                page = edhrec_client.fetch_commander_page("foo", cache_dir=tmp)
            urlopen.assert_not_called()
            self.assertEqual(page, {"cached": True})


if __name__ == "__main__":
    unittest.main()
