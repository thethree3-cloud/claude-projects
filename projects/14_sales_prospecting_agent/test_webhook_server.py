import base64
import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import patch

from webhook_server import app, verify_signature

CLIENT_SECRET = "test-client-secret"


def sign(method, uri, raw_body, timestamp, client_secret=CLIENT_SECRET):
    message = (method + uri + raw_body + timestamp).encode("utf-8")
    return base64.b64encode(hmac.new(client_secret.encode("utf-8"), message, hashlib.sha256).digest()).decode(
        "utf-8"
    )


class VerifySignatureTests(unittest.TestCase):
    def test_valid_signature_is_accepted(self):
        timestamp = str(int(time.time() * 1000))
        raw_body = b'{"hello":"world"}'
        signature = sign("POST", "https://example.trycloudflare.com/webhooks/hubspot", raw_body.decode(), timestamp)

        self.assertTrue(
            verify_signature(
                "POST", "https://example.trycloudflare.com/webhooks/hubspot", raw_body, timestamp, signature, CLIENT_SECRET
            )
        )

    def test_tampered_body_is_rejected(self):
        timestamp = str(int(time.time() * 1000))
        signature = sign("POST", "https://example.trycloudflare.com/webhooks/hubspot", '{"hello":"world"}', timestamp)

        self.assertFalse(
            verify_signature(
                "POST",
                "https://example.trycloudflare.com/webhooks/hubspot",
                b'{"hello":"tampered"}',
                timestamp,
                signature,
                CLIENT_SECRET,
            )
        )

    def test_wrong_secret_is_rejected(self):
        timestamp = str(int(time.time() * 1000))
        raw_body = b'{"hello":"world"}'
        signature = sign("POST", "https://example.trycloudflare.com/webhooks/hubspot", raw_body.decode(), timestamp)

        self.assertFalse(
            verify_signature(
                "POST",
                "https://example.trycloudflare.com/webhooks/hubspot",
                raw_body,
                timestamp,
                signature,
                "a-different-secret",
            )
        )

    def test_stale_timestamp_is_rejected(self):
        stale_timestamp = str(int(time.time() * 1000) - (10 * 60 * 1000))  # 10 minutes old
        raw_body = b'{"hello":"world"}'
        signature = sign(
            "POST", "https://example.trycloudflare.com/webhooks/hubspot", raw_body.decode(), stale_timestamp
        )

        self.assertFalse(
            verify_signature(
                "POST",
                "https://example.trycloudflare.com/webhooks/hubspot",
                raw_body,
                stale_timestamp,
                signature,
                CLIENT_SECRET,
            )
        )

    def test_missing_headers_are_rejected(self):
        self.assertFalse(
            verify_signature("POST", "https://example.trycloudflare.com/webhooks/hubspot", b"{}", None, None, CLIENT_SECRET)
        )


class WebhookRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def _post(self, payload, client_secret=CLIENT_SECRET, tamper=False):
        raw_body = json.dumps(payload).encode("utf-8")
        timestamp = str(int(time.time() * 1000))
        uri = "https://testserver/webhooks/hubspot"
        signature = sign("POST", uri, raw_body.decode(), timestamp, client_secret)
        if tamper:
            raw_body = raw_body + b" "  # changes the body after signing
        return self.client.post(
            "/webhooks/hubspot",
            data=raw_body,
            headers={
                "Host": "testserver",
                "Content-Type": "application/json",
                "X-HubSpot-Request-Timestamp": timestamp,
                "X-HubSpot-Signature-v3": signature,
            },
        )

    @patch.dict("os.environ", {"HUBSPOT_CLIENT_SECRET": CLIENT_SECRET})
    @patch("webhook_server.process_company_event_async")
    def test_valid_company_creation_event_processes_the_company(self, mock_process):
        response = self._post([{"subscriptionType": "company.creation", "objectId": 12345}])

        self.assertEqual(response.status_code, 200)
        mock_process.assert_called_once_with("12345")

    @patch.dict("os.environ", {"HUBSPOT_CLIENT_SECRET": CLIENT_SECRET})
    @patch("webhook_server.process_company_event_async")
    def test_non_company_event_is_ignored(self, mock_process):
        response = self._post([{"subscriptionType": "contact.creation", "objectId": 999}])

        self.assertEqual(response.status_code, 200)
        mock_process.assert_not_called()

    @patch.dict("os.environ", {"HUBSPOT_CLIENT_SECRET": CLIENT_SECRET})
    @patch("webhook_server.process_company_event_async")
    def test_invalid_signature_is_rejected_and_not_processed(self, mock_process):
        response = self._post([{"subscriptionType": "company.creation", "objectId": 12345}], tamper=True)

        self.assertEqual(response.status_code, 401)
        mock_process.assert_not_called()

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_client_secret_returns_500(self):
        response = self.client.post("/webhooks/hubspot", data=b"[]", headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 500)


class ProcessCompanyEventAsyncTests(unittest.TestCase):
    @patch("webhook_server.process_company_event")
    def test_runs_process_company_event_on_a_background_thread_not_inline(self, mock_process):
        # A slow, blocking real call (mocked here as a sleep) must not
        # delay the wrapper's own return -- that's the whole point of the
        # fix: HubSpot's retry storm was caused by this work blocking the
        # HTTP response.
        mock_process.side_effect = lambda company_id: time.sleep(0.2)

        from webhook_server import process_company_event_async

        started = time.time()
        process_company_event_async("company-1")
        elapsed = time.time() - started

        self.assertLess(elapsed, 0.1, "process_company_event_async should return immediately, not block")

        time.sleep(0.3)  # let the background thread finish before asserting
        mock_process.assert_called_once_with("company-1")


class ProcessCompanyEventTests(unittest.TestCase):
    @patch("webhook_server.export_leads_to_hubspot")
    @patch("webhook_server.evaluate_lead")
    @patch("webhook_server.find_existing_customer_names")
    @patch("webhook_server.get_hubspot_client")
    def test_scores_and_exports_the_company_by_name(
        self, mock_get_client, mock_find_customers, mock_evaluate, mock_export
    ):
        from types import SimpleNamespace

        from webhook_server import process_company_event

        mock_client = mock_get_client.return_value
        mock_client.crm.companies.basic_api.get_by_id.return_value = SimpleNamespace(
            properties={"name": "Polytronix Inc"}
        )
        mock_find_customers.return_value = {"existing co"}
        mock_evaluate.return_value = {"company_name": "Polytronix Inc", "score": 60, "band": "Medium"}

        process_company_event("company-1")

        mock_evaluate.assert_called_once()
        self.assertEqual(mock_evaluate.call_args[0][0], "Polytronix Inc")
        mock_export.assert_called_once_with(
            [{"company_name": "Polytronix Inc", "score": 60, "band": "Medium"}], {"existing co"}
        )

    @patch("webhook_server.export_leads_to_hubspot")
    @patch("webhook_server.get_hubspot_client")
    def test_company_with_no_name_is_skipped(self, mock_get_client, mock_export):
        from types import SimpleNamespace

        from webhook_server import process_company_event

        mock_client = mock_get_client.return_value
        mock_client.crm.companies.basic_api.get_by_id.return_value = SimpleNamespace(properties={})

        process_company_event("company-1")

        mock_export.assert_not_called()


if __name__ == "__main__":
    unittest.main()
