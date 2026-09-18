import unittest

from deep_draw_pricing import (
    PRICING,
    compute_box_quote,
    estimate_num_draws,
    open_box_surface_area_sqft,
    material_cost,
    labor_cost,
    cover_cost,
    nutplate_cost,
)


class TestSurfaceArea(unittest.TestCase):
    def test_open_box_has_no_lid(self):
        # bottom (10x10=100) + 4 sides (4 * 10*5=200) = 300 sqin = 2.083 sqft
        area = open_box_surface_area_sqft(10, 10, 5)
        self.assertAlmostEqual(area, 300 / 144.0)

    def test_bigger_box_has_more_area(self):
        self.assertGreater(
            open_box_surface_area_sqft(20, 20, 10),
            open_box_surface_area_sqft(10, 10, 5),
        )


class TestEstimateNumDraws(unittest.TestCase):
    def test_shallow_wide_box_needs_few_draws(self):
        self.assertEqual(estimate_num_draws(width_in=10, length_in=10, height_in=1), 1)

    def test_deep_narrow_box_needs_more_draws(self):
        shallow = estimate_num_draws(width_in=10, length_in=10, height_in=2)
        deep = estimate_num_draws(width_in=10, length_in=10, height_in=12)
        self.assertGreater(deep, shallow)

    def test_never_less_than_one(self):
        self.assertGreaterEqual(estimate_num_draws(10, 10, 0.1), 1)


class TestCostComponents(unittest.TestCase):
    def test_thicker_gauge_costs_more_material(self):
        area = 5.0
        self.assertGreater(material_cost(area, 0.090), material_cost(area, 0.032))

    def test_more_draws_costs_more_labor(self):
        area = 5.0
        self.assertGreater(labor_cost(area, 8), labor_cost(area, 1))

    def test_no_cover_costs_nothing(self):
        self.assertEqual(cover_cost(10, 10, 0.063, "none"), 0.0)

    def test_gasket_cover_costs_more_than_flush(self):
        cf = cover_cost(10, 10, 0.063, "CF")
        cog = cover_cost(10, 10, 0.063, "COG")
        self.assertGreater(cog, cf)

    def test_no_nutplates_costs_nothing(self):
        self.assertEqual(nutplate_cost(10, 10, "none"), 0.0)

    def test_mill_finish_costs_nothing(self):
        quote = compute_box_quote(width_in=10, length_in=10, height_in=5, gauge_in=0.063)
        self.assertEqual(quote["line_items"]["finish"], 0.0)

    def test_powder_coat_costs_more_than_mill_finish(self):
        mill = compute_box_quote(width_in=10, length_in=10, height_in=5, gauge_in=0.063, finish="mill finish")
        coated = compute_box_quote(
            width_in=10, length_in=10, height_in=5, gauge_in=0.063,
            finish="powder coat (custom color)",
        )
        self.assertGreater(coated["total"], mill["total"])

    def test_bigger_perimeter_needs_more_nutplates(self):
        self.assertGreater(nutplate_cost(30, 30, "AA"), nutplate_cost(3, 3, "AA"))


class TestComputeBoxQuote(unittest.TestCase):
    def test_base_quote_has_material_and_labor(self):
        quote = compute_box_quote(width_in=10, length_in=10, height_in=5, gauge_in=0.063)
        self.assertIn("material", quote["line_items"])
        self.assertIn("labor", quote["line_items"])
        self.assertNotIn("cover", quote["line_items"])
        self.assertNotIn("nutplates", quote["line_items"])
        self.assertGreater(quote["total"], quote["subtotal"])

    def test_cover_and_nutplates_add_line_items(self):
        quote = compute_box_quote(
            width_in=10, length_in=10, height_in=5, gauge_in=0.063,
            cover_type="COG", nutplate_pattern="AA",
        )
        self.assertIn("cover", quote["line_items"])
        self.assertIn("nutplates", quote["line_items"])

    def test_bigger_box_costs_more(self):
        small = compute_box_quote(width_in=2, length_in=2, height_in=1, gauge_in=0.032)
        big = compute_box_quote(width_in=20, length_in=20, height_in=10, gauge_in=0.090)
        self.assertGreater(big["total"], small["total"])

    def test_rejects_nonpositive_dimensions(self):
        with self.assertRaises(ValueError):
            compute_box_quote(width_in=0, length_in=10, height_in=5, gauge_in=0.063)

    def test_markup_applied(self):
        quote = compute_box_quote(width_in=10, length_in=10, height_in=5, gauge_in=0.063)
        self.assertAlmostEqual(quote["markup"], quote["subtotal"] * PRICING["markup_pct"])


if __name__ == "__main__":
    unittest.main()
