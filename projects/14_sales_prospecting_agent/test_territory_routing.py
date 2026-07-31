import unittest

from generate_sample_data import DATA_DIR, write_sample_territory_routing
from territory_routing import load_territory_routing, route_salesperson

ROWS = [
    {
        "salesperson_name": "Jordan Reyes",
        "email": "jordan.reyes@example.com",
        "territory": "Southwest",
        "coverage": "TX;NM;AZ;OK",
    },
    {
        "salesperson_name": "Casey Kim",
        "email": "casey.kim@example.com",
        "territory": "Southeast",
        "coverage": "FL;GA;AL;SC;NC",
    },
    {
        "salesperson_name": "Morgan Blake",
        "email": "morgan.blake@example.com",
        "territory": "International",
        "coverage": "INTERNATIONAL",
    },
]


class RouteSalespersonTests(unittest.TestCase):
    def test_domestic_state_match(self):
        result = route_salesperson({"state": "TX", "country": None}, ROWS)
        self.assertEqual(result["salesperson_name"], "Jordan Reyes")
        self.assertEqual(result["territory"], "Southwest")

    def test_domestic_state_no_covering_territory_needs_review(self):
        result = route_salesperson({"state": "MT", "country": None}, ROWS)
        self.assertEqual(result["salesperson_name"], "Needs Review")
        self.assertEqual(result["email"], "")
        self.assertEqual(result["territory"], "")

    def test_non_domestic_with_international_row(self):
        result = route_salesperson({"state": None, "country": "Germany"}, ROWS)
        self.assertEqual(result["salesperson_name"], "Morgan Blake")
        self.assertEqual(result["territory"], "International")

    def test_non_domestic_with_no_international_row_needs_review(self):
        rows_without_international = ROWS[:2]
        result = route_salesperson(
            {"state": None, "country": "Germany"}, rows_without_international
        )
        self.assertEqual(result["salesperson_name"], "Needs Review")

    def test_us_country_with_no_state_falls_through_to_needs_review(self):
        result = route_salesperson({"state": None, "country": "USA"}, ROWS)
        self.assertEqual(result["salesperson_name"], "Needs Review")

    def test_no_location_determined_needs_review(self):
        result = route_salesperson({"state": None, "country": None}, ROWS)
        self.assertEqual(result["salesperson_name"], "Needs Review")
        self.assertIn("Could not determine", result["assignment_reason"])

    def test_never_invents_an_assignment_not_in_rows(self):
        result = route_salesperson({"state": "CA", "country": None}, ROWS)
        assigned_names = {row["salesperson_name"] for row in ROWS}
        self.assertNotIn(result["salesperson_name"], assigned_names)
        self.assertEqual(result["salesperson_name"], "Needs Review")


class LoadTerritoryRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        write_sample_territory_routing()
        cls.rows = load_territory_routing(DATA_DIR / "sample_territory_routing.csv")

    def test_loads_all_rows(self):
        self.assertEqual(len(self.rows), 3)
        self.assertEqual(self.rows[0]["salesperson_name"], "Jordan Reyes")

    def test_international_sentinel_present(self):
        coverages = [row["coverage"] for row in self.rows]
        self.assertIn("INTERNATIONAL", coverages)


if __name__ == "__main__":
    unittest.main()
