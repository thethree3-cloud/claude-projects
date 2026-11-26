import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import archidekt
import build_deck
import card_db
import scryfall_tags
import watchlist
from test_card_db import printing, write_bulk


class ScryfallTagTests(unittest.TestCase):
    def test_fetch_follows_pages(self):
        pages = {"first": {"data": [{"oracle_id": "a"}, {"oracle_id": "b"}], "has_more": True, "next_page": "p2"},
                 "p2": {"data": [{"oracle_id": "c"}, {"name": "no id"}], "has_more": False}}
        got = scryfall_tags.fetch_tag("ramp", get=lambda url: pages["first" if "otag" in url else url])
        self.assertEqual(got, ["a", "b", "c"])

    def test_refresh_load_and_stale(self):
        tagged = {"board-wipe": ["w"], "removal": ["w", "r", "c"], "counterspell": ["c"], "ramp": ["x"],
                  "draw": ["x"], "tutor": ["t"]}

        def get(url):
            tag = url.split("otag%3A")[1].split("+")[0]
            return {"data": [{"oracle_id": o} for o in tagged.get(tag, [])], "has_more": False}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tags.json"
            self.assertTrue(scryfall_tags.is_stale(path))
            scryfall_tags.refresh(path, get=get, log=lambda *_: None)
            tags = scryfall_tags.load(path)
            self.assertEqual(tags["w"], "wipe,removal")
            self.assertEqual(tags["c"], "removal,removal")
            self.assertEqual(tags["x"], "ramp,draw")
            self.assertFalse(scryfall_tags.is_stale(path))
            self.assertIsNone(scryfall_tags.load(Path(tmp) / "missing.json"))

    def test_rate_limit_backs_off(self):
        calls, sleeps = [], []
        err = urllib.error.HTTPError("https://api.scryfall.com/x", 429, "slow down", {"Retry-After": "3"}, None)

        def urlopen(req, timeout):
            calls.append(1)
            if len(calls) < 3:
                raise err
            class R:
                def __enter__(self):
                    import io
                    return io.BytesIO(b'{"data": [], "has_more": false}')
                def __exit__(self, *a):
                    return False
            return R()
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            self.assertEqual(scryfall_tags._get("https://api.scryfall.com/x", sleep=sleeps.append), {"data": [], "has_more": False})
        self.assertIn(3.0, sleeps)  # Retry-After honored
        self.assertEqual(len(calls), 3)


