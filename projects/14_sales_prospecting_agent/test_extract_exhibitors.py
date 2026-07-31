import unittest

from extract_exhibitors import extract_company_names
from generate_sample_data import DATA_DIR, EXHIBITORS, write_exhibitor_list_pdf


class ExtractCompanyNamesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        write_exhibitor_list_pdf()
        cls.pdf_path = DATA_DIR / "sample_expo_exhibitors.pdf"

    def test_extracts_all_known_exhibitors_in_order(self):
        names = extract_company_names(self.pdf_path)
        self.assertEqual(names, EXHIBITORS)


if __name__ == "__main__":
    unittest.main()
