import tempfile
import unittest
from pathlib import Path

import card_db
import fetch_staples
from test_card_db import SAMPLE, printing, prices, write_bulk

EXTRA = [
    printing("cheap_ub", "Cheap Dimir Card", color_identity=["B", "U"], edhrec_rank=5, prices=prices("0.50")),
    printing("pricey_ub", "Pricey Dimir Card", color_identity=["U", "B"], edhrec_rank=3, prices=prices("30")),
    printing("legend_ub", "Dimir Legend", type_line="Legendary Creature — Wizard",
             color_identity=["U", "B"], edhrec_rank=1, prices=prices("1")),
    printing("banned_ub", "Banned Dimir", color_identity=["U", "B"], edhrec_rank=2,
             legalities={"commander": "banned"}, prices=prices("1")),
    printing("norank_ub", "Unranked Dimir", color_identity=["U", "B"], prices=prices("1")),
]


class FetchStaplesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        bulk = Path(self.tmp.name) / "bulk.jsonl.gz"
        write_bulk(bulk, SAMPLE + EXTRA)
        db_path = Path(self.tmp.name) / "cards.sqlite"
        card_db.build_db(bulk, db_path)
        self.db = card_db.CardDB(db_path)
        self.addCleanup(self.db.close)

    def test_normalize_identity_uses_wubrg_order(self):
        self.assertEqual(fetch_staples.normalize_identity("gw"), "WG")
        self.assertEqual(fetch_staples.normalize_identity("BU"), "UB")
        self.assertEqual(fetch_staples.normalize_identity(""), "")

    def test_every_group_key_matches_its_letters(self):
        for key, (identity, _) in fetch_staples.GROUPS.items():
            self.assertEqual(sorted(key if key != "colorless" else ""), sorted(identity.lower()), key)

    def test_colorless_group_is_ranked_and_priced(self):
        names = [r["name"] for r in fetch_staples.build_group(self.db, "")]
        self.assertEqual(names[:2], ["Sol Ring", "Command Tower"])
        sol = fetch_staples.build_group(self.db, "")[0]
        self.assertEqual((sol["rank"], sol["usd"]), (1, 1.50))

    def test_pair_group_is_exact_identity_legal_and_ranked_only(self):
        names = [r["name"] for r in fetch_staples.build_group(self.db, "UB")]
        self.assertEqual(names, ["Dimir Legend", "Pricey Dimir Card", "Cheap Dimir Card"])
        self.assertNotIn("Banned Dimir", names)
        self.assertNotIn("Unranked Dimir", names)
        self.assertNotIn("Cheap Blue Spell", names)  # mono-blue is a different group

    def test_markdown_tiers_and_legendary_creatures_excluded(self):
        data = {key: [] for key in fetch_staples.GROUPS}
        data["ub"] = fetch_staples.build_group(self.db, "UB")
        text = fetch_staples.render_markdown(data)
        self.assertIn("Cheap Dimir Card $0.50", text)
        self.assertIn("Pricey Dimir Card $30.00", text)
        self.assertNotIn("Dimir Legend", text)
        under = next(line for line in text.splitlines() if line.startswith("| Under $2") and "Cheap Dimir" in line)
        self.assertNotIn("Pricey", under)


if __name__ == "__main__":
    unittest.main()
