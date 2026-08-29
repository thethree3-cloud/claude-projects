"""Receives HubSpot webhooks and reacts to them -- the first part of
Project 14 that runs itself instead of being kicked off by a driver
script. Subscribed (in the HubSpot Private App's Webhooks tab, not via
code -- HubSpot doesn't expose webhook subscription management through
the API) to "Company created": when a Company is added to HubSpot by any
means, this fires, and the exact same pipeline the driver scripts already
use scores and routes it automatically.

Requires a HubSpot **Private App**, not the Service Key used elsewhere in
this project -- Service Keys don't support webhooks. See README "Slice 9"
for the full setup (Private App creation, HUBSPOT_CLIENT_SECRET, and
exposing this server with cloudflared).

Processing happens synchronously in the request handler -- a known
simplification, not a production design. HubSpot expects a fast ack and
may retry on timeout; a real version would ack immediately and process on
a background worker/queue instead.
"""

import base64
import hashlib
import hmac
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request

from hubspot_crm import export_leads_to_hubspot, get_hubspot_client
from hubspot_deals import find_existing_customer_names
from pipeline import evaluate_lead

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH)

CLIENT_PROFILE_PATH = "data/sample_client_profile.yaml"
TERRITORY_ROUTING_PATH = "data/sample_territory_routing.csv"

# HubSpot considers a request stale (possible replay) past this age.
MAX_TIMESTAMP_AGE_MS = 5 * 60 * 1000

app = Flask(__name__)


def verify_signature(method, uri, raw_body, timestamp_header, signature_header, client_secret):
    """HubSpot's v3 webhook signature scheme: HMAC-SHA256 over
    method + uri + raw_body + timestamp, keyed with the Private App's
    Client Secret, compared against X-HubSpot-Signature-v3. Also rejects
    a stale timestamp (> 5 minutes old) as replay protection.

    `uri` must be the full absolute URL HubSpot actually sent the request
    to (e.g. "https://your-tunnel.trycloudflare.com/webhooks/hubspot"),
    confirmed against HubSpot's own signature-validation examples -- not
    just the path. This matters here specifically because the request
    arrives through a tunnel: Flask's own view of the connection is
    plain HTTP to localhost, not the public HTTPS URL HubSpot signed
    against, so the caller has to reconstruct the real one (see the route
    below) rather than trusting `request.url`.

    Takes plain values, not a Flask request object, so this is a pure,
    easily-testable function -- the route below is the only thing that
    reads from `request`.
    """
    if not timestamp_header or not signature_header:
        return False

    try:
        age_ms = int(time.time() * 1000) - int(timestamp_header)
    except ValueError:
        return False
    if age_ms > MAX_TIMESTAMP_AGE_MS:
        return False

    message = (method + uri + raw_body.decode("utf-8") + timestamp_header).encode("utf-8")
    expected = base64.b64encode(hmac.new(client_secret.encode("utf-8"), message, hashlib.sha256).digest())
    return hmac.compare_digest(expected, signature_header.encode("utf-8"))


def process_company_event(company_id):
    """Runs one Company through the exact same scoring/routing/export
    chain the driver scripts already use -- this function is the only new
    business logic in this slice; everything it calls was already built
    and tested in earlier slices."""
    client = get_hubspot_client()
    company = client.crm.companies.basic_api.get_by_id(company_id=company_id, properties=["name"])
    company_name = company.properties.get("name")
    if not company_name:
        print(f"Company {company_id} has no name property, skipping.")
        return

    print(f"Webhook: new company {company_name!r} ({company_id}) -- scoring...")
    existing_customers = find_existing_customer_names(client)
    lead = evaluate_lead(company_name, CLIENT_PROFILE_PATH, TERRITORY_ROUTING_PATH)
    results = export_leads_to_hubspot([lead], existing_customers)
    print(f"Webhook: {company_name} -> {lead['score']}/{lead['band']}, exported: {results[0]}")


def process_company_event_async(company_id):
    """Kicks off process_company_event() on a background thread instead of
    running it inline. HubSpot expects a fast ack and retries (with the
    same eventId, escalating attemptNumber) if the response is too slow --
    confirmed live: the real scoring/export chain (a live web search plus
    several live HubSpot calls) easily took long enough to trigger repeat
    deliveries of the same event, each one redoing all that live work.
    Idempotent upsert (Slice 8) meant no duplicate records were created,
    but it was still wasted API calls and cost. Returning the HTTP
    response immediately and doing the real work here fixes that."""
    threading.Thread(target=process_company_event, args=(company_id,), daemon=True).start()


@app.route("/webhooks/hubspot", methods=["POST"])
def hubspot_webhook():
    client_secret = os.environ.get("HUBSPOT_CLIENT_SECRET")
    if not client_secret:
        return {"error": "HUBSPOT_CLIENT_SECRET not configured"}, 500

    raw_body = request.get_data()
    # HubSpot signs the full absolute URL it actually called. cloudflared
    # preserves the original Host header (the public tunnel hostname), but
    # the connection Flask sees is plain HTTP to localhost -- so the
    # scheme has to be assumed "https" rather than read from the request;
    # HubSpot only ever calls webhooks over https.
    full_uri = f"https://{request.host}{request.path}"
    if request.query_string:
        full_uri += f"?{request.query_string.decode('utf-8')}"
    signed = verify_signature(
        method=request.method,
        uri=full_uri,
        raw_body=raw_body,
        timestamp_header=request.headers.get("X-HubSpot-Request-Timestamp"),
        signature_header=request.headers.get("X-HubSpot-Signature-v3"),
        client_secret=client_secret,
    )
    if not signed:
        print("Webhook: signature verification failed, dropping request.")
        return {"error": "invalid signature"}, 401

    events = request.get_json(silent=True) or []
    print(f"Webhook: received {len(events)} event(s): {events}")

    for event in events:
        subscription_type = event.get("subscriptionType", "")
        if subscription_type.startswith("company."):
            company_id = event.get("objectId")
            if company_id:
                process_company_event_async(str(company_id))

    return {"status": "ok"}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
