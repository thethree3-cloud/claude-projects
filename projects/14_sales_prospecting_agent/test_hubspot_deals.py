import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hubspot_deals import (
    build_deal_name,
    build_deal_properties,
    find_closed_won_stage_ids,
    find_existing_customer_names,
    find_existing_deal_id,
    find_initial_stage_id,
    get_default_pipeline,
    upsert_deal,
)

GOOD_LEAD = {"company_name": "Polytronix Inc", "score": 60, "band": "Medium"}


def _pipeline(pipeline_id, display_order, archived, stages):
    return SimpleNamespace(id=pipeline_id, display_order=display_order, archived=archived, stages=stages)


def _stage(stage_id, display_order, archived=False, metadata=None):
    return SimpleNamespace(id=stage_id, display_order=display_order, archived=archived, metadata=metadata or {})


class GetDefaultPipelineTests(unittest.TestCase):
    def test_picks_lowest_display_order_among_non_archived(self):
        client = MagicMock()
        client.crm.pipelines.pipelines_api.get_all.return_value = SimpleNamespace(
            results=[
                _pipeline("archived-first", 0, True, []),
                _pipeline("second", 1, False, []),
                _pipeline("first", 2, False, []),
            ]
        )
        pipeline = get_default_pipeline(client)
        self.assertEqual(pipeline.id, "second")


class FindInitialStageIdTests(unittest.TestCase):
    def test_picks_lowest_display_order_stage(self):
        pipeline = _pipeline(
            "p1",
            0,
            False,
            [_stage("archived", 0, archived=True), _stage("later", 5), _stage("first", 1)],
        )
        self.assertEqual(find_initial_stage_id(pipeline), "first")


class FindClosedWonStageIdsTests(unittest.TestCase):
    def test_matches_only_closed_and_full_probability(self):
        pipeline = _pipeline(
            "p1",
            0,
            False,
            [
                _stage("open", 0, metadata={"isClosed": "false", "probability": "0.0"}),
                _stage("closed-lost", 1, metadata={"isClosed": "true", "probability": "0.0"}),
                _stage("closed-won", 2, metadata={"isClosed": "true", "probability": "1.0"}),
            ],
        )
        self.assertEqual(find_closed_won_stage_ids(pipeline), ["closed-won"])

    def test_no_closed_won_stage_returns_empty_list(self):
        pipeline = _pipeline("p1", 0, False, [_stage("open", 0, metadata={"isClosed": "false"})])
        self.assertEqual(find_closed_won_stage_ids(pipeline), [])


class BuildDealTests(unittest.TestCase):
    def test_build_deal_name(self):
        self.assertEqual(build_deal_name(GOOD_LEAD), "Polytronix Inc — Prospecting Lead")

    def test_build_deal_properties(self):
        props = build_deal_properties(GOOD_LEAD, pipeline_id="p1", stage_id="s1")
        self.assertEqual(props["dealname"], "Polytronix Inc — Prospecting Lead")
        self.assertEqual(props["pipeline"], "p1")
        self.assertEqual(props["dealstage"], "s1")
        self.assertEqual(props["fit_score"], "60")
        self.assertEqual(props["fit_band"], "Medium")


