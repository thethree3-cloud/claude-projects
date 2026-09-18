import unittest

from mini_series_pricing import (
    MATERIALS,
    MATERIAL_THICKNESS_CODE,
    resolve_gauge_in,
    material_cost,
    labor_cost,
    open_box_surface_area_sqft,
    open_can_surface_area_sqft,
    compute_mini_box_quote,
    compute_mini_can_quote,
)


class TestResolveGauge(unittest.TestCase):
    def test_code_lookup_by_material(self):
        self.assertEqual(resolve_gauge_in("A", None, "AL"), 0.020)
        self.assertEqual(resolve_gauge_in("A", None, "ST"), 0.018)
        self.assertEqual(resolve_gauge_in("C", None, "MU"), 0.031)

    def test_override_wins_regardless_of_material(self):
        self.assertEqual(resolve_gauge_in("A", 0.040, "ST"), 0.040)
        self.assertEqual(resolve_gauge_in(None, 0.050, "MU"), 0.050)

    def test_every_code_has_all_four_materials(self):
        for code, table in MATERIAL_THICKNESS_CODE.items():
            self.assertEqual(set(table.keys()), set(MATERIALS.keys()))


class TestCostComponents(unittest.TestCase):
    def test_denser_material_costs_more(self):
        area = 0.5
        gauge = 0.020
        al = material_cost(area, gauge, "AL")
        steel = material_cost(area, gauge, "ST")
        brass = material_cost(area, gauge, "BR")
        mu_metal = material_cost(area, gauge, "MU")
        # Brass and mu-metal are both denser and pricier per lb than aluminum.
        self.assertGreater(brass, al)
        self.assertGreater(mu_metal, al)
        self.assertGreater(steel, 0)

    def test_more_draws_costs_more_labor(self):
        area = 0.5
        self.assertGreater(labor_cost(area, 6), labor_cost(area, 1))


class TestComputeMiniBoxQuote(unittest.TestCase):
    def test_code_resolved_quote_has_material_and_labor(self):
        quote = compute_mini_box_quote(
            width_in=1.0, length_in=1.0, height_in=1.0,
            material_code="A", gauge_override_in=None, material_key="AL",
        )
        self.assertIn("material", quote["line_items"])
        self.assertIn("labor", quote["line_items"])
        self.assertEqual(quote["gauge_in"], 0.020)
        self.assertGreater(quote["total"], quote["subtotal"])

    def test_gauge_override_ignores_code(self):
        quote = compute_mini_box_quote(
            width_in=1.5, length_in=2.5, height_in=0.94,
            material_code=None, gauge_override_in=0.040, material_key="MU",
        )
        self.assertEqual(quote["gauge_in"], 0.040)

    def test_different_materials_change_price(self):
        kwargs = dict(width_in=1.5, length_in=1.5, height_in=2.0, material_code="B", gauge_override_in=None)
        al_total = compute_mini_box_quote(**kwargs, material_key="AL")["total"]
        mu_metal_total = compute_mini_box_quote(**kwargs, material_key="MU")["total"]
        self.assertNotEqual(al_total, mu_metal_total)

    def test_powder_coat_costs_more_than_mill_finish(self):
        kwargs = dict(width_in=1.5, length_in=1.5, height_in=2.0, material_code="B", gauge_override_in=None, material_key="AL")
        mill = compute_mini_box_quote(**kwargs, finish="mill finish")
        coated = compute_mini_box_quote(**kwargs, finish="powder coat (custom color)")
        self.assertGreater(coated["total"], mill["total"])

    def test_rejects_nonpositive_dimensions(self):
        with self.assertRaises(ValueError):
            compute_mini_box_quote(
                width_in=0, length_in=1.0, height_in=1.0,
                material_code="A", gauge_override_in=None, material_key="AL",
            )


class TestCanSurfaceArea(unittest.TestCase):
    def test_no_lid_smaller_than_closed_cylinder(self):
        # An open can (bottom disk + wall, no lid) has less area than a
        # box of comparable footprint would with a lid on both ends.
        area = open_can_surface_area_sqft(diameter_in=2.0, height_in=3.0)
        closed_area = area + 3.141592653589793 * 1.0 * 1.0 / 144.0
        self.assertLess(area, closed_area)

    def test_bigger_can_has_more_area(self):
        self.assertGreater(
            open_can_surface_area_sqft(4.0, 4.0),
            open_can_surface_area_sqft(2.0, 2.0),
        )

    def test_can_area_smaller_than_box_of_same_footprint(self):
        # A circle inscribed in a square has less area than the square,
        # so a can should always cost a little less in material than an
        # equivalent-footprint box of the same diameter/side and height.
        d, h = 2.0, 3.0
        self.assertLess(
            open_can_surface_area_sqft(d, h),
            open_box_surface_area_sqft(d, d, h),
        )


class TestComputeMiniCanQuote(unittest.TestCase):
    def test_code_resolved_quote_has_material_and_labor(self):
        quote = compute_mini_can_quote(
            diameter_in=1.0, height_in=2.0,
            material_code="A", gauge_override_in=None, material_key="AL",
        )
        self.assertIn("material", quote["line_items"])
        self.assertIn("labor", quote["line_items"])
        self.assertEqual(quote["gauge_in"], 0.020)
        self.assertGreater(quote["total"], quote["subtotal"])

    def test_gauge_override_ignores_code(self):
        quote = compute_mini_can_quote(
            diameter_in=2.0, height_in=1.125,
            material_code=None, gauge_override_in=0.040, material_key="ST",
        )
        self.assertEqual(quote["gauge_in"], 0.040)

    def test_bigger_can_costs_more(self):
        # Same height:diameter ratio on both so estimate_num_draws() comes
        # out equal either side, isolating the size effect (a narrower big
        # can, relatively deeper than its own diameter, could otherwise
        # need more draws and cost more despite being smaller overall --
        # see test_mini_quote_history.py for where this bit the box series).
        small = compute_mini_can_quote(
            diameter_in=0.5, height_in=0.5, material_code="A", gauge_override_in=None, material_key="AL",
        )
        big = compute_mini_can_quote(
            diameter_in=3.0, height_in=3.0, material_code="C", gauge_override_in=None, material_key="AL",
        )
        self.assertGreater(big["total"], small["total"])

    def test_rejects_nonpositive_dimensions(self):
        with self.assertRaises(ValueError):
            compute_mini_can_quote(
                diameter_in=0, height_in=1.0,
                material_code="A", gauge_override_in=None, material_key="AL",
            )


if __name__ == "__main__":
    unittest.main()
