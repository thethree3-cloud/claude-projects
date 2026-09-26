"""Offline tests for the eval scoring and the case file itself."""

import unittest

from eval_cases import CASES
from run_eval import check_case, normalize


def result(answer, *subjects):
    return {"answer": answer, "sources": [{"subject": s} for s in subjects]}


class NormalizeTests(unittest.TestCase):
    def test_folds_bold_case_space_dashes_and_quotes(self):
        self.assertEqual(normalize("**C‐1** form\n Workers’ Comp"), "c-1 form workers' comp")


class CheckCaseTests(unittest.TestCase):
    def test_pass(self):
        case = {"must_include": ["C-1"], "sources": ["Workers' Compensation"]}
        self.assertEqual(check_case(case, result("Fill out a C‐1.", "Workers’ Compensation")), [])

    def test_missing_value_and_wrong_source(self):
        case = {"must_include": ["30 feet"], "sources": ["Smoking"]}
        self.assertEqual(len(check_case(case, result("Not stated.", "Safety"))), 2)

    def test_any_of_alternatives(self):
        case = {"must_include": [["two weeks", "2 weeks"]]}
        self.assertEqual(check_case(case, result("Give 2 weeks notice.")), [])
        self.assertEqual(len(check_case(case, result("Give notice."))), 1)

    def test_must_not(self):
        self.assertEqual(len(check_case({"must_not": ["$500"]}, result("Up to $500."))), 1)

    def test_no_sources(self):
        case = {"no_sources": True}
        self.assertEqual(check_case(case, result("Not covered; ask HR.")), [])
        self.assertEqual(len(check_case(case, result("Maybe.", "Safety"))), 1)


class CaseFileTests(unittest.TestCase):
    def test_ids_unique_and_every_case_checks_something(self):
        ids = [c["id"] for c in CASES]
        self.assertEqual(len(ids), len(set(ids)))
        for case in CASES:
            self.assertTrue(case.get("must_include") or case.get("sources") or case.get("no_sources"),
                            case["id"])


if __name__ == "__main__":
    unittest.main()
