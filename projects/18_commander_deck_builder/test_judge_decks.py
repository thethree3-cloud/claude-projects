import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import build_deck
import card_db
import judge_decks
import llm_deck
from test_card_db import write_bulk
from test_llm_deck import FakeClient, make_cards


def verdict(winner, a=7, b=5):
    score = lambda n: {c: n for c in judge_decks.CRITERIA}  # noqa: E731
    text = json.dumps({"deck_a": score(a), "deck_b": score(b), "winner": winner, "confidence": "medium",
                       "reason": "Deck A has more draw."})
    usage = SimpleNamespace(input_tokens=6000, output_tokens=2000, cache_creation_input_tokens=0,
                            cache_read_input_tokens=0)
    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)],
                           usage=usage, model="claude-sonnet-5-5")


class JudgeCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        bulk = Path(cls.tmp.name) / "bulk.jsonl.gz"
        write_bulk(bulk, make_cards())
        card_db.build_db(bulk, Path(cls.tmp.name) / "cards.sqlite")
        cls.db = card_db.CardDB(Path(cls.tmp.name) / "cards.sqlite")
        commander = cls.db.get("Green Commander")
        edhrec = [{"name": f"Spell {i}", "inclusion": 0.5 - i / 200} for i in range(80)]
        pool = build_deck.candidate_pool(commander, edhrec, cls.db)
        for c in pool:
            c["oracle_text"] = cls.db.get(c["name"])["oracle_text"]
        table, _ = llm_deck.card_table(pool)
        prompt = llm_deck.first_prompt(commander, 50, 2.0, table)
        # Claude picked the 62 *least* popular cards; the baseline takes the most popular.
        picks = [{"id": f"c{i}", "reason": "fits"} for i in range(19, 81)]
        cls.trace = [{"role": "user", "content": prompt},
                     {"role": "assistant", "content": json.dumps({"strategy": "s", "picks": picks})}]
        cls.case = {"id": "green-50", "commander": "Green Commander"}

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def test_parse_trace_reads_budget_table_and_final_picks(self):
        parsed = judge_decks.parse_trace(self.trace)
        self.assertEqual((parsed["budget"], parsed["commander_cost"]), (50.0, 2.0))
        self.assertEqual(len(parsed["rows"]), 80)
        self.assertEqual(parsed["rows"][0]["name"], "Spell 0")
        self.assertEqual(parsed["rows"][0]["usd"], 0.5)
        self.assertAlmostEqual(parsed["rows"][0]["inclusion"], 0.5)
        self.assertEqual(len(parsed["picks"]), 62)

    def test_rebuild_gives_two_full_decks_from_one_pool(self):
        _, claude, baseline = judge_decks.rebuild_decks(self.case, self.trace, self.db)
        for deck in (claude, baseline):
            self.assertEqual(len(deck["cards"]) + sum(deck["basics"].values()), 99)
            self.assertLessEqual(deck["spent"], 50)
        self.assertIn("Spell 79", {c["name"] for c in claude["cards"]})
        self.assertIn("Spell 0", {c["name"] for c in baseline["cards"]})

    def test_deck_text_is_blind(self):
        _, claude, _ = judge_decks.rebuild_decks(self.case, self.trace, self.db)
        text = judge_decks.deck_text(claude, self.db)
        self.assertIn("Sorcery (62):", text)
        self.assertIn("- Spell 18 [MV 2, Sorcery]: Trample.", text)
        self.assertIn("Basic lands: 37 Forest", text)
        self.assertTrue(text.startswith("Facts: 37 lands (0 nonbasic, 37 basic), 62 nonland cards, average mana value of nonland cards 2.00."))
        for leak in ("fits", "$", "%", "synergy", "draw)", "Claude", "baseline"):
            self.assertNotIn(leak, text)

    def test_judge_case_maps_letters_back_to_builders(self):
        client = FakeClient([verdict("A"), verdict("A")])
        first = judge_decks.judge_case(self.case, self.trace, self.db, client, "claude_first")
        second = judge_decks.judge_case(self.case, self.trace, self.db, client, "baseline_first")
        self.assertEqual(first["winner"], "claude")
        self.assertEqual(second["winner"], "baseline")  # "A" is the baseline deck in this order
        self.assertEqual(second["scores"]["baseline"]["mana"], 7)
        self.assertEqual(second["scores"]["claude"]["mana"], 5)
        self.assertEqual(first["cost_usd"], 0.032)  # 6000 in + 2000 out at Sonnet prices
        sent = client.requests[0]
        self.assertEqual(sent["model"], "claude-sonnet-5-5")
        self.assertEqual(sent["output_config"]["format"]["schema"], judge_decks.VERDICT_SCHEMA)
        self.assertNotIn("Claude", sent["messages"][0]["content"].split("Deck A")[1])

    def test_bad_answers_raise(self):
        cut = verdict("A")
        cut.stop_reason = "max_tokens"
        with self.assertRaises(judge_decks.ScanError):
            judge_decks.ask_judge(FakeClient([cut]), "prompt")
        bad = verdict("A")
        bad.content[0].text = '{"winner": "A"}'
        with self.assertRaises(judge_decks.ScanError):
            judge_decks.ask_judge(FakeClient([bad]), "prompt")

    def test_run_writes_rows_and_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "green-50.json"
            trace_path.write_text(json.dumps(self.trace))
            case = {**self.case, "trace": trace_path}
            client = FakeClient([verdict("A"), verdict("B")])
            failures = judge_decks.run([case], client, self.db, workers=1, out_dir=tmp, log=lambda *_: None)
            self.assertEqual(failures, 0)
            rows = [json.loads(l) for l in (Path(tmp) / "results.jsonl").read_text().splitlines()]
            self.assertEqual({r["order"] for r in rows}, {"claude_first", "baseline_first"})
            judge_decks.run([case], FakeClient([]), self.db, workers=1, out_dir=tmp, log=lambda *_: None)
            self.assertEqual(len((Path(tmp) / "results.jsonl").read_text().splitlines()), 2)  # nothing redone


def row(cid, order, winner):
    scores = {"claude": {c: 6 for c in judge_decks.CRITERIA}, "baseline": {c: 5 for c in judge_decks.CRITERIA}}
    return {"prompt_id": cid, "order": order, "winner": winner, "scores": scores, "cost_usd": 0.05}


class SummaryTests(unittest.TestCase):
    def test_case_needs_both_orders_to_agree(self):
        rows = [
            row("a", "claude_first", "claude"), row("a", "baseline_first", "claude"),      # Claude wins
            row("b", "claude_first", "baseline"), row("b", "baseline_first", "baseline"),  # baseline wins
            row("c", "claude_first", "claude"), row("c", "baseline_first", "baseline"),    # split (position)
            row("d", "claude_first", "tie"), row("d", "baseline_first", "tie"),            # tie -> split
            row("e", "claude_first", "claude"),                                           # incomplete, ignored
        ]
        s = judge_decks.summarize(rows)
        self.assertEqual((s["cases"], s["claude"], s["baseline"], s["split"]), (4, 1, 1, 2))
        # Decided calls: a(2) b(2) c(2); the first-shown deck won in a1, b2, c1, c2 -> 4/6.
        self.assertAlmostEqual(s["first_position_win_rate"], 4 / 6)
        self.assertEqual(s["means"]["claude"]["mana"], 6)
        self.assertEqual(s["cost_usd"], 0.4)
        text = judge_decks.summary_markdown(s, "claude-sonnet-5-5")
        self.assertIn("| Claude (Opus 5.5) deck wins | 1 | 25%", text)


if __name__ == "__main__":
    unittest.main()
