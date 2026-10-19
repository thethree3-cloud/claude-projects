import json
import tempfile
import unittest
from pathlib import Path

import anthropic
from unittest import mock

import build_deck
import card_db
import eval_decks
from test_card_db import printing, write_bulk
from test_llm_deck import FakeClient, make_cards, message


class PureTests(unittest.TestCase):
    def test_jaccard(self):
        self.assertEqual(eval_decks.jaccard(["a", "b"], ["b", "c"]), 1 / 3)
        self.assertEqual(eval_decks.jaccard([], []), 0.0)

    def test_wilson_interval(self):
        lo, hi = eval_decks.wilson(30, 30)
        self.assertGreater(lo, 0.88)
        self.assertEqual(hi, 1.0)
        self.assertEqual(eval_decks.wilson(0, 0), (0.0, 0.0))

    def test_case_ids_unique(self):
        ids = [c["id"] for c in eval_decks.all_cases()]
        self.assertEqual(len(ids), 30)
        self.assertEqual(len(set(ids)), 30)
        self.assertIn("kestia-50", ids)

    def test_grade_deck(self):
        deck = {"cards": [{"name": "A", "listed": True, "inclusion": 0.6},
                          {"name": "B", "listed": False, "inclusion": 0.0}], "spent": 40.0}
        g = eval_decks.grade_deck(deck, 50, ["A", "C"], {"warnings": ["Only 3 ramp cards; aim for at least 8."]}, True)
        self.assertEqual(g["budget_use"], 0.8)
        self.assertAlmostEqual(g["avg_overlap"], 1 / 3, places=4)
        self.assertEqual(g["inclusion"], 0.6)
        self.assertEqual(g["roles_ok"], 0.0)
        self.assertEqual(g["valid_first"], 1.0)


class RunnerTests(unittest.TestCase):
    """Oracle / null / error checks on the whole runner, with fake data and a fake Claude."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        bulk = self.dir / "bulk.jsonl.gz"
        write_bulk(bulk, make_cards())
        card_db.build_db(bulk, self.dir / "cards.sqlite")
        self.ctx = eval_decks.Context(self.dir / "cards.sqlite")
        db = self.ctx.db()
        commander = db.get("Green Commander")
        edhrec = [{"name": f"Spell {i}", "inclusion": 0.5 - i / 200} for i in range(80)]
        pool = build_deck.candidate_pool(commander, edhrec, db)
        for c in pool:
            c["oracle_text"] = db.get(c["name"])["oracle_text"]
        self.ids = [f"c{i}" for i in range(1, 63)]  # 62 cheap spells
        self.ctx.by_commander["Green Commander"] = {
            "commander": commander, "pool": pool, "avg_deck": [f"Spell {i}" for i in range(62)]}
        self.cases = [{"id": "green-50", "commander": "Green Commander", "budget": 50}]

    def rows(self, variant):
        path = self.dir / "runs" / variant / "results.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def run_claude(self, answers):
        client = FakeClient(answers)
        eval_decks.run_variant("claude-opus-5-5", self.cases, workers=1, client=client, log=lambda *_: None,
                               ctx=self.ctx, runs_dir=self.dir / "runs")
        return client

    def test_oracle_answer_scores_full_marks(self):
        self.run_claude([message(self.ids)])
        [row] = self.rows("claude-opus-5-5")
        self.assertEqual(row["status"], "ok")
        self.assertEqual((row["grade"]["valid_first"], row["grade"]["valid"]), (1.0, 1.0))
        self.assertEqual(row["grade"]["avg_overlap"], 1.0)  # picked exactly the average deck
        self.assertTrue((self.dir / "runs" / "claude-opus-5-5" / "traces" / "green-50.json").exists())
        self.assertGreater(row["cost_usd"], 0)

    def test_null_answer_scores_zero(self):
        self.run_claude([message([])] * 3)
        [row] = self.rows("claude-opus-5-5")
        self.assertEqual(row["status"], "invalid")
        self.assertEqual((row["grade"]["valid_first"], row["grade"]["valid"]), (0.0, 0.0))
        self.assertEqual(row["attempts"], 3)

    def test_api_error_goes_to_errors_not_results(self):
        client = FakeClient([])
        client.beta.messages.stream = mock.Mock(side_effect=anthropic.APIConnectionError(request=mock.Mock()))
        eval_decks.run_variant("claude-opus-5-5", self.cases, workers=1, client=client, log=lambda *_: None,
                               ctx=self.ctx, runs_dir=self.dir / "runs")
        self.assertEqual(self.rows("claude-opus-5-5"), [])
        errors = (self.dir / "runs" / "claude-opus-5-5" / "errors.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(errors[0])["failure"], "api_or_parse_error")

    def test_resume_skips_done_cases(self):
        self.run_claude([message(self.ids)])
        client = self.run_claude([])  # nothing scripted: would fail if it called Claude
        self.assertEqual(client.requests, [])
        self.assertEqual(len(self.rows("claude-opus-5-5")), 1)

    def test_baseline_variant_and_summary(self):
        eval_decks.run_variant("baseline", self.cases, log=lambda *_: None, ctx=self.ctx, runs_dir=self.dir / "runs")
        [row] = self.rows("baseline")
        self.assertEqual(row["status"], "ok")
        self.run_claude([message([]), message(self.ids)])
        summary = eval_decks.summarize(self.dir / "runs" / "claude-opus-5-5")
        self.assertEqual((summary["valid_first"], summary["valid"]), (0.0, 1.0))
        table = eval_decks.summary_table([eval_decks.summarize(self.dir / "runs" / "baseline"), summary])
        self.assertIn("| baseline | 1 | 100%", table)
        self.assertIn("| claude-opus-5-5 | 1 | 0%", table)


if __name__ == "__main__":
    unittest.main()
