import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import card_db
import llm_deck
from test_card_db import printing, write_bulk


def make_cards():
    out = [printing("cmd", "Green Commander", type_line="Legendary Creature — Elf", color_identity=["G"],
                    oracle_text="Elves you control get +1/+1.", prices={"usd": "2.00"})]
    for i in range(80):
        out.append(printing(f"s{i}", f"Spell {i}", type_line="Sorcery", color_identity=["G"],
                            oracle_text="Draw a card." if i < 10 else "Trample.", cmc=2, prices={"usd": "0.50"}))
    out.append(printing("pricey", "Pricey Spell", type_line="Sorcery", color_identity=["G"], prices={"usd": "90.00"}))
    out.append(printing("f", "Forest", type_line="Basic Land — Forest", color_identity=["G"]))
    return out


def message(picks, stop_reason="end_turn"):
    text = json.dumps({"strategy": "Go wide with elves.", "picks": [{"id": i, "reason": "fits"} for i in picks]})
    usage = SimpleNamespace(input_tokens=1000, output_tokens=500, cache_creation_input_tokens=15000,
                            cache_read_input_tokens=0)
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)], usage=usage)


class FakeClient:
    """Streams scripted answers; records each request's messages."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    @contextlib.contextmanager
    def _stream(self, **kwargs):
        self.requests.append(kwargs)
        answer = self.answers.pop(0)
        yield SimpleNamespace(get_final_message=lambda: answer)


class LlmDeckCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        bulk = Path(cls.tmp.name) / "bulk.jsonl.gz"
        write_bulk(bulk, make_cards())
        card_db.build_db(bulk, Path(cls.tmp.name) / "cards.sqlite")
        cls.db = card_db.CardDB(Path(cls.tmp.name) / "cards.sqlite")
        cls.commander = cls.db.get("Green Commander")
        edhrec = [{"name": f"Spell {i}", "inclusion": 0.5 - i / 200} for i in range(80)]
        edhrec.append({"name": "Pricey Spell", "inclusion": 0.9})
        import build_deck
        cls.pool = build_deck.candidate_pool(cls.commander, edhrec, cls.db)
        for c in cls.pool:
            c["oracle_text"] = cls.db.get(c["name"])["oracle_text"]
        cls.ids = {c["name"]: f"c{i}" for i, c in enumerate(cls.pool, 1)}

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def spell_ids(self, n):
        return [self.ids[f"Spell {i}"] for i in range(n)]

    def run_build(self, answers, budget=100):
        client = FakeClient(answers)
        result = llm_deck.build_with_claude(self.commander, self.pool, budget, self.db, client,
                                            commander_cost=2.0, log=lambda *_: None)
        return result, client


class TableAndPromptTests(LlmDeckCase):
    def test_table_has_ids_prices_and_text(self):
        table, by_id = llm_deck.card_table(self.pool)
        self.assertEqual(len(by_id), len(self.pool))
        self.assertIn("| Spell 0 | draw | 50% | $0.50 | Draw a card.", table)

    def test_prompt_states_money_after_commander(self):
        prompt = llm_deck.first_prompt(self.commander, 100, 2.0, "TABLE")
        self.assertIn("may cost at most $98.00", prompt)
        self.assertIn("TABLE", prompt)


class AssembleTests(LlmDeckCase):
    def test_basics_fill_to_99_and_cost_includes_commander(self):
        _, by_id = llm_deck.card_table(self.pool)
        picks = [llm_deck.Pick(id=i, reason="r") for i in self.spell_ids(62)]
        deck, problems = llm_deck.assemble(self.commander, by_id, picks, commander_cost=2.0)
        self.assertEqual(problems, [])
        self.assertEqual(deck["basics"], {"Forest": 37})
        self.assertEqual(deck["spent"], 2.0 + 62 * 0.5)

    def test_unknown_and_repeated_ids_reported(self):
        _, by_id = llm_deck.card_table(self.pool)
        picks = [llm_deck.Pick(id="c1", reason="r"), llm_deck.Pick(id="c1", reason="r"), llm_deck.Pick(id="c999", reason="r")]
        deck, problems = llm_deck.assemble(self.commander, by_id, picks)
        self.assertEqual(len(deck["cards"]), 1)
        self.assertTrue(any("more than once" in p for p in problems))
        self.assertTrue(any("Unknown id 'c999'" in p for p in problems))


class LoopTests(LlmDeckCase):
    def test_valid_first_try(self):
        result, client = self.run_build([message(self.spell_ids(62))])
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(result["deck"]["spent"], 33.0)
        self.assertEqual(result["strategy"], "Go wide with elves.")
        first = client.requests[0]["messages"][0]["content"][0]
        self.assertEqual(first["cache_control"], {"type": "ephemeral"})
        self.assertGreater(result["cost_usd"], 0)

    def test_over_budget_fixed_on_retry_with_feedback(self):
        bad = message(self.spell_ids(61) + [self.ids["Pricey Spell"]])
        good = message(self.spell_ids(62))
        result, client = self.run_build([bad, good])
        self.assertTrue(result["ok"])
        self.assertEqual([len(a["errors"]) > 0 for a in result["attempts"]], [True, False])
        retry = client.requests[1]["messages"]
        self.assertEqual(retry[1]["role"], "assistant")
        self.assertIs(retry[1]["content"], bad.content)  # Claude's answer passed back unchanged
        self.assertIn("Costs $", retry[2]["content"])
        self.assertIn("limit for picks is $98.00", retry[2]["content"])

    def test_gives_up_after_max_attempts(self):
        bad = message(["c999"])
        result, client = self.run_build([bad] * llm_deck.MAX_ATTEMPTS)
        self.assertFalse(result["ok"])
        self.assertEqual(len(client.requests), llm_deck.MAX_ATTEMPTS)
        self.assertNotIn("deck", result)  # nothing invalid is ever handed back as a deck
        self.assertNotIn("text", result)

    def test_refusal_and_cut_off_raise(self):
        with self.assertRaises(llm_deck.ScanError):
            self.run_build([message([], stop_reason="refusal")])
        with self.assertRaises(llm_deck.ScanError):
            self.run_build([message(self.spell_ids(62), stop_reason="max_tokens")])


class CostTests(unittest.TestCase):
    def test_estimate(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_creation_input_tokens": 0,
                 "cache_read_input_tokens": 1_000_000}
        self.assertEqual(llm_deck.estimated_cost(usage, "claude-opus-5-5"), 4.0 + 2.0 + 0.4)
        self.assertIsNone(llm_deck.estimated_cost(usage, "unknown-model"))


if __name__ == "__main__":
    unittest.main()