class FindExistingDealIdTests(unittest.TestCase):
    @patch("hubspot_deals.get_hubspot_client")
    def test_returns_id_when_found(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.crm.deals.search_api.do_search.return_value = SimpleNamespace(
            total=1, results=[SimpleNamespace(id="d1")]
        )
        mock_get_client.return_value = mock_client
        self.assertEqual(find_existing_deal_id("Polytronix Inc — Prospecting Lead"), "d1")

    @patch("hubspot_deals.get_hubspot_client")
    def test_returns_none_when_not_found(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.crm.deals.search_api.do_search.return_value = SimpleNamespace(total=0, results=[])
        mock_get_client.return_value = mock_client
        self.assertIsNone(find_existing_deal_id("Nonexistent Co — Prospecting Lead"))


class UpsertDealTests(unittest.TestCase):
    @patch("hubspot_deals.find_existing_deal_id")
    @patch("hubspot_deals.get_hubspot_client")
    def test_creates_and_associates_when_no_existing_match(self, mock_get_client, mock_find):
        mock_find.return_value = None
        mock_client = MagicMock()
        mock_client.crm.deals.basic_api.create.return_value = SimpleNamespace(id="new-deal-id")
        mock_get_client.return_value = mock_client

        result = upsert_deal(GOOD_LEAD, company_id="company-1", pipeline_id="p1", stage_id="s1")

        mock_client.crm.deals.basic_api.create.assert_called_once()
        mock_client.crm.deals.basic_api.update.assert_not_called()
        mock_client.crm.associations.v4.basic_api.create_default.assert_called_once_with(
            from_object_type="deals", from_object_id="new-deal-id", to_object_type="companies", to_object_id="company-1"
        )
        self.assertEqual(result["action"], "created")
        self.assertEqual(result["hubspot_deal_id"], "new-deal-id")

    @patch("hubspot_deals.find_existing_deal_id")
    @patch("hubspot_deals.get_hubspot_client")
    def test_updates_without_re_associating(self, mock_get_client, mock_find):
        mock_find.return_value = "existing-deal-id"
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = upsert_deal(GOOD_LEAD, company_id="company-1", pipeline_id="p1", stage_id="s1")

        mock_client.crm.deals.basic_api.update.assert_called_once()
        mock_client.crm.deals.basic_api.create.assert_not_called()
        mock_client.crm.associations.v4.basic_api.create_default.assert_not_called()
        self.assertEqual(result["action"], "updated")
        self.assertEqual(result["hubspot_deal_id"], "existing-deal-id")

    @patch("hubspot_deals.find_existing_deal_id")
    @patch("hubspot_deals.get_hubspot_client")
    def test_api_error_is_caught_not_raised(self, mock_get_client, mock_find):
        from hubspot.crm.deals import ApiException

        mock_find.return_value = None
        mock_client = MagicMock()
        mock_client.crm.deals.basic_api.create.side_effect = ApiException(status=500)
        mock_get_client.return_value = mock_client

        result = upsert_deal(GOOD_LEAD, company_id="company-1", pipeline_id="p1", stage_id="s1")

        self.assertEqual(result["action"], "error")
        self.assertIsNone(result["hubspot_deal_id"])


class AssociateDealToCompanyTests(unittest.TestCase):
    @patch("hubspot_deals.get_hubspot_client")
    def test_calls_create_default_with_deal_and_company(self, mock_get_client):
        from hubspot_deals import associate_deal_to_company

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        associate_deal_to_company("deal-1", "company-1")

        mock_client.crm.associations.v4.basic_api.create_default.assert_called_once_with(
            from_object_type="deals", from_object_id="deal-1", to_object_type="companies", to_object_id="company-1"
        )


class FindExistingCustomerNamesTests(unittest.TestCase):
    @patch("hubspot_deals.get_default_pipeline")
    def test_no_closed_won_stage_returns_empty_set_without_searching_deals(self, mock_get_pipeline):
        pipeline = _pipeline("p1", 0, False, [_stage("open", 0, metadata={"isClosed": "false"})])
        mock_get_pipeline.return_value = pipeline
        client = MagicMock()

        result = find_existing_customer_names(client)

        self.assertEqual(result, set())
        client.crm.deals.search_api.do_search.assert_not_called()

    @patch("hubspot_deals.get_default_pipeline")
    def test_returns_lowercased_names_of_companies_on_closed_won_deals(self, mock_get_pipeline):
        pipeline = _pipeline(
            "p1", 0, False, [_stage("won", 0, metadata={"isClosed": "true", "probability": "1.0"})]
        )
        mock_get_pipeline.return_value = pipeline

        client = MagicMock()
        client.crm.deals.search_api.do_search.return_value = SimpleNamespace(
            results=[SimpleNamespace(id="deal-1")]
        )
        client.crm.associations.batch_api.read.return_value = SimpleNamespace(
            results=[SimpleNamespace(to=[SimpleNamespace(id="company-1")])]
        )
        client.crm.companies.batch_api.read.return_value = SimpleNamespace(
            results=[SimpleNamespace(properties={"name": "Polytronix Inc"})]
        )

        result = find_existing_customer_names(client)

        self.assertEqual(result, {"polytronix inc"})
        # One batch association read for all deals, not one get_page per deal.
        client.crm.associations.batch_api.read.assert_called_once()
        read_call = client.crm.associations.batch_api.read.call_args
        self.assertEqual(read_call.kwargs["from_object_type"], "deals")
        self.assertEqual(read_call.kwargs["to_object_type"], "companies")
        # One batch company read for all resulting companies, not one
        # get_by_id per company.
        client.crm.companies.batch_api.read.assert_called_once()

    @patch("hubspot_deals.get_default_pipeline")
    def test_no_matching_deals_returns_empty_set_without_reading_associations(self, mock_get_pipeline):
        pipeline = _pipeline(
            "p1", 0, False, [_stage("won", 0, metadata={"isClosed": "true", "probability": "1.0"})]
        )
        mock_get_pipeline.return_value = pipeline

        client = MagicMock()
        client.crm.deals.search_api.do_search.return_value = SimpleNamespace(results=[])

        result = find_existing_customer_names(client)

        self.assertEqual(result, set())
        client.crm.associations.batch_api.read.assert_not_called()

    @patch("hubspot_deals.get_default_pipeline")
    def test_no_associated_companies_returns_empty_set_without_reading_companies(self, mock_get_pipeline):
        pipeline = _pipeline(
            "p1", 0, False, [_stage("won", 0, metadata={"isClosed": "true", "probability": "1.0"})]
        )
        mock_get_pipeline.return_value = pipeline

        client = MagicMock()
        client.crm.deals.search_api.do_search.return_value = SimpleNamespace(
            results=[SimpleNamespace(id="deal-1")]
        )
        client.crm.associations.batch_api.read.return_value = SimpleNamespace(results=[SimpleNamespace(to=[])])

        result = find_existing_customer_names(client)

        self.assertEqual(result, set())
        client.crm.companies.batch_api.read.assert_not_called()

    @patch("hubspot_deals.get_default_pipeline")
    def test_association_batch_read_failure_returns_empty_set(self, mock_get_pipeline):
        from hubspot.crm.associations import ApiException as AssociationBatchApiException

        pipeline = _pipeline(
            "p1", 0, False, [_stage("won", 0, metadata={"isClosed": "true", "probability": "1.0"})]
        )
        mock_get_pipeline.return_value = pipeline

        client = MagicMock()
        client.crm.deals.search_api.do_search.return_value = SimpleNamespace(
            results=[SimpleNamespace(id="deal-1")]
        )
        client.crm.associations.batch_api.read.side_effect = AssociationBatchApiException(status=500)

        result = find_existing_customer_names(client)

        self.assertEqual(result, set())


if __name__ == "__main__":
    unittest.main()
