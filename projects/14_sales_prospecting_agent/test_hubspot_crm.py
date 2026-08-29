import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from crm_export import CSV_FIELDNAMES
from hubspot_crm import (
    CUSTOM_COMPANY_PROPERTIES,
    HUBSPOT_PROPERTY_NAME_MAP,
    build_hubspot_properties,
    export_leads_to_hubspot,
    find_existing_company_id,
    upsert_company,
)

NO_CONTACT = {"name": None, "title": None, "email": None, "insufficient_information": True}

GOOD_LEAD = {
    "company_name": "Polytronix Inc",
    "score": 60,
    "band": "Medium",
    "fit_reason": "Matched 3 of 9 signals: rugged, avionics, defense-related",
    "location": {"state": "TX", "country": None, "insufficient_information": False},
    "contact": NO_CONTACT,
    "source": "Web search",
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


HIGH_LEAD = {**GOOD_LEAD, "company_name": "Vantage Defense Composites", "band": "High"}
LOW_LEAD = {**GOOD_LEAD, "company_name": "Bank of America", "band": "Low"}


class ExportLeadsToHubspotDealWiringTests(unittest.TestCase):
    @patch("hubspot_contacts.upsert_contact")
    @patch("hubspot_notes.create_triage_note")
    @patch("hubspot_notes.get_note_association_type_ids")
    @patch("hubspot_deals.upsert_deal")
    @patch("hubspot_deals.find_initial_stage_id")
    @patch("hubspot_deals.get_default_pipeline")
    @patch("hubspot_deals.ensure_custom_deal_properties")
    @patch("hubspot_crm.upsert_company")
    @patch("hubspot_crm.ensure_custom_properties")
    def test_creates_a_deal_for_high_and_medium_but_not_low(
        self,
        mock_ensure_company_props,
        mock_upsert_company,
        mock_ensure_deal_props,
        mock_get_pipeline,
        mock_find_stage,
        mock_upsert_deal,
        mock_get_note_types,
        mock_create_note,
        mock_upsert_contact,
    ):
        mock_get_pipeline.return_value = SimpleNamespace(id="pipeline-1")
        mock_find_stage.return_value = "stage-1"
        mock_upsert_company.side_effect = lambda lead, match: {
            "company_name": lead["company_name"],
            "hubspot_company_id": f"company-{lead['company_name']}",
            "action": "created",
        }
        mock_upsert_deal.return_value = {"hubspot_deal_id": "deal-1", "action": "created"}
        mock_get_note_types.return_value = {"company": 190, "deal": 214}
        mock_create_note.return_value = {"hubspot_note_id": "note-1", "action": "created"}
        mock_upsert_contact.return_value = None

        results = export_leads_to_hubspot([HIGH_LEAD, GOOD_LEAD, LOW_LEAD], existing_customers=set())

        self.assertEqual(mock_upsert_deal.call_count, 2)
        called_companies = {call.args[0]["company_name"] for call in mock_upsert_deal.call_args_list}
        self.assertEqual(called_companies, {HIGH_LEAD["company_name"], GOOD_LEAD["company_name"]})

        low_result = next(r for r in results if r["company_name"] == LOW_LEAD["company_name"])
        self.assertNotIn("hubspot_deal_id", low_result)

        # Every lead (including Low) still gets a note -- unlike Deals,
        # which are gated to High/Medium.
        self.assertEqual(mock_create_note.call_count, 3)

    @patch("hubspot_contacts.upsert_contact")
    @patch("hubspot_notes.create_triage_note")
    @patch("hubspot_notes.get_note_association_type_ids")
    @patch("hubspot_deals.upsert_deal")
    @patch("hubspot_deals.find_initial_stage_id")
    @patch("hubspot_deals.get_default_pipeline")
    @patch("hubspot_deals.ensure_custom_deal_properties")
    @patch("hubspot_crm.upsert_company")
    @patch("hubspot_crm.ensure_custom_properties")
    def test_skips_deal_note_and_contact_when_company_upsert_errored(
        self,
        mock_ensure_company_props,
        mock_upsert_company,
        mock_ensure_deal_props,
        mock_get_pipeline,
        mock_find_stage,
        mock_upsert_deal,
        mock_get_note_types,
        mock_create_note,
        mock_upsert_contact,
    ):
        mock_get_pipeline.return_value = SimpleNamespace(id="pipeline-1")
        mock_find_stage.return_value = "stage-1"
        mock_upsert_company.return_value = {
            "company_name": HIGH_LEAD["company_name"],
            "hubspot_company_id": None,
            "action": "error",
        }
        mock_get_note_types.return_value = {"company": 190, "deal": 214}

        export_leads_to_hubspot([HIGH_LEAD], existing_customers=set())

        mock_upsert_deal.assert_not_called()
        mock_create_note.assert_not_called()
        mock_upsert_contact.assert_not_called()


class ExportLeadsToHubspotNoteAndContactWiringTests(unittest.TestCase):
    @patch("hubspot_contacts.upsert_contact")
    @patch("hubspot_notes.create_triage_note")
    @patch("hubspot_notes.get_note_association_type_ids")
    @patch("hubspot_deals.upsert_deal")
    @patch("hubspot_deals.find_initial_stage_id")
    @patch("hubspot_deals.get_default_pipeline")
    @patch("hubspot_deals.ensure_custom_deal_properties")
    @patch("hubspot_crm.upsert_company")
    @patch("hubspot_crm.ensure_custom_properties")
    def test_note_gets_the_deal_id_and_contact_result_is_merged_in(
        self,
        mock_ensure_company_props,
        mock_upsert_company,
        mock_ensure_deal_props,
        mock_get_pipeline,
        mock_find_stage,
        mock_upsert_deal,
        mock_get_note_types,
        mock_create_note,
        mock_upsert_contact,
    ):
        mock_get_pipeline.return_value = SimpleNamespace(id="pipeline-1")
        mock_find_stage.return_value = "stage-1"
        mock_upsert_company.return_value = {
            "company_name": HIGH_LEAD["company_name"],
            "hubspot_company_id": "company-1",
            "action": "created",
        }
        mock_upsert_deal.return_value = {"hubspot_deal_id": "deal-1", "action": "created"}
        mock_get_note_types.return_value = {"company": 190, "deal": 214}
        mock_create_note.return_value = {"hubspot_note_id": "note-1", "action": "created"}
        mock_upsert_contact.return_value = {"hubspot_contact_id": "contact-1", "action": "created"}

        results = export_leads_to_hubspot([HIGH_LEAD], existing_customers=set())

        mock_create_note.assert_called_once_with(HIGH_LEAD, "company-1", {"company": 190, "deal": 214}, deal_id="deal-1")
        mock_upsert_contact.assert_called_once_with(HIGH_LEAD["contact"], "company-1", deal_id="deal-1")
        self.assertEqual(results[0]["hubspot_note_id"], "note-1")
        self.assertEqual(results[0]["hubspot_contact_id"], "contact-1")
        self.assertEqual(results[0]["contact_action"], "created")

    @patch("hubspot_contacts.upsert_contact")
    @patch("hubspot_notes.create_triage_note")
    @patch("hubspot_notes.get_note_association_type_ids")
    @patch("hubspot_deals.upsert_deal")
    @patch("hubspot_deals.find_initial_stage_id")
    @patch("hubspot_deals.get_default_pipeline")
    @patch("hubspot_deals.ensure_custom_deal_properties")
    @patch("hubspot_crm.upsert_company")
    @patch("hubspot_crm.ensure_custom_properties")
    def test_no_contact_key_added_to_result_when_none_grounded(
        self,
        mock_ensure_company_props,
        mock_upsert_company,
        mock_ensure_deal_props,
        mock_get_pipeline,
        mock_find_stage,
        mock_upsert_deal,
        mock_get_note_types,
        mock_create_note,
        mock_upsert_contact,
    ):
        mock_get_pipeline.return_value = SimpleNamespace(id="pipeline-1")
        mock_find_stage.return_value = "stage-1"
        mock_upsert_company.return_value = {
            "company_name": LOW_LEAD["company_name"],
            "hubspot_company_id": "company-1",
            "action": "created",
        }
        mock_get_note_types.return_value = {"company": 190, "deal": 214}
        mock_create_note.return_value = {"hubspot_note_id": "note-1", "action": "created"}
        mock_upsert_contact.return_value = None  # no email grounded

        results = export_leads_to_hubspot([LOW_LEAD], existing_customers=set())

        mock_create_note.assert_called_once_with(LOW_LEAD, "company-1", {"company": 190, "deal": 214}, deal_id=None)
        self.assertNotIn("hubspot_contact_id", results[0])
        self.assertNotIn("contact_action", results[0])


if __name__ == "__main__":
    unittest.main()
