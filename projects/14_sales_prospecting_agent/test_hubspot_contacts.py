import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hubspot_contacts import build_contact_properties, find_existing_contact_id, upsert_contact

GOOD_CONTACT = {
    "name": "Jordan Reyes",
    "title": "VP of Sales",
    "email": "jordan.reyes@example.com",
    "insufficient_information": False,
}
NO_CONTACT = {"name": None, "title": None, "email": None, "insufficient_information": True}


class BuildContactPropertiesTests(unittest.TestCase):
    def test_splits_first_and_last_name(self):
        props = build_contact_properties(GOOD_CONTACT)
        self.assertEqual(props["firstname"], "Jordan")
        self.assertEqual(props["lastname"], "Reyes")
        self.assertEqual(props["email"], "jordan.reyes@example.com")
        self.assertEqual(props["jobtitle"], "VP of Sales")

    def test_single_word_name_has_no_lastname(self):
        props = build_contact_properties({"name": "Cher", "title": None, "email": "cher@example.com"})
        self.assertEqual(props["firstname"], "Cher")
        self.assertNotIn("lastname", props)
        self.assertNotIn("jobtitle", props)


class FindExistingContactIdTests(unittest.TestCase):
    @patch("hubspot_contacts.get_hubspot_client")
    def test_returns_id_when_found(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.crm.contacts.search_api.do_search.return_value = SimpleNamespace(
            total=1, results=[SimpleNamespace(id="c1")]
        )
        mock_get_client.return_value = mock_client
        self.assertEqual(find_existing_contact_id("jordan.reyes@example.com"), "c1")

    @patch("hubspot_contacts.get_hubspot_client")
    def test_returns_none_when_not_found(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.crm.contacts.search_api.do_search.return_value = SimpleNamespace(total=0, results=[])
        mock_get_client.return_value = mock_client
        self.assertIsNone(find_existing_contact_id("nobody@example.com"))


class UpsertContactTests(unittest.TestCase):
    def test_skips_when_no_email_grounded(self):
        result = upsert_contact(NO_CONTACT, company_id="company-1")
        self.assertIsNone(result)

    @patch("hubspot_contacts.find_existing_contact_id")
    @patch("hubspot_contacts.get_hubspot_client")
    def test_creates_and_associates_to_company_when_no_existing_match(self, mock_get_client, mock_find):
        mock_find.return_value = None
        mock_client = MagicMock()
        mock_client.crm.contacts.basic_api.create.return_value = SimpleNamespace(id="new-contact-id")
        mock_get_client.return_value = mock_client

        result = upsert_contact(GOOD_CONTACT, company_id="company-1")

        mock_client.crm.contacts.basic_api.create.assert_called_once()
        mock_client.crm.associations.v4.basic_api.create_default.assert_called_once_with(
            from_object_type="contacts", from_object_id="new-contact-id", to_object_type="companies", to_object_id="company-1"
        )
        self.assertEqual(result["action"], "created")
        self.assertEqual(result["hubspot_contact_id"], "new-contact-id")

    @patch("hubspot_contacts.find_existing_contact_id")
    @patch("hubspot_contacts.get_hubspot_client")
    def test_creates_and_associates_to_deal_when_given(self, mock_get_client, mock_find):
        mock_find.return_value = None
        mock_client = MagicMock()
        mock_client.crm.contacts.basic_api.create.return_value = SimpleNamespace(id="new-contact-id")
        mock_get_client.return_value = mock_client

        upsert_contact(GOOD_CONTACT, company_id="company-1", deal_id="deal-1")

        self.assertEqual(mock_client.crm.associations.v4.basic_api.create_default.call_count, 2)
        second_call = mock_client.crm.associations.v4.basic_api.create_default.call_args_list[1]
        self.assertEqual(second_call.kwargs["to_object_type"], "deals")
        self.assertEqual(second_call.kwargs["to_object_id"], "deal-1")

    @patch("hubspot_contacts.find_existing_contact_id")
    @patch("hubspot_contacts.get_hubspot_client")
    def test_updates_without_associating_when_existing_match_found(self, mock_get_client, mock_find):
        mock_find.return_value = "existing-contact-id"
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = upsert_contact(GOOD_CONTACT, company_id="company-1")

        mock_client.crm.contacts.basic_api.update.assert_called_once()
        mock_client.crm.contacts.basic_api.create.assert_not_called()
        mock_client.crm.associations.v4.basic_api.create_default.assert_not_called()
        self.assertEqual(result["action"], "updated")

    @patch("hubspot_contacts.find_existing_contact_id")
    @patch("hubspot_contacts.get_hubspot_client")
    def test_api_error_is_caught_not_raised(self, mock_get_client, mock_find):
        from hubspot.crm.contacts import ApiException

        mock_find.return_value = None
        mock_client = MagicMock()
        mock_client.crm.contacts.basic_api.create.side_effect = ApiException(status=500)
        mock_get_client.return_value = mock_client

        result = upsert_contact(GOOD_CONTACT, company_id="company-1")

        self.assertEqual(result["action"], "error")
        self.assertIsNone(result["hubspot_contact_id"])


if __name__ == "__main__":
    unittest.main()
