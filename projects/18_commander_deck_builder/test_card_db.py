import gzip
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import card_db


def printing(oracle_id, name, **overrides):
    """A minimal Scryfall-style printing."""
    card = {
        "object": "card",
        "oracle_id": oracle_id,
        "name": name,
        "layout": "normal",
        "set": "tst",
        "set_type": "expansion",
        "collector_number": "1",
        "type_line": "Artifact",
        "oracle_text": "",
        "color_identity": [],
        "cmc": 1,
        "legalities": {"commander": "legal"},
        "prices": {"usd": None, "usd_foil": None, "usd_etched": None},
        "promo": False,
        "digital": False,
    }
    card.update(overrides)
    return card


def prices(usd=None, foil=None):
    return {"usd": usd, "usd_foil": foil, "usd_etched": None}


SAMPLE = [
    # Sol Ring: default printing has no USD; cheapest non-promo wins over a cheaper promo/digital.
    printing("sol", "Sol Ring", set="frc", edhrec_rank=None, prices=prices(None, "5.00")),
    printing("sol", "Sol Ring", set="cmm", collector_number="1", edhrec_rank=1, prices=prices("1.50")),
    printing("sol", "Sol Ring", set="c21", prices=prices("2.00")),
    printing("sol", "Sol Ring", set="sld", promo=True, prices=prices("0.90")),
    printing("sol", "Sol Ring", set="arena", digital=True, prices=prices("0.10")),
    # Only a promo printing has a plain USD price.
    printing("tower", "Command Tower", promo=True, prices=prices("0.50", "1.00"), edhrec_rank=2),
    # Foil-only pricing.
    printing("foily", "Foily Card", prices=prices(None, "3.00")),
    printing("free", "Priceless Card"),
    # Double-faced: data lives on the faces.
    printing(
        "esika",
        "Esika, God of the Tree // The Prismatic Bridge",
        layout="modal_dfc",
        type_line=None,
        oracle_text=None,
        color_identity=["G", "W"],
        card_faces=[
            {"type_line": "Legendary Creature — God", "oracle_text": "Vigilance"},
            {"type_line": "Legendary Artifact", "oracle_text": "Reveal cards"},
        ],
        prices=prices("0.60"),
    ),
    printing("mul", "Muldrotha, the Gravetide", type_line="Legendary Creature — Elemental Avatar",
             color_identity=["B", "G", "U"], cmc=6, edhrec_rank=1137, prices=prices("0.80")),
    printing("lotus", "Black Lotus", legalities={"commander": "banned"}, prices=prices("9000")),
    printing("cheap_u", "Cheap Blue Spell", color_identity=["U"], edhrec_rank=50, prices=prices("0.20")),
    printing("pricey_u", "Pricey Blue Spell", color_identity=["U"], edhrec_rank=10, prices=prices("40.00")),
    # Not real cards: token, no oracle id, memorabilia, digital-only.
    printing("tok", "Goblin", layout="token", prices=prices("0.01")),
    printing(None, "Art Card", layout="art_series"),
    printing("mem", "Memorabilia Card", set_type="memorabilia", prices=prices("0.01")),
    printing("dig", "Digital Only", digital=True, prices=prices("0.01")),
]


def write_bulk(path, cards=SAMPLE):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for card in cards:
            f.write(json.dumps(card) + "\n")


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)


