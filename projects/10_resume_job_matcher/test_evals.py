"""Offline checks that the eval fixtures are well-formed. The evals themselves
(`run_evals.py`) hit the real model and aren't part of this suite."""

import unittest

import run_evals
from eval_cases import FIT_CASES, TAILOR_CASES, VALID_BANDS


class EvalCasesTests(unittest.TestCase):
    def test_there_are_cases(self):
        self.assertTrue(FIT_CASES)
        self.assertTrue(TAILOR_CASES)

    def test_case_names_are_unique(self):
        names = [c.name for c in (*FIT_CASES, *TAILOR_CASES)]
        self.assertEqual(len(names), len(set(names)))

    def test_fit_cases_are_coherent(self):
        for case in FIT_CASES:
            with self.subTest(case=case.name):
                self.assertTrue(case.resume.strip())
                self.assertTrue(case.job.strip())
                self.assertTrue(case.band_in)
                self.assertLessEqual(set(case.band_in), VALID_BANDS)
                lo, hi = case.score_range
                self.assertLessEqual(0, lo)
                self.assertLess(lo, hi)
                self.assertLessEqual(hi, 100)

    def test_tailor_cases_are_coherent(self):
        for case in TAILOR_CASES:
            with self.subTest(case=case.name):
                self.assertTrue(case.resume.strip())
                self.assertTrue(case.job.strip())
                self.assertGreaterEqual(case.max_flags, 0)


class RunnerTests(unittest.TestCase):
    def test_list_mode_makes_no_api_calls(self):
        # --list must not touch pipeline; a missing key would raise if it did
        rc = run_evals.main(["--list"])
        self.assertEqual(rc, 0)

    def test_unmatched_filter_returns_nonzero(self):
        self.assertEqual(run_evals.main(["--case", "definitely-no-such-case"]), 1)

    def test_result_passed_is_false_on_error(self):
        result = run_evals.Result("x")
        result.check("a", True)
        result.error = "boom"
        self.assertFalse(result.passed)


if __name__ == "__main__":
    unittest.main()
