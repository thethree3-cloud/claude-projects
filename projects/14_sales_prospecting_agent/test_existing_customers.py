import unittest

from existing_customers import is_existing_customer, load_existing_customers
from generate_sample_data import DATA_DIR, write_sample_existing_customers


class ExistingCustomersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        write_sample_existing_customers()
        cls.existing_customers = load_existing_customers(
            DATA_DIR / "sample_existing_customers.csv"
        )

    def test_loads_expected_number_of_customers(self):
        self.assertEqual(len(self.existing_customers), 3)

    def test_known_customer_matches_case_insensitively(self):
        self.assertTrue(
            is_existing_customer("ironclad avionics systems", self.existing_customers)
        )
        self.assertTrue(
            is_existing_customer("IRONCLAD AVIONICS SYSTEMS", self.existing_customers)
        )

    def test_unknown_company_does_not_match(self):
        self.assertFalse(
            is_existing_customer("Some Other Company", self.existing_customers)
        )


if __name__ == "__main__":
    unittest.main()