class DownloadUrlTests(unittest.TestCase):
    def test_new_key(self):
        self.assertEqual(card_db.bulk_download_url({"jsonl_download_uri": "https://x/a.jsonl.gz"}), "https://x/a.jsonl.gz")

    def test_old_key_fallback(self):
        self.assertEqual(card_db.bulk_download_url({"download_uri": "https://x/a.json"}), "https://x/a.json")

    def test_missing_raises(self):
        with self.assertRaises(card_db.BulkDataError):
            card_db.bulk_download_url({"object": "bulk_data"})


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.cards = card_db.aggregate_cards(json.dumps(c) for c in SAMPLE)

    def test_one_row_per_oracle_id_and_non_cards_skipped(self):
        names = {c["name"] for c in self.cards.values()}
        self.assertNotIn("Goblin", names)
        self.assertNotIn("Art Card", names)
        self.assertNotIn("Memorabilia Card", names)
        self.assertNotIn("Digital Only", names)
        self.assertEqual(len([c for c in self.cards.values() if c["name"] == "Sol Ring"]), 1)

    def test_cheapest_non_promo_non_digital_price_wins(self):
        sol = self.cards["sol"]
        self.assertEqual(sol["usd"], 1.50)
        self.assertEqual(sol["price_source"], "non_promo")
        self.assertEqual(sol["price_printing"], "cmm #1")

    def test_edhrec_rank_taken_from_any_printing(self):
        self.assertEqual(self.cards["sol"]["edhrec_rank"], 1)

    def test_promo_used_when_no_non_promo_price(self):
        self.assertEqual((self.cards["tower"]["usd"], self.cards["tower"]["price_source"]), (0.50, "promo"))

    def test_foil_only_price_is_last_resort(self):
        self.assertEqual((self.cards["foily"]["usd"], self.cards["foily"]["price_source"]), (3.00, "foil"))

    def test_no_price_stays_none(self):
        self.assertIsNone(self.cards["free"]["usd"])

    def test_double_faced_card_reads_faces(self):
        esika = self.cards["esika"]
        self.assertIn("Legendary Creature — God", esika["type_line"])
        self.assertIn("Vigilance", esika["oracle_text"])
        self.assertEqual(esika["front_name_lower"], "esika, god of the tree")

    def test_color_identity_in_wubrg_order(self):
        self.assertEqual(self.cards["esika"]["color_identity"], "WG")
        self.assertEqual(self.cards["mul"]["color_identity"], "UBG")
        self.assertEqual(self.cards["sol"]["color_identity"], "")

    def test_commander_legality(self):
        self.assertEqual(self.cards["lotus"]["legal_commander"], 0)
        self.assertEqual(self.cards["sol"]["legal_commander"], 1)


class BuildAndQueryTests(TempDirCase):
    def setUp(self):
        super().setUp()
        bulk = self.dir / "bulk.jsonl.gz"
        write_bulk(bulk)
        self.db_path = self.dir / "cards.sqlite"
        card_db.build_db(bulk, self.db_path, updated_at="2026-09-24T00:00:00Z")
        self.db = card_db.CardDB(self.db_path)
        self.addCleanup(self.db.close)

    def test_meta_and_count(self):
        self.assertEqual(self.db.meta()["updated_at"], "2026-09-24T00:00:00Z")
        self.assertEqual(self.db.count(), int(self.db.meta()["card_count"]))

    def test_get_is_case_insensitive_and_matches_front_face(self):
        self.assertEqual(self.db.get("sol ring")["usd"], 1.50)
        self.assertEqual(self.db.get("Esika, God of the Tree")["name"], "Esika, God of the Tree // The Prismatic Bridge")
        self.assertIsNone(self.db.get("Nope"))

    def test_get_many_omits_unknown(self):
        found = self.db.get_many(["Sol Ring", "Nope", "Command Tower"])
        self.assertEqual(sorted(found), ["Command Tower", "Sol Ring"])

    def test_find_name_exact_substring_and_typo(self):
        self.assertEqual(self.db.find_name("Sol Ring"), "Sol Ring")
        self.assertEqual(self.db.find_name("muldrotha"), "Muldrotha, the Gravetide")
        self.assertEqual(self.db.find_name("muldrotha the gravtide"), "Muldrotha, the Gravetide")
        self.assertIsNone(self.db.find_name("zzzzqqq"))

    def test_candidates_respect_identity_price_legality_and_rank(self):
        names = [c["name"] for c in self.db.candidates("U")]
        self.assertEqual(names[:3], ["Sol Ring", "Command Tower", "Pricey Blue Spell"])
        self.assertNotIn("Muldrotha, the Gravetide", names)  # needs B and G
        self.assertNotIn("Black Lotus", names)  # banned
        cheap = [c["name"] for c in self.db.candidates("U", max_price=1)]
        self.assertNotIn("Pricey Blue Spell", cheap)
        self.assertNotIn("Priceless Card", cheap)  # unpriced excluded by a price cap
        self.assertEqual([c["name"] for c in self.db.candidates("U", limit=2)], ["Sol Ring", "Command Tower"])

    def test_rebuild_replaces_old_database(self):
        bulk = self.dir / "small.jsonl.gz"
        write_bulk(bulk, [SAMPLE[1]])
        card_db.build_db(bulk, self.db_path, updated_at="new")
        db = card_db.CardDB(self.db_path)
        self.addCleanup(db.close)
        self.assertEqual(db.count(), 1)


