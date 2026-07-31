import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from crm_export import CSV_FIELDNAMES
from hubspot_crm import (
    CUSTOM_COMPANY_PROPERTIES,
    HUBSPOT_PROPERTY_NAME_MAP,
    build_hubspot_properties,
    find_existing_company_id,
    upsert_company,
)

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


class PropertyNameMapTests(unittest.TestCase):
    def test_every_csv_field_has_a_hubspot_mapping(self):
        self.assertEqual(set(HUBSPOT_PROPERTY_NAME_MAP), set(CSV_FIELDNAMES))


class CustomPropertyLabelTests(unittest.TestCase):
    def test_lead_status_label_does_not_collide_with_hubspot_builtin(self):
        # Regression test: found live -- HubSpot rejects a custom property
        # whose label matches an existing property's label (here, its own
        # built-in hs_lead_status is labeled "Lead Status"). This doesn't
        # catch every possible collision with HubSpot's full built-in
        # property set, but guards against reintroducing this exact one.
        lead_status_prop = next(p for p in CUSTOM_COMPANY_PROPERTIES if p["name"] == "lead_status")
        self.assertNotEqual(lead_status_prop["label"], "Lead Status")


class BuildHubspotPropertiesTests(unittest.TestCase):
    def test_translates_column_names_to_snake_case(self):
        props = build_hubspot_properties(GOOD_LEAD, is_existing_customer_match=False)
        self.assertEqual(props["name"], "Polytronix Inc")
        self.assertEqual(props["fit_score"], "60")
        self.assertEqual(props["fit_band"], "Medium")
        self.assertEqual(props["state"], "TX")
        self.assertEqual(props["assigned_salesperson"], "Jordan Reyes")
        self.assertEqual(props["existing_customer_match"], "No")


class FindExistingCompanyIdTests(unittest.TestCase):
    @patch("hubspot_crm.get_hubspot_client")
    def test_returns_id_when_found(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.crm.companies.search_api.do_search.return_value = SimpleNamespace(
            total=1, results=[SimpleNamespace(id="123")]
        )
        mock_get_client.return_value = mock_client

        self.assertEqual(find_existing_company_id("Polytronix Inc"), "123")

    @patch("hubspot_crm.get_hubspot_client")
    def test_returns_none_when_not_found(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.crm.companies.search_api.do_search.return_value = SimpleNamespace(
            total=0, results=[]
        )
        mock_get_client.return_value = mock_client

        self.assertIsNone(find_existing_company_id("Nonexistent Co"))


class UpsertCompanyTests(unittest.TestCase):
    @patch("hubspot_crm.find_existing_company_id")
    @patch("hubspot_crm.get_hubspot_client")
    def test_creates_when_no_existing_match(self, mock_get_client, mock_find):
        mock_find.return_value = None
        mock_client = MagicMock()
        mock_client.crm.companies.basic_api.create.return_value = SimpleNamespace(id="new-id")
        mock_get_client.return_value = mock_client

        result = upsert_company(GOOD_LEAD, is_existing_customer_match=False)

        mock_client.crm.companies.basic_api.create.assert_called_once()
        mock_client.crm.companies.basic_api.update.assert_not_called()
        self.assertEqual(result["action"], "created")
        self.assertEqual(result["hubspot_company_id"], "new-id")

    @patch("hubspot_crm.find_existing_company_id")
    @patch("hubspot_crm.get_hubspot_client")
    def test_updates_when_existing_match_found(self, mock_get_client, mock_find):
        mock_find.return_value = "existing-id"
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = upsert_company(GOOD_LEAD, is_existing_customer_match=True)

        mock_client.crm.companies.basic_api.update.assert_called_once()
        mock_client.crm.companies.basic_api.create.assert_not_called()
        self.assertEqual(result["action"], "updated")
        self.assertEqual(result["hubspot_company_id"], "existing-id")

    @patch("hubspot_crm.find_existing_company_id")
    @patch("hubspot_crm.get_hubspot_client")
    def test_api_error_is_caught_not_raised(self, mock_get_client, mock_find):
        from hubspot.crm.companies import ApiException

        mock_find.return_value = None
        mock_client = MagicMock()
        mock_client.crm.companies.basic_api.create.side_effect = ApiException(status=500)
        mock_get_client.return_value = mock_client

        result = upsert_company(GOOD_LEAD, is_existing_customer_match=False)

        self.assertEqual(result["action"], "error")
        self.assertIsNone(result["hubspot_company_id"])


if __name__ == "__main__":
    unittest.main()
