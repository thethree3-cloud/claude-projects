import unittest
from unittest import mock

import commander_lookup


def _card(name, inclusion, synergy=0.0, role="Creature", gc=False, hs=False):
    return {
        "name": name,
        "role": role,
        "inclusion": inclusion,
        "synergy": synergy,
        "num_decks": 0,
        "potential_decks": 0,
        "high_synergy": hs,
        "game_changer": gc,
    }


def _info(usd, type_line="Creature"):
    return {"usd": usd, "type_line": type_line, "price_source": "default" if usd is not None else None}


def _rows():
    cards = [
        _card("Cheap Popular", 0.9, 0.1),
        _card("Pricey Popular", 0.8, 0.5, role="Enchantment", gc=True),
        _card("Cheap Synergy", 0.3, 0.6, hs=True),
        _card("Unpriced", 0.5, 0.0),
        _card("Forest", 0.95, 0.0, role="Land"),
    ]
    info = {
        "Cheap Popular": _info(0.5),
        "Pricey Popular": _info(70.0),
        "Cheap Synergy": _info(1.0),
        "Unpriced": _info(None),
        "Forest": _info(0.1, "Basic Land"),
    }
    return commander_lookup.build_rows(cards, info)


class BuildRowsTests(unittest.TestCase):
    def test_role_falls_back_to_type_line(self):
        rows = commander_lookup.build_rows(
            [_card("Only In Top Cards", 0.4, role=None)], {"Only In Top Cards": _info(1.0, "Artifact — Equipment")}
        )
        self.assertEqual(rows[0]["role"], "Artifact")

    def test_cards_scryfall_cannot_find_are_dropped(self):
        rows = commander_lookup.build_rows([_card("Ghost", 0.4)], {})
        self.assertEqual(rows, [])


class RankRowsTests(unittest.TestCase):
    def names(self, rows):
        return [r["name"] for r in rows]

    def test_sorts_by_inclusion_by_default_and_drops_basics(self):
        ranked = commander_lookup.rank_rows(_rows())
        self.assertEqual(self.names(ranked)[0], "Cheap Popular")
        self.assertNotIn("Forest", self.names(ranked))

    def test_include_basics(self):
        ranked = commander_lookup.rank_rows(_rows(), include_basics=True)
        self.assertEqual(self.names(ranked)[0], "Forest")

    def test_sort_by_synergy(self):
        ranked = commander_lookup.rank_rows(_rows(), sort="synergy")
        self.assertEqual(self.names(ranked)[0], "Cheap Synergy")

    def test_max_price_filters_expensive_and_unpriced(self):
        ranked = commander_lookup.rank_rows(_rows(), max_price=5)
        self.assertEqual(sorted(self.names(ranked)), ["Cheap Popular", "Cheap Synergy"])

    def test_unpriced_kept_without_price_cap(self):
        self.assertIn("Unpriced", self.names(commander_lookup.rank_rows(_rows())))

    def test_role_filter_is_case_insensitive(self):
        ranked = commander_lookup.rank_rows(_rows(), role="enchantment")
        self.assertEqual(self.names(ranked), ["Pricey Popular"])

    def test_min_inclusion_and_limit(self):
        self.assertEqual(len(commander_lookup.rank_rows(_rows(), min_inclusion=0.6)), 2)
        self.assertEqual(len(commander_lookup.rank_rows(_rows(), limit=1)), 1)

    def test_bad_sort_raises(self):
        with self.assertRaises(ValueError):
            commander_lookup.rank_rows(_rows(), sort="price")


class FormatTests(unittest.TestCase):
    def test_table_contains_prices_flags_and_total(self):
        commander = {"name": "Test Cmdr", "num_decks": 1234, "color_identity": ["B", "G"]}
        text = commander_lookup.format_table(commander, commander_lookup.rank_rows(_rows()))
        self.assertIn("Test Cmdr — top cards from 1,234 decks", text)
        self.assertIn("game changer", text)
        self.assertIn("$70.00", text)
        self.assertIn("n/a", text)
        self.assertIn("Total for listed cards: $71.50 (1 unpriced)", text)


class ResolveTests(unittest.TestCase):
    def test_returns_exact_name(self):
        with mock.patch("commander_lookup.scryfall_prices._request", return_value={"name": "Muldrotha, the Gravetide"}):
            self.assertEqual(commander_lookup.resolve_commander("muldrotha"), "Muldrotha, the Gravetide")


if __name__ == "__main__":
    unittest.main()
