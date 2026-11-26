import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import card_db
import collection
import scan_binder
from collection import Collection
from scan_binder import CardSlot
from test_card_db import printing, write_bulk
from test_scan_binder import fake_client


def scanned(*names):
    """``match_names``-style results; None = an unknown card."""
    return [
        {"slot": i + 1, "read": n or "???", "name": n, "status": "exact" if n else "unknown", "legible": True}
        for i, n in enumerate(names)
    ]


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.col = Collection(self.dir / "collection.sqlite")
        self.addCleanup(self.col.close)


class SavePageTests(TempDirCase):
    def test_saves_known_cards_and_skips_unknown(self):
        result = self.col.save_page("BNG", 1, scanned("Brimaz, King of Oreskos", None, "Eater of Hope"), "IMG_1.jpeg")
        self.assertEqual(result["saved"], ["Brimaz, King of Oreskos", "Eater of Hope"])
        self.assertEqual([c["slot"] for c in result["skipped"]], [2])
        self.assertEqual(self.col.names(), {"Brimaz, King of Oreskos", "Eater of Hope"})

    def test_rescanning_a_page_replaces_it(self):
        self.col.save_page("BNG", 1, scanned("A", "B", "C"))
        self.col.save_page("BNG", 1, scanned("A", "D"))
        self.assertEqual([c["card_name"] for c in self.col.cards()], ["A", "D"])

    def test_other_pages_and_binders_untouched(self):
        self.col.save_page("BNG", 1, scanned("A"))
        self.col.save_page("BNG", 2, scanned("B"))
        self.col.save_page("Trade", 1, scanned("C"))
        self.col.save_page("BNG", 1, scanned("Z"))
        self.assertEqual(self.col.names(), {"Z", "B", "C"})

    def test_survives_reopening(self):
        self.col.save_page("BNG", 1, scanned("A"))
        again = Collection(self.col.path)
        self.addCleanup(again.close)
        self.assertEqual(again.names(), {"A"})


class QueryTests(TempDirCase):
    def setUp(self):
        super().setUp()
        self.col.save_page("BNG", 1, scanned("Courser of Kruphix", "Eye Gouge"))
        self.col.save_page("Trade", 3, scanned("Courser of Kruphix"))

    def test_cards_total_copies_across_pockets(self):
        self.col.set_quantity("BNG", 1, 1, 3)
        self.assertEqual(self.col.cards(), [
            {"card_name": "Courser of Kruphix", "quantity": 4},
            {"card_name": "Eye Gouge", "quantity": 1},
        ])

    def test_find_is_case_insensitive_and_lists_every_pocket(self):
        hits = self.col.find("courser of kruphix")
        self.assertEqual([(h["binder"], h["page"], h["slot"]) for h in hits], [("BNG", 1, 1), ("Trade", 3, 1)])
        self.assertEqual(self.col.find("Sol Ring"), [])

    def test_binders_summary(self):
        self.assertEqual(self.col.binders(), [
            {"binder": "BNG", "pages": 1, "cards": 2},
            {"binder": "Trade", "pages": 1, "cards": 1},
        ])

    def test_set_quantity_rules(self):
        self.assertFalse(self.col.set_quantity("BNG", 1, 9, 2))  # empty pocket
        with self.assertRaises(ValueError):
            self.col.set_quantity("BNG", 1, 1, 0)

    def test_remove_page(self):
        self.assertEqual(self.col.remove_page("BNG", 1), 2)
        self.assertEqual(self.col.names(), {"Courser of Kruphix"})


class CliTests(TempDirCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with mock.patch("collection.Collection", lambda: Collection(self.col.path)), contextlib.redirect_stdout(out):
            code = collection.main(list(argv))
        return code, out.getvalue()

    def test_find_and_list(self):
        self.col.save_page("BNG", 2, scanned("Eye Gouge"))
        code, out = self.run_cli("find", "eye gouge")
        self.assertEqual(code, 0)
        self.assertIn("BNG, page 2, slot 1", out)
        self.assertIn("1 different cards, 1 copies", self.run_cli("list")[1])

    def test_set_qty_on_empty_pocket_fails(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.run_cli("set-qty", "BNG", "1", "1", "2")[0], 1)


class ScanAndSaveTests(TempDirCase):
    """scan_binder --binder saves each image as consecutive pages."""

    def test_scan_saves_pages_starting_at_page_flag(self):
        bulk = self.dir / "bulk.jsonl.gz"
        write_bulk(bulk, [printing("e", "Eye Gouge", color_identity=["B"])])
        card_db.build_db(bulk, self.dir / "cards.sqlite")
        images = []
        for name in ("a.jpg", "b.jpg"):
            path = self.dir / name
            Image.new("RGB", (100, 140)).save(path)
            images.append(str(path))
        client = fake_client([CardSlot(slot=1, name="Eye Gouge", legible=True),
                              CardSlot(slot=2, name="Qqqq Zzzz", legible=False)])

        with mock.patch("scan_binder.make_client", return_value=client), \
             mock.patch("scan_binder.card_db.open_db", return_value=card_db.CardDB(self.dir / "cards.sqlite")), \
             mock.patch("scan_binder.Collection", lambda: Collection(self.col.path)), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            code = scan_binder.main([*images, "--binder", "BNG", "--page", "4"])

        self.assertEqual(code, 0)
        self.assertEqual([(h["page"], h["slot"]) for h in self.col.find("Eye Gouge")], [(4, 1), (5, 1)])
        self.assertIn("not saved (unknown card): slot 2", out.getvalue())


if __name__ == "__main__":
    unittest.main()
