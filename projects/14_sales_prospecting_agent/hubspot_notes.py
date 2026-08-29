import time

from hubspot.crm.associations.v4 import ApiException as AssociationApiException
from hubspot.crm.objects.notes import ApiException, PublicAssociationsForObject, SimplePublicObjectInputForCreate
from hubspot.crm.objects.notes.models.association_spec import AssociationSpec
from hubspot.crm.objects.notes.models.public_object_id import PublicObjectId

from hubspot_crm import get_hubspot_client

# Confirmed live against Alan's own HubSpot account's Notes property
# schema this session (client.crm.properties.core_api.get_all("notes")) --
# not assumed. hs_timestamp is a "datetime" property: HubSpot's own
# convention for that type is milliseconds since epoch, same as every
# other datetime property this project has touched.
NOTE_BODY_PROPERTY = "hs_note_body"
NOTE_TIMESTAMP_PROPERTY = "hs_timestamp"


def build_note_body(lead):
    return (
        f"Auto-triaged: {lead['score']}/{lead['band']}. "
        f"{lead['fit_reason']} Source: {lead['source']}."
    )


def get_note_association_type_ids(client=None):
    """Looks up the real HubSpot-defined default association type IDs for
    Note->Company and Note->Deal via the Associations Schema Definitions
    API -- Notes attach associations at create time (unlike
    hubspot_deals.upsert_deal's Company/Deal association, which has a
    separate create_default call that resolves the default type
    automatically), so there's no way to avoid knowing the numeric ID
    here. Confirmed live against Alan's real account this session:
    Note->Company is 190, Note->Deal is 214 -- not hardcoded from that
    observation, looked up fresh each call (cheap, and correct if a
    portal's association types ever change) so this can't silently go
    stale. Call once per run, same as hubspot_deals.get_default_pipeline,
    not once per lead.
    """
    client = client or get_hubspot_client()
    company_types = client.crm.associations.v4.schema.definitions_api.get_all(
        from_object_type="notes", to_object_type="companies"
    )
    deal_types = client.crm.associations.v4.schema.definitions_api.get_all(
        from_object_type="notes", to_object_type="deals"
    )
    return {
        "company": company_types.results[0].type_id,
        "deal": deal_types.results[0].type_id,
    }


def _association(to_object_id, association_type_id):
    return PublicAssociationsForObject(
        to=PublicObjectId(id=to_object_id),
        types=[AssociationSpec(association_category="HUBSPOT_DEFINED", association_type_id=association_type_id)],
    )


def create_triage_note(lead, company_id, association_type_ids, deal_id=None):
    """Logs one Note summarizing this lead's triage result, associated to
    the Company (always) and the Deal (if one exists for this lead).
    Fires for every lead regardless of fit band -- unlike a Deal, a note
    documenting "we checked this company, here's what we found" is useful
    even on a Low/Unknown record, so a reviewer never wonders whether it
    was actually evaluated.

    `association_type_ids` is the dict from get_note_association_type_ids()
    -- looked up once by the caller, not re-fetched per lead.
    """
    client = get_hubspot_client()
    properties = {
        NOTE_BODY_PROPERTY: build_note_body(lead),
        NOTE_TIMESTAMP_PROPERTY: str(int(time.time() * 1000)),
    }
    associations = [_association(company_id, association_type_ids["company"])]
    if deal_id:
        associations.append(_association(deal_id, association_type_ids["deal"]))

    try:
        response = client.crm.objects.notes.basic_api.create(
            simple_public_object_input_for_create=SimplePublicObjectInputForCreate(
                properties=properties, associations=associations
            )
        )
        return {"hubspot_note_id": response.id, "action": "created"}
    except (ApiException, AssociationApiException) as e:
        return {"hubspot_note_id": None, "action": "error", "error": str(e)}
