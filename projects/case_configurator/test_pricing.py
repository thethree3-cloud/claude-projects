import unittest

from pricing import (
    CaseSpec,
    PRICING,
    compute_quote,
    surface_area_sqft,
    interior_volume_cuft,
    material_cost,
    labor_cost,
)


class TestSurfaceArea(unittest.TestCase):
    def test_cube(self):
        # 6 faces of 12x12 = 864 sqin -> 6 sqft
        self.assertAlmostEqual(surface_area_sqft(12, 12, 12), 6.0)

    def test_box(self):
        expected_sqin = 2 * (30 * 30 + 30 * 18 + 30 * 18)
        self.assertAlmostEqual(surface_area_sqft(30, 30, 18), expected_sqin / 144.0)


class TestVolume(unittest.TestCase):
    def test_cube(self):
        self.assertAlmostEqual(interior_volume_cuft(12, 12, 12), 1.0)


class TestMaterialAndLaborCost(unittest.TestCase):
    def test_thicker_material_costs_more(self):
        area = 10.0
        self.assertGreater(material_cost(area, 0.090), material_cost(area, 0.063))

    def test_more_draws_costs_more_labor(self):
        area = 10.0
        self.assertGreater(labor_cost(area, 8), labor_cost(area, 2))

    def test_larger_area_costs_more_labor_and_material(self):
        self.assertGreater(material_cost(20.0, 0.090), material_cost(10.0, 0.090))
        self.assertGreater(labor_cost(20.0, 4), labor_cost(10.0, 4))


class TestComputeQuote(unittest.TestCase):
    def test_base_case_no_options(self):
        spec = CaseSpec(width_in=30, height_in=30, depth_in=18)
        quote = compute_quote(spec)
        self.assertIn("material", quote.line_items)
        self.assertIn("labor", quote.line_items)
        self.assertNotIn("handles", quote.line_items)
        self.assertNotIn("foam_interior", quote.line_items)
        self.assertGreater(quote.total, quote.subtotal)  # markup applied

    def test_finish_is_free_for_mill(self):
        spec = CaseSpec(width_in=30, height_in=30, depth_in=18, finish="mill finish")
        quote = compute_quote(spec)
        self.assertAlmostEqual(quote.line_items["finish"], 0.0)

    def test_options_add_line_items(self):
        spec = CaseSpec(
            width_in=30, height_in=30, depth_in=18,
            handle_count=2, bumper_count=4, foam_interior=True,
            rack_rails=True, reinforced_opening=True, mounting_flanges=True,
        )
        quote = compute_quote(spec)
        for key in ("handles", "bumpers", "foam_interior", "rack_rails",
                    "reinforced_opening", "mounting_flanges"):
            self.assertIn(key, quote.line_items)

        self.assertAlmostEqual(quote.line_items["handles"], 2 * PRICING["handle_each"])
        self.assertAlmostEqual(quote.line_items["bumpers"], 4 * PRICING["bumper_each"])
        self.assertAlmostEqual(quote.line_items["rack_rails"], PRICING["rack_rails_flat"])

    def test_markup_applied_to_subtotal(self):
        spec = CaseSpec(width_in=30, height_in=30, depth_in=18)
        quote = compute_quote(spec)
        self.assertAlmostEqual(quote.markup, quote.subtotal * PRICING["markup_pct"])
        self.assertAlmostEqual(quote.total, quote.subtotal + quote.markup)

    def test_heavy_duty_material_costs_more(self):
        base = CaseSpec(width_in=30, height_in=30, depth_in=18, material="standard (.063\" 6061)")
        heavy = CaseSpec(width_in=30, height_in=30, depth_in=18, material="heavy duty (.090\" 6061)")
        self.assertGreater(compute_quote(heavy).total, compute_quote(base).total)

    def test_more_draws_costs_more(self):
        few = CaseSpec(width_in=30, height_in=30, depth_in=18, num_draws=2)
        many = CaseSpec(width_in=30, height_in=30, depth_in=18, num_draws=12)
        self.assertGreater(compute_quote(many).total, compute_quote(few).total)

    def test_bigger_case_costs_more(self):
        small = CaseSpec(width_in=12, height_in=12, depth_in=8)
        big = CaseSpec(width_in=40, height_in=40, depth_in=24)
        self.assertGreater(compute_quote(big).total, compute_quote(small).total)

    def test_rejects_nonpositive_dimensions(self):
        spec = CaseSpec(width_in=0, height_in=30, depth_in=18)
        with self.assertRaises(ValueError):
            compute_quote(spec)


if __name__ == "__main__":
    unittest.main()
