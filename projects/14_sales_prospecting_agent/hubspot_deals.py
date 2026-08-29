from hubspot.crm.associations import ApiException as AssociationBatchApiException
from hubspot.crm.associations import BatchInputPublicObjectId
from hubspot.crm.associations import PublicObjectId as AssociationObjectId
from hubspot.crm.associations.v4 import ApiException as AssociationApiException
from hubspot.crm.companies import ApiException as CompanyApiException
from hubspot.crm.companies import BatchReadInputSimplePublicObjectId
from hubspot.crm.companies import SimplePublicObjectId as CompanyObjectId
from hubspot.crm.deals import (
    ApiException,
    Filter,
    FilterGroup,
    PublicObjectSearchRequest,
    SimplePublicObjectInput,
    SimplePublicObjectInputForCreate,
)
from hubspot.crm.properties import ApiException as PropertiesApiException
from hubspot.crm.properties import PropertyCreate

from hubspot_crm import _options, get_hubspot_client

# HubSpot's own convention for marking a pipeline stage as "won" -- a
# closed stage with 100% probability. There's no dedicated boolean field
# for this; metadata is a plain dict[str, str], so these are string
# comparisons, not booleans.
CLOSED_METADATA_KEY = "isClosed"
PROBABILITY_METADATA_KEY = "probability"
WON_PROBABILITY = "1.0"

CUSTOM_DEAL_PROPERTIES = [
    {
        "name": "fit_score",
        "label": "Fit Score",
        "type": "number",
        "field_type": "number",
        "group_name": "dealinformation",
    },
    {
        "name": "fit_band",
        "label": "Fit Band",
        "type": "enumeration",
        "field_type": "select",
        "group_name": "dealinformation",
        "options": _options(["High", "Medium", "Low", "Unknown"]),
    },
]


def get_default_pipeline(client=None):
    """Returns the first (lowest display_order, non-archived) Deals
    pipeline. A portfolio/sandbox account has exactly one; picking the
    first is a documented simplification for accounts with more, same
    spirit as find_existing_company_id()'s name-not-domain limitation."""
    client = client or get_hubspot_client()
    response = client.crm.pipelines.pipelines_api.get_all("deals")
    pipelines = [p for p in response.results if not p.archived]
    return min(pipelines, key=lambda p: p.display_order)


def find_initial_stage_id(pipeline):
    """The stage a new deal enters -- lowest display_order."""
    stages = [s for s in pipeline.stages if not s.archived]
    return min(stages, key=lambda s: s.display_order).id


def find_closed_won_stage_ids(pipeline):
    """Stages HubSpot itself considers "won": closed with 100% probability.
    Returns a list -- most pipelines have exactly one such stage, but
    nothing guarantees only one."""
    return [
        s.id
        for s in pipeline.stages
        if s.metadata.get(CLOSED_METADATA_KEY) == "true"
        and s.metadata.get(PROBABILITY_METADATA_KEY) == WON_PROBABILITY
    ]


def ensure_custom_deal_properties():
    """Creates fit_score/fit_band custom Deal properties if they don't
    already exist. One-time setup, same pattern as
    hubspot_crm.ensure_custom_properties() -- call once per run, not once
    per lead."""
    client = get_hubspot_client()
    for prop in CUSTOM_DEAL_PROPERTIES:
        try:
            client.crm.properties.core_api.get_by_name("deals", prop["name"])
        except PropertiesApiException as e:
            if e.status == 404:
                client.crm.properties.core_api.create("deals", PropertyCreate(**prop))
            else:
                raise


def build_deal_name(lead):
    return f"{lead['company_name']} — Prospecting Lead"


def build_deal_properties(lead, pipeline_id, stage_id):
    return {
        "dealname": build_deal_name(lead),
        "pipeline": pipeline_id,
        "dealstage": stage_id,
        "fit_score": str(lead["score"]),
        "fit_band": lead["band"],
    }


def find_existing_deal_id(dealname):
    """Searches by the "dealname" property (exact match) -- same
    search-before-create idempotency pattern as
    hubspot_crm.find_existing_company_id()."""
    client = get_hubspot_client()
    request = PublicObjectSearchRequest(
        filter_groups=[FilterGroup(filters=[Filter(property_name="dealname", operator="EQ", value=dealname)])],
        limit=1,
    )
    response = client.crm.deals.search_api.do_search(public_object_search_request=request)
    if response.total > 0:
        return response.results[0].id
    return None


