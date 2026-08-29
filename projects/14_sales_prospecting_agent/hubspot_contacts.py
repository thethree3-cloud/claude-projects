from hubspot.crm.associations.v4 import ApiException as AssociationApiException
from hubspot.crm.contacts import (
    ApiException,
    Filter,
    FilterGroup,
    PublicObjectSearchRequest,
    SimplePublicObjectInput,
    SimplePublicObjectInputForCreate,
)

from hubspot_crm import get_hubspot_client


def _split_name(full_name):
    """Best-effort first/last split -- HubSpot's built-in Contact
    properties are firstname/lastname, not a single "name" field like
    Company. A single-word name (no space) goes entirely into firstname,
    leaving lastname blank, rather than guessing."""
    parts = full_name.strip().split(" ", 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def build_contact_properties(contact):
    firstname, lastname = _split_name(contact["name"])
    properties = {"firstname": firstname, "email": contact["email"]}
    if lastname:
        properties["lastname"] = lastname
    if contact["title"]:
        properties["jobtitle"] = contact["title"]
    return properties


def find_existing_contact_id(email):
    """Searches by "email" -- HubSpot's own canonical Contact dedup key,
    unlike Company (which only has "name" to search on, a documented
    weaker substitute -- see hubspot_crm.find_existing_company_id)."""
    client = get_hubspot_client()
    request = PublicObjectSearchRequest(
        filter_groups=[FilterGroup(filters=[Filter(property_name="email", operator="EQ", value=email)])],
        limit=1,
    )
    response = client.crm.contacts.search_api.do_search(public_object_search_request=request)
    if response.total > 0:
        return response.results[0].id
    return None


def upsert_contact(contact, company_id, deal_id=None):
    """Creates or updates one Contact and associates it to the Company
    (and Deal, if given) -- but only when a real email was grounded.
    No email means no safe way to dedup a person (no fuzzy name matching,
    same "under-flag rather than risk a wrong match" precedent as
    existing_customers.is_existing_customer()), so this is skipped
    entirely rather than creating an ungrounded or duplicate-prone
    record. Returns None in that case, not an error -- "nothing to do"
    is the expected, common outcome here (see extract_contact.py)."""
    if contact.get("insufficient_information") or not contact.get("email"):
        return None

    client = get_hubspot_client()
    email = contact["email"]
    properties = build_contact_properties(contact)

    try:
        existing_id = find_existing_contact_id(email)
        if existing_id:
            client.crm.contacts.basic_api.update(
                contact_id=existing_id,
                simple_public_object_input=SimplePublicObjectInput(properties=properties),
            )
            return {"email": email, "hubspot_contact_id": existing_id, "action": "updated"}

        response = client.crm.contacts.basic_api.create(
            simple_public_object_input_for_create=SimplePublicObjectInputForCreate(properties=properties),
        )
        contact_id = response.id
        client.crm.associations.v4.basic_api.create_default(
            from_object_type="contacts", from_object_id=contact_id, to_object_type="companies", to_object_id=company_id
        )
        if deal_id:
            client.crm.associations.v4.basic_api.create_default(
                from_object_type="contacts", from_object_id=contact_id, to_object_type="deals", to_object_id=deal_id
            )
        return {"email": email, "hubspot_contact_id": contact_id, "action": "created"}
    except (ApiException, AssociationApiException) as e:
        return {"email": email, "hubspot_contact_id": None, "action": "error", "error": str(e)}
