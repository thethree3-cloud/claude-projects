import unittest

from score import band_for, projected, score_comparison


def _comparison(required, preferred, years_met=True, edu_met=True):
    """Builds a comparison dict shaped like match.match_requirements() output.
    `required`/`preferred` are lists of bools (met or not)."""
    return {
        "required_skills": [
            {"skill": f"r{i}", "met": met, "evidence": ""} for i, met in enumerate(required)
        ],
        "preferred_skills": [
            {"skill": f"p{i}", "met": met, "evidence": ""} for i, met in enumerate(preferred)
        ],
        "years": {"required": 2, "candidate": 5 if years_met else 0, "met": years_met},
        "education": {"requirement": "BS", "met": edu_met, "note": "n/a"},
    }


class BandForTests(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(band_for(75), "Strong")
        self.assertEqual(band_for(100), "Strong")
        self.assertEqual(band_for(74), "Possible")
        self.assertEqual(band_for(45), "Possible")
        self.assertEqual(band_for(44), "Weak")
        self.assertEqual(band_for(0), "Weak")


class ScoreComparisonTests(unittest.TestCase):
    def test_everything_met_scores_100_strong(self):
        result = score_comparison(_comparison([True, True], [True, True]))
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["band"], "Strong")

    def test_nothing_met_scores_zero_weak(self):
        result = score_comparison(
            _comparison([False, False], [False], years_met=False, edu_met=False)
        )
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["band"], "Weak")

    def test_half_required_plus_years_and_education(self):
        # 60 * 0.5 (req) + 20 (years) + 15 * 0 (pref) + 5 (edu) = 55
        result = score_comparison(_comparison([True, False], [False, False]))
        self.assertEqual(result["score"], 55)
        self.assertEqual(result["band"], "Possible")

    def test_empty_skill_lists_count_as_full_marks(self):
        # No required and no preferred skills named -> both components full.
        # 60 + 20 + 15 + 5 = 100
        result = score_comparison(_comparison([], []))
        self.assertEqual(result["score"], 100)

    def test_breakdown_components_sum_to_score(self):
        result = score_comparison(_comparison([True, False, False], [True, False]))
        self.assertEqual(
            round(sum(c["points"] for c in result["breakdown"])), result["score"]
        )

    def test_breakdown_is_explainable_per_component(self):
        result = score_comparison(_comparison([True, False], [True]))
        components = {c["component"]: c for c in result["breakdown"]}
        self.assertEqual(components["Required skills"]["detail"], "1 of 2 met")
        self.assertEqual(components["Required skills"]["points"], 30.0)
        self.assertEqual(components["Preferred skills"]["detail"], "1 of 1 met")
        self.assertEqual(components["Preferred skills"]["points"], 15.0)

    def test_missing_years_zeroes_only_that_component(self):
        met = score_comparison(_comparison([True], [True]))["score"]
        no_years = score_comparison(_comparison([True], [True], years_met=False))["score"]
        self.assertEqual(met - no_years, 20)


class ProjectedTests(unittest.TestCase):
    def test_no_gaps_gives_an_empty_projection(self):
        result = projected(_comparison([True, True], [True]))
        self.assertEqual(result["per_gap"], [])
        self.assertEqual(result["current"], result["if_all_closed"])

    def test_per_gap_and_all_closed(self):
        # 1 of 2 required met, years short, education met:
        #   current = 30 + 0 + 15 + 5 = 50
        comparison = _comparison([True, False], [True], years_met=False)
        result = projected(comparison)
        self.assertEqual(result["current"], 50)

        by_gap = {e["gap"]: e for e in result["per_gap"]}
        self.assertEqual(set(by_gap), {"r1", "years of experience"})
        # closing the one unmet required skill -> +30
        self.assertEqual(by_gap["r1"], {"gap": "r1", "score": 80, "delta": 30})
        # closing the years gap -> +20
        self.assertEqual(by_gap["years of experience"]["delta"], 20)
        # everything closed -> 100
        self.assertEqual(result["if_all_closed"], 100)

    def test_education_gap_is_projected(self):
        result = projected(_comparison([True], [True], edu_met=False))
        self.assertEqual(
            [e["gap"] for e in result["per_gap"]], ["education"]
        )
        self.assertEqual(result["per_gap"][0]["delta"], 5)

    def test_projection_does_not_mutate_the_input(self):
        comparison = _comparison([False], [False], years_met=False, edu_met=False)
        projected(comparison)
        self.assertFalse(comparison["required_skills"][0]["met"])
        self.assertFalse(comparison["years"]["met"])


if __name__ == "__main__":
    unittest.main()