class TagRoleTests(unittest.TestCase):
    def test_jobs_from_tags_with_regex_fallback(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bulk = Path(tmp.name) / "bulk.jsonl.gz"
        write_bulk(bulk, [
            printing("dt", "Demonic Tutor", type_line="Sorcery", oracle_text="Search your library for a card."),
            printing("cr", "Cyclonic Rift", type_line="Instant", oracle_text="Return target nonland permanent."),
            printing("cv", "Cultivate", type_line="Sorcery",
                     oracle_text="Search your library for up to two basic land cards."),
            printing("pl", "Plain Bear", type_line="Creature", oracle_text="Draw a card."),
        ])
        tags = {"dt": "tutor", "cr": "wipe,removal", "cv": "ramp,tutor"}
        card_db.build_db(bulk, Path(tmp.name) / "tagged.sqlite", tags=tags)
        card_db.build_db(bulk, Path(tmp.name) / "plain.sqlite")
        tagged = card_db.CardDB(Path(tmp.name) / "tagged.sqlite")
        plain = card_db.CardDB(Path(tmp.name) / "plain.sqlite")
        self.addCleanup(tagged.close)
        self.addCleanup(plain.close)
        role = {n: build_deck.card_role(tagged.get(n)) for n in ("Demonic Tutor", "Cyclonic Rift", "Cultivate", "Plain Bear")}
        self.assertEqual(role, {"Demonic Tutor": "tutor", "Cyclonic Rift": "wipe", "Cultivate": "ramp",
                                "Plain Bear": "synergy"})  # untagged with tags loaded: "-" -> synergy
        self.assertEqual(tagged.get("Plain Bear")["tags"], "-")
        self.assertEqual(plain.get("Plain Bear")["tags"], "")
        self.assertEqual(build_deck.card_role(plain.get("Plain Bear")), "draw")      # rules-text guess
        self.assertEqual(build_deck.card_role(plain.get("Demonic Tutor")), "synergy")  # regex has no tutors
        self.assertIn("tutor", build_deck.ROLES)


def deck_json(deck_id, created, commander, cards, bracket=None, maybe=()):
    entries = [{"categories": ["Commander"], "quantity": 1,
                "card": {"oracleCard": {"uid": f"oid-{commander}", "name": commander, "salt": 1.2}}}]
    entries += [{"categories": ["Ramp"], "quantity": q, "card": {"oracleCard": {"uid": f"oid-{n}", "name": n}}}
                for n, q in cards]
    entries += [{"categories": ["Maybeboard"], "quantity": 1, "card": {"oracleCard": {"uid": f"oid-{n}", "name": n}}}
                for n in maybe]
    return {"id": deck_id, "createdAt": f"{created}T10:00:00Z", "edhBracket": bracket, "name": f"Deck {deck_id}",
            "cards": entries, "categories": [{"name": "Commander", "includedInDeck": True},
                                             {"name": "Ramp", "includedInDeck": True},
                                             {"name": "Maybeboard", "includedInDeck": False}]}


class ArchidektTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.a = archidekt.Archidekt(Path(tmp.name) / "a.sqlite")
        self.addCleanup(self.a.close)

    def test_parse_deck_skips_maybeboard(self):
        d = archidekt.parse_deck(deck_json(1, "2026-11-20", "Hero", [("Sol Ring", 1), ("Forest", 98)], 2,
                                           maybe=["Sideboard Card"]))
        self.assertEqual(d["commanders"], ["Hero"])
        self.assertEqual(d["bracket"], 2)
        self.assertNotIn("oid-Sideboard Card", d["cards"])
        self.assertEqual(d["cards"]["oid-Forest"], ("Forest", 98))
        self.assertEqual(d["salt"]["oid-Hero"], ("Hero", 1.2))

    def test_sample_keeps_only_new_complete_public_decks(self):
        listing = {"results": [{"id": 1, "size": 100}, {"id": 2, "size": 4}, {"id": 3, "size": 100, "private": True},
                               {"id": 4, "size": 100}], "next": None}
        decks = {1: deck_json(1, "2026-11-20", "Hero", [("Sol Ring", 1), ("Forest", 98)]),
                 4: deck_json(4, "2026-11-20", "Hero", [("Forest", 10)])}  # too small once read

        def get(url):
            if "/v3/" in url:
                return listing
            return decks.get(int(url.rstrip("/").rsplit("/", 1)[-1]))
        self.assertEqual(self.a.sample(get=get, log=lambda *_: None), 1)
        self.assertEqual(self.a.count(), 1)
        self.assertEqual(self.a.sample(get=get, log=lambda *_: None), 0)  # deck 1 already known
        self.assertEqual(self.a.salt("oid-Hero"), 1.2)

    def test_trends_compare_recent_and_earlier_decks(self):
        for i in range(4):  # earlier: 1 of 4 decks play Rising Card
            self.a.save(archidekt.parse_deck(deck_json(10 + i, "2026-11-01", "Old Hero",
                                                       [("Rising Card", 1)] if i == 0 else [("Other", 1)])))
        for i in range(4):  # last week: 3 of 4 do
            self.a.save(archidekt.parse_deck(deck_json(20 + i, "2026-11-18", "New Hero",
                                                       [("Rising Card", 1)] if i < 3 else [("Other", 1)], bracket=2)))
        t = self.a.trends(today="2026-11-20", min_decks=1)
        self.assertEqual((t["recent_decks"], t["base_decks"]), (4, 4))
        rising = next(c for c in t["cards"] if c["name"] == "Rising Card")
        self.assertEqual((rising["share"], rising["base_share"], rising["change_pts"]), (0.75, 0.25, 50.0))
        self.assertEqual(t["commanders"][0], {"commander": "New Hero", "decks": 4, "base_decks": 0})
        self.assertEqual(self.a.trends(today="2026-11-20", bracket=2, min_decks=1)["base_decks"], 0)
        with mock.patch.object(archidekt, "DB_PATH", self.a.path):
            self.assertEqual(archidekt.card_trend(today="2026-11-20")["Rising Card"][:2], (0.75, 50.0))

    def test_casual_label_thresholds(self):
        self.assertIsNone(watchlist.casual_label(None))
        self.assertIsNone(watchlist.casual_label((0.3, 5.0, 10)))      # too few decks
        self.assertIsNone(watchlist.casual_label((0.3, 1.0, 200)))     # change too small
        self.assertEqual(watchlist.casual_label((0.3, 5.0, 200)),
                         "in 30% of new Archidekt decks (+5.0 pts vs the 4 weeks before)")


if __name__ == "__main__":
    unittest.main()
