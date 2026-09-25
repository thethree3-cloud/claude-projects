import tempfile
import unittest
from unittest import mock

import scryfall_prices


def _card(name, usd, type_line="Artifact"):
    return {"name": name, "type_line": type_line, "prices": {"usd": usd, "usd_foil": None}}


class LookupCardsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        sleep = mock.patch("scryfall_prices.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_default_price_used_when_present(self):
        response = {"data": [_card("Mind Stone", "0.28")]}
        with mock.patch("scryfall_prices._request", return_value=response):
            info = scryfall_prices.lookup_cards(["Mind Stone"], cache_dir=self.tmp.name)
        self.assertEqual(info["Mind Stone"]["usd"], 0.28)
        self.assertEqual(info["Mind Stone"]["price_source"], "default")

    def test_falls_back_to_cheapest_printing(self):
        def fake_request(url, body=None):
            if "collection" in url:
                return {"data": [_card("Sol Ring", None)]}
            return {"data": [_card("Sol Ring", "1.42"), _card("Sol Ring", "12.00")]}

        with mock.patch("scryfall_prices._request", side_effect=fake_request):
            info = scryfall_prices.lookup_cards(["Sol Ring"], cache_dir=self.tmp.name)
        self.assertEqual(info["Sol Ring"]["usd"], 1.42)
        self.assertEqual(info["Sol Ring"]["price_source"], "cheapest_printing")

    def test_unknown_name_omitted(self):
        with mock.patch("scryfall_prices._request", return_value={"data": []}):
            info = scryfall_prices.lookup_cards(["Not A Card"], cache_dir=self.tmp.name)
        self.assertEqual(info, {})

    def test_second_call_uses_cache(self):
        response = {"data": [_card("Mind Stone", "0.28")]}
        with mock.patch("scryfall_prices._request", return_value=response) as request:
            scryfall_prices.lookup_cards(["Mind Stone"], cache_dir=self.tmp.name)
            scryfall_prices.lookup_cards(["Mind Stone"], cache_dir=self.tmp.name)
        self.assertEqual(request.call_count, 1)

    def test_dfc_front_face_name_matches_full_name(self):
        response = {"data": [_card("Esika, God of the Tree // The Prismatic Bridge", "0.5", "Legendary Creature")]}
        with mock.patch("scryfall_prices._request", return_value=response):
            info = scryfall_prices.lookup_cards(["Esika, God of the Tree"], cache_dir=self.tmp.name)
        self.assertEqual(info["Esika, God of the Tree"]["usd"], 0.5)


if __name__ == "__main__":
    unittest.main()
