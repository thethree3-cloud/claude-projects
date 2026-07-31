import csv
import tempfile
import unittest
from pathlib import Path

from crm_export import build_crm_row, export_leads_to_csv

GOOD_LEAD = {
    "company_name": "Polytronix Inc",
    "score": 60,
    "band": "Medium",
    "fit_reason": "Matched 3 of 9 signals: rugged, avionics, defense-related",
    "location": {"state": "TX", "country": None, "insufficient_information": False},
    "salesperson_name": "Jordan Reyes",
    "email": "jordan.reyes@example.com",
    "territory": "Southwest",
    "assignment_reason": "Company state (TX) matches the Southwest territory.",
}

NEEDS_REVIEW_LEAD = {
    "company_name": "Mystery Corp",
    "score": 0,
    "band": "Unknown",
    "fit_reason": "Not enough information gathered to judge fit.",
    "location": {"state": None, "country": None, "insufficient_information": True},
    "salesperson_name": "Needs Review",
    "email": "",
    "territory": "",
    "assignment_reason": "Could not determine company's state or country from research text.",
}


class BuildCrmRowTests(unittest.TestCase):
    def test_scored_lead_gets_new_status(self):
        row = build_crm_row(GOOD_LEAD, is_existing_customer_match=False)
        self.assertEqual(row["Lead Status"], "New")
        self.assertEqual(row["Review Notes"], "")
        self.assertEqual(row["State"], "TX")
        self.assertEqual(row["Country"], "Not Found")
        self.assertEqual(row["Existing Customer Match"], "No")

    def test_existing_customer_match_flagged(self):
        row = build_crm_row(GOOD_LEAD, is_existing_customer_match=True)
        self.assertEqual(row["Existing Customer Match"], "Yes")

    def test_unknown_band_yields_needs_review_status(self):
        row = build_crm_row(NEEDS_REVIEW_LEAD, is_existing_customer_match=False)
        self.assertEqual(row["Lead Status"], "Needs Review")
        self.assertEqual(row["Review Notes"], NEEDS_REVIEW_LEAD["assignment_reason"])
        self.assertEqual(row["Territory"], "Not Found")
        self.assertEqual(row["State"], "Not Found")

    def test_needs_review_salesperson_yields_needs_review_status_even_with_high_score(self):
        lead = {**GOOD_LEAD, "band": "High", "salesperson_name": "Needs Review", "territory": ""}
        row = build_crm_row(lead, is_existing_customer_match=False)
        self.assertEqual(row["Lead Status"], "Needs Review")


class ExportLeadsToCsvTests(unittest.TestCase):
    def test_writes_expected_rows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "leads.csv"
            export_leads_to_csv(
                [GOOD_LEAD, NEEDS_REVIEW_LEAD],
                existing_customers={"polytronix inc"},
                output_path=output_path,
            )

            with output_path.open(newline="") as f:
                rows = list(csv.DictReader(f))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Company Name"], "Polytronix Inc")
        self.assertEqual(rows[0]["Existing Customer Match"], "Yes")
        self.assertEqual(rows[1]["Company Name"], "Mystery Corp")
        self.assertEqual(rows[1]["Lead Status"], "Needs Review")


if __name__ == "__main__":
    unittest.main()
