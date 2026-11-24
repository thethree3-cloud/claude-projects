import json
import tempfile
import unittest
from pathlib import Path

import card_db
import sets
from test_card_db import printing, write_bulk

SCRYFALL = {"data": [
    {"code": "trk", "name": "Star Trek", "released_at": "2026-11-13", "set_type": "expansion", "card_count": 3,
     "icon_svg_uri": "https://svgs/trk.svg", "parent_set_code": None, "digital": False},
    {"code": "trc", "name": "Star Trek Commander", "released_at": "2026-11-13", "set_type": "commander",
     "card_count": 1, "icon_svg_uri": "https://svgs/trc.svg", "parent_set_code": "trk", "digital": False},
    {"code": "ttrk", "name": "Star Trek Tokens", "released_at": "2026-11-13", "set_type": "token",
     "parent_set_code": "trk", "digital": False},
    {"code": "old", "name": "Old Set", "released_at": "2010-01-01", "set_type": "expansion", "parent_set_code": None,
     "digital": False},
]}


class SetTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        bulk = self.dir / "bulk.jsonl.gz"
        write_bulk(bulk, [
            printing("ds9", "Deep Space 9", set="trk", set_name="Star Trek", collector_number="263", rarity="mythic",
                     prices={"usd": "40.00", "usd_foil": "60.00"}, edhrec_rank=500),
            printing("ds9", "Deep Space 9", set="trk", set_name="Star Trek", collector_number="556", rarity="mythic",
                     border_color="borderless", frame_effects=["showcase"], prices={"usd_foil": "178.00"}),
            printing("tri", "Tribble", set="trk", set_name="Star Trek", collector_number="1", rarity="common",
                     prices={"usd": "0.20"}, edhrec_rank=20),
            printing("cmd", "Picard", set="trc", set_name="Star Trek Commander", collector_number="1", rarity="mythic",
                     prices={"usd": "5.00"}),
            printing("tok", "Tribble Token Card", set="ttrk", set_name="Star Trek Tokens", prices={"usd": "0.10"}),
            printing("o", "Old Card", set="old", set_name="Old Set", released_at="2010-01-01", prices={"usd": "1.00"}),
        ])
        card_db.build_db(bulk, self.dir / "c.sqlite")
        self.db = card_db.CardDB(self.dir / "c.sqlite")
        self.addCleanup(self.db.close)
        self.meta = sets.fetch_sets(cache=self.dir / "sets.json", get=lambda url: SCRYFALL)
        self.sets = sets.listed_sets(self.db, self.meta)

    def test_fetch_is_cached(self):
        self.assertEqual(self.meta["trc"]["parent"], "trk")
        again = sets.fetch_sets(cache=self.dir / "sets.json", get=lambda url: self.fail("not cached"))
        self.assertEqual(again, self.meta)

    def test_listed_sets_skip_tokens_and_order_newest_first(self):
        codes = [s["code"] for s in self.sets]
        self.assertNotIn("ttrk", codes)
        self.assertEqual(codes[-1], "old")
        trk = next(s for s in self.sets if s["code"] == "trk")
        self.assertEqual((trk["printings"], trk["value"], trk["icon"]), (3, 40.2, "https://svgs/trk.svg"))

    def test_family_search_cards_and_summary(self):
        self.assertEqual([s["code"] for s in sets.family("trc", self.sets)], ["trk", "trc"])
        self.assertEqual([s["code"] for s in sets.search("star trek", self.sets)][:2], ["trk", "trc"] if
                         self.sets[0]["code"] == "trk" else ["trc", "trk"])
        cards = sets.set_cards(self.db, ["trk"])
        top = sorted(cards, key=sets.SORTS["Most valuable"])[0]
        self.assertEqual((top["collector_number"], top["top_price"]), ("556", 178.0))  # showcase foil
        normal = sorted(cards, key=sets.SORTS["Normal price"])[0]
        self.assertEqual(normal["collector_number"], "263")
        played = sorted(cards, key=sets.SORTS["Most played in Commander"])[0]
        self.assertEqual(played["name"], "Tribble")
        sm = sets.summary(cards)
        self.assertEqual((sm["printings"], sm["priced"], sm["total"], sm["over_10"], sm["unique_cards"]),
                         (3, 2, 40.2, 1, 2))
        self.assertEqual(sm["top"]["top_price"], 178.0)


if __name__ == "__main__":
    unittest.main()