class BuildFailureTests(TempDirCase):
    def test_empty_bulk_raises(self):
        bulk = self.dir / "empty.jsonl.gz"
        write_bulk(bulk, [])
        with self.assertRaises(card_db.BulkDataError):
            card_db.build_db(bulk, self.dir / "cards.sqlite")

    def test_corrupt_bulk_raises(self):
        bulk = self.dir / "bad.jsonl.gz"
        bulk.write_bytes(b"not gzip")
        with self.assertRaises(card_db.BulkDataError):
            card_db.build_db(bulk, self.dir / "cards.sqlite")
        self.assertFalse((self.dir / "cards.sqlite").exists())


class EnsureDbTests(TempDirCase):
    META = {"updated_at": "2026-09-24T00:00:00Z", "jsonl_download_uri": "https://x/b.jsonl.gz", "compressed_size": 1}

    def fake_download(self, url, dest):
        write_bulk(dest)

    def make_db(self, updated_at, age_hours=0):
        bulk = self.dir / card_db.BULK_NAME
        write_bulk(bulk)
        db_path = self.dir / card_db.DB_NAME
        card_db.build_db(bulk, db_path, updated_at=updated_at)
        old = time.time() - age_hours * 3600
        os.utime(db_path, (old, old))
        return db_path

    def ensure(self, **kwargs):
        return card_db.ensure_db(data_dir=self.dir, log=lambda *_: None, **kwargs)

    def test_fresh_db_makes_no_network_calls(self):
        self.make_db("x", age_hours=1)
        with mock.patch("card_db.fetch_bulk_metadata") as meta:
            self.ensure()
        meta.assert_not_called()

    def test_first_run_downloads_and_builds(self):
        with mock.patch("card_db.fetch_bulk_metadata", return_value=self.META), \
             mock.patch("card_db.download_bulk", side_effect=self.fake_download) as dl:
            path = self.ensure()
        dl.assert_called_once()
        self.assertTrue(path.exists())

    def test_stale_but_unchanged_upstream_skips_download(self):
        self.make_db(self.META["updated_at"], age_hours=48)
        with mock.patch("card_db.fetch_bulk_metadata", return_value=self.META), \
             mock.patch("card_db.download_bulk") as dl:
            path = self.ensure()
        dl.assert_not_called()
        self.assertLess(card_db._db_age_hours(path), 1)  # touched, so fresh again

    def test_stale_and_changed_upstream_redownloads(self):
        self.make_db("older", age_hours=48)
        with mock.patch("card_db.fetch_bulk_metadata", return_value=self.META), \
             mock.patch("card_db.download_bulk", side_effect=self.fake_download) as dl:
            path = self.ensure()
        dl.assert_called_once()
        db = card_db.CardDB(path)
        self.addCleanup(db.close)
        self.assertEqual(db.meta()["updated_at"], self.META["updated_at"])

    def test_offline_with_existing_db_uses_it(self):
        path = self.make_db("x", age_hours=48)
        with mock.patch("card_db.fetch_bulk_metadata", side_effect=OSError("offline")):
            self.assertEqual(self.ensure(), path)

    def test_offline_without_db_raises(self):
        with mock.patch("card_db.fetch_bulk_metadata", side_effect=OSError("offline")):
            with self.assertRaises(card_db.BulkDataError):
                self.ensure()


if __name__ == "__main__":
    unittest.main()
