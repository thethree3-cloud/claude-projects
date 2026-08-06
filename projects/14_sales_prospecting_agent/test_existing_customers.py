import unittest

import openpyxl

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


class ExistingCustomersXlsxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.xlsx_path = DATA_DIR / "sample_existing_customers_test.xlsx"

        # Header casing/whitespace deliberately messy, and a blank trailing
        # row -- matches what a hand-authored real-world Excel file looks
        # like, unlike this project's own tidy CSV writer.
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["  Company_Name  "])
        sheet.append(["Ironclad Avionics Systems"])
        sheet.append(["Sentinel Power Systems"])
        sheet.append([None])
        workbook.save(cls.xlsx_path)

        cls.existing_customers = load_existing_customers(cls.xlsx_path)

    def test_loads_expected_number_of_customers(self):
        self.assertEqual(len(self.existing_customers), 2)

    def test_known_customer_matches_case_insensitively(self):
        self.assertTrue(
            is_existing_customer("ironclad avionics systems", self.existing_customers)
        )

    def test_unknown_company_does_not_match(self):
        self.assertFalse(
            is_existing_customer("Some Other Company", self.existing_customers)
        )


if __name__ == "__main__":
    unittest.main()
