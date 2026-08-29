import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hubspot_notes import build_note_body, create_triage_note, get_note_association_type_ids

GOOD_LEAD = {
    "company_name": "Polytronix Inc",
    "score": 60,
    "band": "Medium",
    "fit_reason": "Matched 3 of 9 signals: rugged, avionics, defense-related",
    "source": "Web search",
}
ASSOCIATION_TYPE_IDS = {"company": 190, "deal": 214}


class BuildNoteBodyTests(unittest.TestCase):
    def test_includes_score_band_reason_and_source(self):
        body = build_note_body(GOOD_LEAD)
        self.assertIn("60/Medium", body)
        self.assertIn("Matched 3 of 9 signals", body)
        self.assertIn("Web search", body)


class GetNoteAssociationTypeIdsTests(unittest.TestCase):
    def test_returns_company_and_deal_type_ids(self):
        client = MagicMock()
        client.crm.associations.v4.schema.definitions_api.get_all.side_effect = [
            SimpleNamespace(results=[SimpleNamespace(type_id=190)]),
            SimpleNamespace(results=[SimpleNamespace(type_id=214)]),
        ]

        result = get_note_association_type_ids(client)

        self.assertEqual(result, {"company": 190, "deal": 214})
        client.crm.associations.v4.schema.definitions_api.get_all.assert_any_call(
            from_object_type="notes", to_object_type="companies"
        )
        client.crm.associations.v4.schema.definitions_api.get_all.assert_any_call(
            from_object_type="notes", to_object_type="deals"
        )


class CreateTriageNoteTests(unittest.TestCase):
    @patch("hubspot_notes.get_hubspot_client")
    def test_creates_note_associated_to_company_only(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.crm.objects.notes.basic_api.create.return_value = SimpleNamespace(id="note-1")
        mock_get_client.return_value = mock_client

        result = create_triage_note(GOOD_LEAD, company_id="company-1", association_type_ids=ASSOCIATION_TYPE_IDS)

        self.assertEqual(result["action"], "created")
        self.assertEqual(result["hubspot_note_id"], "note-1")
        create_call = mock_client.crm.objects.notes.basic_api.create.call_args
        note_input = create_call.kwargs["simple_public_object_input_for_create"]
        self.assertEqual(len(note_input.associations), 1)
        self.assertEqual(note_input.associations[0].to.id, "company-1")
        self.assertEqual(note_input.associations[0].types[0].association_type_id, 190)

    @patch("hubspot_notes.get_hubspot_client")
    def test_creates_note_associated_to_company_and_deal(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.crm.objects.notes.basic_api.create.return_value = SimpleNamespace(id="note-1")
        mock_get_client.return_value = mock_client

        create_triage_note(
            GOOD_LEAD, company_id="company-1", association_type_ids=ASSOCIATION_TYPE_IDS, deal_id="deal-1"
        )

        note_input = mock_client.crm.objects.notes.basic_api.create.call_args.kwargs[
            "simple_public_object_input_for_create"
        ]
        self.assertEqual(len(note_input.associations), 2)
        self.assertEqual(note_input.associations[1].to.id, "deal-1")
        self.assertEqual(note_input.associations[1].types[0].association_type_id, 214)

    @patch("hubspot_notes.get_hubspot_client")
    def test_api_error_is_caught_not_raised(self, mock_get_client):
        from hubspot.crm.objects.notes import ApiException

        mock_client = MagicMock()
        mock_client.crm.objects.notes.basic_api.create.side_effect = ApiException(status=500)
        mock_get_client.return_value = mock_client

        result = create_triage_note(GOOD_LEAD, company_id="company-1", association_type_ids=ASSOCIATION_TYPE_IDS)

        self.assertEqual(result["action"], "error")
        self.assertIsNone(result["hubspot_note_id"])


if __name__ == "__main__":
    unittest.main()
