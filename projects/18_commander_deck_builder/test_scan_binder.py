import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import anthropic
from PIL import Image

import card_db
import scan_binder
from scan_binder import CardSlot
from test_card_db import printing, write_bulk

CARDS = [
    printing("brimaz", "Brimaz, King of Oreskos", color_identity=["W"]),
    printing("eater", "Eater of Hope", color_identity=["B"]),
    printing("courser", "Courser of Kruphix", color_identity=["G"]),
]


def fake_client(cards=None, stop_reason="end_turn", error=None, text=None):
    """Stands in for anthropic.Anthropic(); records the request."""
    if text is None:
        text = json.dumps({"cards": [c.model_dump() for c in cards or []]})
    block = SimpleNamespace(type="text", text=text)
    response = SimpleNamespace(stop_reason=stop_reason, content=[block])
    create = mock.Mock(side_effect=error) if error else mock.Mock(return_value=response)
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def photo(self, size=(3024, 4032), name="page.jpg"):
        path = self.dir / name
        Image.new("RGB", size, "white").save(path)
        return path


class PrepareImageTests(TempDirCase):
    def test_large_photo_downscaled_to_max_edge(self):
        data = base64.b64decode(scan_binder.prepare_image(self.photo()))
        img = Image.open(io.BytesIO(data))
        self.assertEqual(max(img.size), scan_binder.MAX_EDGE)
        self.assertEqual(img.format, "JPEG")

    def test_small_photo_not_upscaled(self):
        data = base64.b64decode(scan_binder.prepare_image(self.photo((800, 600))))
        self.assertEqual(Image.open(io.BytesIO(data)).size, (800, 600))

    def test_bad_file_raises_scan_error(self):
        bad = self.dir / "bad.jpg"
        bad.write_bytes(b"not an image")
        with self.assertRaises(scan_binder.ScanError):
            scan_binder.prepare_image(bad)


class ReadNamesTests(TempDirCase):
    def test_returns_cards_in_slot_order_and_sends_image(self):
        client = fake_client([CardSlot(slot=2, name="B", legible=True), CardSlot(slot=1, name="A", legible=True)])
        slots = scan_binder.read_names(self.photo(), client)
        self.assertEqual([s.name for s in slots], ["A", "B"])
        kwargs = client.beta.messages.create.call_args.kwargs
        self.assertEqual(kwargs["model"], scan_binder.MODEL)
        self.assertEqual(kwargs["output_config"]["format"]["schema"], scan_binder.PAGE_SCHEMA)
        self.assertEqual(kwargs["messages"][0]["content"][0]["type"], "image")

    def test_refusal_raises(self):
        with self.assertRaises(scan_binder.ScanError):
            scan_binder.read_names(self.photo(), fake_client([], stop_reason="refusal"))

    def test_unreadable_answer_raises(self):
        with self.assertRaises(scan_binder.ScanError):
            scan_binder.read_names(self.photo(), fake_client(text="not json"))

    def test_cut_off_answer_raises(self):
        with self.assertRaises(scan_binder.ScanError):
            scan_binder.read_names(self.photo(), fake_client([], stop_reason="max_tokens"))

    def test_api_error_becomes_scan_error(self):
        error = anthropic.APIConnectionError(request=mock.Mock())
        with self.assertRaises(scan_binder.ScanError):
            scan_binder.read_names(self.photo(), fake_client([], error=error))


class MatchNamesTests(TempDirCase):
    def setUp(self):
        super().setUp()
        bulk = self.dir / "bulk.jsonl.gz"
        write_bulk(bulk, CARDS)
        card_db.build_db(bulk, self.dir / "cards.sqlite")
        self.db = card_db.CardDB(self.dir / "cards.sqlite")
        self.addCleanup(self.db.close)

    def match(self, *names):
        slots = [CardSlot(slot=i + 1, name=n, legible=True) for i, n in enumerate(names)]
        return scan_binder.match_names(slots, self.db)

    def test_exact_name_kept(self):
        [card] = self.match("brimaz, king of oreskos")
        self.assertEqual((card["name"], card["status"]), ("Brimaz, King of Oreskos", "exact"))

    def test_misread_corrected_to_real_card(self):
        [card] = self.match("Courser of Kruphlx")
        self.assertEqual((card["name"], card["status"], card["read"]), ("Courser of Kruphix", "corrected", "Courser of Kruphlx"))

    def test_unknown_name_never_guessed(self):
        [card] = self.match("Zzyzx Qwerty")
        self.assertEqual((card["name"], card["status"]), (None, "unknown"))


class ScorePageTests(unittest.TestCase):
    def cards(self, *names):
        return [{"name": n} for n in names]

    def test_all_correct(self):
        score = scan_binder.score_page(self.cards("A", "B"), ["A", "B"])
        self.assertEqual((score["correct"], score["total"], score["misses"]), (2, 2, []))

    def test_wrong_missing_and_extra(self):
        score = scan_binder.score_page(self.cards("A", "X"), ["A", "B", "C"])
        self.assertEqual(score["correct"], 1)
        self.assertEqual([m["slot"] for m in score["misses"]], [2, 3])
        self.assertIsNone(score["misses"][1]["got"])
        self.assertEqual(scan_binder.score_page(self.cards("A", "B"), ["A"])["extra"], ["B"])


if __name__ == "__main__":
    unittest.main()