def associate_deal_to_company(deal_id, company_id):
    """The "most generic" default association between the two object
    types, so no association_type_id has to be looked up or guessed --
    same principle as hubspot_notes.get_note_association_type_ids() had
    to work around by hand, since Notes have no create_default
    equivalent."""
    client = get_hubspot_client()
    client.crm.associations.v4.basic_api.create_default(
        from_object_type="deals",
        from_object_id=deal_id,
        to_object_type="companies",
        to_object_id=company_id,
    )


def upsert_deal(lead, company_id, pipeline_id, stage_id):
    """Creates or updates one Deal for a lead, associated to its Company.

    Only associates on create -- an update means the deal (and its
    association) already exists from a prior run, same idempotent-upsert
    shape as hubspot_crm.upsert_company. Catches ApiException per record
    rather than crashing a whole batch."""
    client = get_hubspot_client()
    dealname = build_deal_name(lead)
    properties = build_deal_properties(lead, pipeline_id, stage_id)

    try:
        existing_id = find_existing_deal_id(dealname)
        if existing_id:
            client.crm.deals.basic_api.update(
                deal_id=existing_id,
                simple_public_object_input=SimplePublicObjectInput(properties=properties),
            )
            return {"dealname": dealname, "hubspot_deal_id": existing_id, "action": "updated"}

        response = client.crm.deals.basic_api.create(
            simple_public_object_input_for_create=SimplePublicObjectInputForCreate(properties=properties),
        )
        deal_id = response.id
        associate_deal_to_company(deal_id, company_id)
        return {"dealname": dealname, "hubspot_deal_id": deal_id, "action": "created"}
    except (ApiException, AssociationApiException) as e:
        return {"dealname": dealname, "hubspot_deal_id": None, "action": "error", "error": str(e)}


def find_existing_customer_names(client=None):
    """Live replacement for existing_customers.load_existing_customers():
    returns the same {lowercased company name} shape, sourced from
    HubSpot's own closed-won deals instead of a static file.

    existing_customers.is_existing_customer() needs zero changes to work
    against this -- it already takes a plain lowercased-name set and does
    case-insensitive exact matching, regardless of where the set came
    from.

    Three API round trips total, not one per deal/company: search deals
    in a closed-won stage (unchanged, a single search call), then one
    **batch** read of all their associations, then one **batch** read of
    all the resulting companies' names. The association batch read uses
    the **v3** associations Batch API (`hubspot.crm.associations.BatchApi`)
    -- confirmed live this session that v4 (`associations.v4.BatchApi`,
    used elsewhere in this file for single-record association creation)
    has no batch *read* at all, only `get_page`/`create_default`/`archive`
    -- a real inconsistency in the SDK's surface, not something this code
    can avoid by staying on v4 throughout.
    """
    client = client or get_hubspot_client()
    pipeline = get_default_pipeline(client)
    closed_won_stage_ids = find_closed_won_stage_ids(pipeline)
    if not closed_won_stage_ids:
        return set()

    request = PublicObjectSearchRequest(
        filter_groups=[
            FilterGroup(filters=[Filter(property_name="dealstage", operator="IN", values=closed_won_stage_ids)])
        ],
        limit=100,
    )
    deals_response = client.crm.deals.search_api.do_search(public_object_search_request=request)
    deal_ids = [deal.id for deal in deals_response.results]
    if not deal_ids:
        return set()

    try:
        assoc_response = client.crm.associations.batch_api.read(
            from_object_type="deals",
            to_object_type="companies",
            batch_input_public_object_id=BatchInputPublicObjectId(
                inputs=[AssociationObjectId(id=deal_id) for deal_id in deal_ids]
            ),
        )
    except AssociationBatchApiException:
        return set()

    company_ids = {associated.id for result in assoc_response.results for associated in result.to}
    if not company_ids:
        return set()

    try:
        companies_response = client.crm.companies.batch_api.read(
            batch_read_input_simple_public_object_id=BatchReadInputSimplePublicObjectId(
                inputs=[CompanyObjectId(id=company_id) for company_id in company_ids], properties=["name"]
            )
        )
    except CompanyApiException:
        return set()

    names = set()
    for company in companies_response.results:
        name = company.properties.get("name")
        if name:
            names.add(name.strip().lower())
    return names
