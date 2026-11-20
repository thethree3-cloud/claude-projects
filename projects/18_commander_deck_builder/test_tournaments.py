import json
import tempfile
import unittest
from pathlib import Path

import card_db
import tournaments
import watchlist
from test_card_db import printing, write_bulk

SLUG = "magiccon-test-open"


def event_page(ids, name="MagicCon Test Open"):
    t = {"TID": SLUG, "name": name, "size": 8, "tournamentDate": "2026-11-13T18:00:00.000Z",
         "bracketUrl": f"https://topdeck.gg/bracket/{SLUG}", "winner": [], "id": "x"}
    links = "".join(f'<a href="/tournament/{SLUG}/decklist/{i}">deck</a>' for i in ids)
    return f'<html><script>{{"data":{{"tournament":{json.dumps(t)}}}}}</script>{links}</html>'


def deck_page(deck_id, standing, player, commanders, cards, wins=2, losses=1):
    items = [{"count": n, "spice": 0, "commanderPlayRate": 0.5,
              "card": {"id": "c", "name": name, "type": kind, "manaCost": ""}} for name, n, kind in cards]
    entry = {"decklistUrl": f"/tournament/{SLUG}/decklist/{deck_id}", "standing": standing, "wins": wins,
             "losses": losses, "draws": 0, "priceUsd": 123.4, "hasDecklist": True,
             "player": {"name": player}, "tournament": {"TID": SLUG},
             "commander": {"name": " / ".join(commanders), "cards": [{"name": c} for c in commanders]},
             "decklist": f"https://topdeck.gg/deck/{SLUG}/{deck_id}", "decklistItems": items}
    return f'<html><script>[{json.dumps({"viewer": None, "tournamentEntry": entry})}]</script></html>'


def deck_cards(commander, extra):
    """A legal-looking 100-card list: commander + extras + Forests."""
    cards = [(commander, 1, "Legendary Creature — Elf")] + [(n, 1, t) for n, t in extra]
    return cards + [("Forest", 100 - len(cards), "Basic Land — Forest")]


class ParseTests(unittest.TestCase):
    def test_slug_from_links_and_names(self):
        self.assertEqual(tournaments.slug_from(f"https://edhtop16.com/tournament/{SLUG}"), SLUG)
        self.assertEqual(tournaments.slug_from(f"https://edhtop16.com/tournament/{SLUG}/decklist/abc"), SLUG)
        self.assertEqual(tournaments.slug_from(SLUG), SLUG)
        with self.assertRaises(tournaments.TournamentError):
            tournaments.slug_from("not a link with spaces")

    def test_parse_event_and_decklist(self):
        event = tournaments.parse_event(event_page(["A1", "B2", "A1"]), SLUG)
        self.assertEqual((event["name"], event["date"], event["size"]), ("MagicCon Test Open", "2026-11-13", 8))
        self.assertEqual(event["decklist_ids"], ["A1", "B2"])
        entry = tournaments.parse_decklist(deck_page("A1", 1, "Alan", ["Green Lord", "Blue Friend"],
                                                     [("Green Lord", 1, "Legendary Creature"),
                                                      ("Sol Ring", 1, "Artifact"), ("Forest", 30, "Basic Land")]))
        self.assertEqual((entry["id"], entry["standing"], entry["player"]), ("A1", 1, "Alan"))
        self.assertEqual(entry["commanders"], ["Green Lord", "Blue Friend"])
        self.assertEqual(entry["cards"][2], {"name": "Forest", "count": 30, "type": "Basic Land"})
        self.assertEqual(tournaments.deck_text(entry).splitlines()[:3], ["1 Green Lord", "1 Blue Friend", "30 Forest"])

    def test_format_change_is_reported(self):
        with self.assertRaises(tournaments.TournamentError):
            tournaments.parse_event("<html>nothing here</html>", SLUG)
        with self.assertRaises(tournaments.TournamentError):
            tournaments.parse_decklist("<html>nothing here</html>")


class ImportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.pages = {
            f"https://edhtop16.com/tournament/{SLUG}": event_page(["A1", "B2", "C3", "BAD"]),
            f"https://edhtop16.com/tournament/{SLUG}/decklist/A1": deck_page(
                "A1", 1, "Ann", ["Green Lord"], deck_cards("Green Lord", [("Sol Ring", "Artifact"),
                                                                          ("Rare Pick", "Instant")])),
            f"https://edhtop16.com/tournament/{SLUG}/decklist/B2": deck_page(
                "B2", 2, "Bo", ["Green Lord"], deck_cards("Green Lord", [("Sol Ring", "Artifact")]), wins=1, losses=2),
            f"https://edhtop16.com/tournament/{SLUG}/decklist/C3": deck_page(
                "C3", 7, "Cy", ["Other Lord"], deck_cards("Other Lord", [("Sol Ring", "Artifact"),
                                                                         ("Rare Pick", "Instant")])),
            f"https://edhtop16.com/tournament/{SLUG}/decklist/BAD": "<html>broken</html>",
        }
        self.calls = []

        def fetch(url):
            self.calls.append(url)
            return self.pages[url]
        self.event = tournaments.import_event(SLUG, data_dir=self.dir / "t", cache_dir=self.dir / "c",
                                              fetch=fetch, log=lambda *_: None)

    def test_import_saves_entries_and_caches(self):
        self.assertEqual([e["standing"] for e in self.event["entries"]], [1, 2, 7])
        self.assertEqual(self.event["failed"], ["BAD"])
        self.assertEqual(tournaments.saved_events(self.dir / "t")[0]["decks"], 3)
        self.assertEqual(tournaments.load_event(SLUG, self.dir / "t")["name"], "MagicCon Test Open")
        n = len(self.calls)
        tournaments.import_event(SLUG, data_dir=self.dir / "t", cache_dir=self.dir / "c",
                                 fetch=lambda url: self.fail(f"refetched {url}") if "decklist/A1" in url
                                 else self.pages[url], log=lambda *_: None)
        self.assertGreaterEqual(n, 5)  # decklists cached forever; event page within a day too

    def test_commander_and_card_tables(self):
        cmds = tournaments.commander_table(self.event)
        self.assertEqual(cmds[0]["commander"], "Green Lord")
        self.assertEqual((cmds[0]["decks"], cmds[0]["best"], cmds[0]["average"]), (2, 1, 1.5))
        self.assertEqual(f"{cmds[0]['wins']}-{cmds[0]['losses']}", "3-3")
        table = {r["name"]: r for r in tournaments.card_table(self.event, None, top=4)}
        self.assertNotIn("Forest", table)       # basics left out
        self.assertNotIn("Green Lord", table)   # commanders left out
        self.assertEqual((table["Sol Ring"]["decks"], table["Sol Ring"]["top_decks"]), (3, 2))
        self.assertEqual(table["Rare Pick"]["top_decks"], 1)  # the 7th-place deck isn't in the top 4
        self.assertEqual(table["Rare Pick"]["top_size"], 2)

    def test_card_play_for_watch_list(self):
        play = tournaments.card_play(days=30, top=8, data_dir=self.dir / "t", today="2026-11-20")
        self.assertEqual(play["Sol Ring"], (3, 3, "MagicCon Test Open"))
        self.assertEqual(tournaments.card_play(days=3, data_dir=self.dir / "t", today="2026-11-30"), {})
        self.assertEqual(watchlist.tournament_factor(play["Sol Ring"]),
                         (1.1, "in 3 of 3 top decks at MagicCon Test Open"))
        self.assertEqual(watchlist.tournament_factor((1, 3, "X")), (1.0, None))  # one deck is noise
        self.assertEqual(watchlist.tournament_factor((2, 20, "X")), (1.0, "in 2 of 20 top decks at X"))

    def test_validator_on_imported_lists(self):
        bulk = self.dir / "bulk.jsonl.gz"
        write_bulk(bulk, [
            printing("gl", "Green Lord", type_line="Legendary Creature — Elf", color_identity=["G"]),
            printing("sol", "Sol Ring"), printing("rp", "Rare Pick", type_line="Instant", color_identity=["G"]),
            printing("for", "Forest", type_line="Basic Land — Forest", color_identity=["G"]),
        ])
        card_db.build_db(bulk, self.dir / "cards.sqlite")
        db = card_db.CardDB(self.dir / "cards.sqlite")
        self.addCleanup(db.close)
        result = tournaments.check_deck(self.event["entries"][0], db)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["stats"]["cards"], 100)


if __name__ == "__main__":
    unittest.main()
