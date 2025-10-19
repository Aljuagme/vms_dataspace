# vms/services/dataspace.py
import hashlib
import json

from vms.services.logging import log_event
from vms.models import Organization, VolunteerEvent, Skill

EDC_NS = "https://w3id.org/edc/v0.0.1/ns/"
ODRL_CTX = "http://www.w3.org/ns/odrl.jsonld"

def _short_id(s: str, n=12):
    return hashlib.sha1(s.encode()).hexdigest()[:n]

def _iso_duration(hours: int) -> str:
    try:
        h = int(hours) if int(hours) > 0 else 1
    except Exception:
        h = 1
    return f"PT{h}H"

def _event_skills_jsonld(event: VolunteerEvent):
    skills = []
    for s in event.skills.all():
        if s.esco_uri:
            skills.append({"@type": "schema:DefinedTerm", "@id": s.esco_uri})
        else:
            skills.append({"@type": "schema:DefinedTerm", "name": s.label})
    return skills

# --- Per-org "local ontology" → shared ontology mapping (for logs) ----
_EVENT_LOCAL_MAPPINGS = {
    "PlatformA": {  # volunteer platform
        "local_name": "title",
        "local_desc": "description",
        "local_location": "location",
        "local_duration": "duration_hours",
        "local_traits": "skills_list",
        "local_org": "org_membership",
    },
    "PlatformB": {  # event platform
        "Name": "title",
        "Details": "description",
        "Place": "location",
        "Hours": "duration_hours",
        "Traits": "skills_list",
        "worksFor": "org_membership",
    },
    "_default": {
        "name": "title",
        "description": "description",
        "location": "location",
        "duration": "duration_hours",
        "skills": "skills_list",
        "organizer": "org_membership",
    },
}

_SHARED_EVENT_MAPPING = {
    "title": "schema:name",
    "description": "schema:description",
    "location": "schema:location",
    "duration_hours": "schema:duration",
    "skills_list": "schema:skills",
    "org_membership": "schema:organizer",
    "isShared": "vms:isShared",
    "prioritize_local": "vms:priorityPolicy",
}

def build_event_jsonld(org: Organization, event: VolunteerEvent, endpoint: str, asset_id: str, contract_id: str):
    doc = {
        "@context": {
            "schema": "https://schema.org/",
            "vms": "https://vms.example.org/context",
            "esco": "https://data.europa.eu/esco/skill",
        },
        "@type": "schema:Event",
        "@id": f"https://vms.example.org/events/{event.id}",
        "schema:name": event.name,
        "schema:description": event.description or "",
        "schema:location": {"@type": "schema:Place", "schema:name": event.location} if event.location else None,
        "schema:duration": _iso_duration(event.duration_hours),
        "schema:organizer": {
            "@type": "schema:Organization",
            "@id": f"https://vms.example.org/orgs/{org.id}",
            "schema:name": org.name,
        },
        "schema:skills": _event_skills_jsonld(event),
        "vms:isShared": bool(event.isShared),
        "vms:priorityPolicy": "local-first" if event.prioritize_local else "open"
    }
    return {k: v for k, v in doc.items() if v not in (None, [], "", {})}

def map_local_event_to_shared(org: Organization, event: VolunteerEvent):
    src = _EVENT_LOCAL_MAPPINGS.get(org.name, _EVENT_LOCAL_MAPPINGS["_default"])
    sample_local = {
        src.get("title", "title"): event.name,
        src.get("description", "description"): event.description,
        src.get("location", "location"): event.location,
        src.get("duration_hours", "duration_hours"): event.duration_hours,
        src.get("skills_list", "skills_list"): [s.label for s in event.skills.all()],
        src.get("org_membership", "org_membership"): org.name,
    }
    mapping = []
    for local_key, value in sample_local.items():
        shared_key = _SHARED_EVENT_MAPPING.get(
            src.get(local_key, local_key),
            _SHARED_EVENT_MAPPING.get(local_key, "(no mapping)")
        )
        mapping.append({
            "local_field": local_key,
            "mapped_to": shared_key,
            "sample_value": value,
        })
    return mapping

def build_usage_policy(org: Organization, event: VolunteerEvent):
    policy_id = _short_id(f"policy-{org.id}-{event.id}")
    constraints = [
        {"leftOperand": "purpose", "operator": "eq", "rightOperand": "volunteer_matching"},
        {"leftOperand": "retention", "operator": "lte", "rightOperand": "P6M"},
    ]
    if event.prioritize_local:
        constraints.append({"leftOperand": "audience", "operator": "eq", "rightOperand": f"org:{org.id}"})
    duties = [
        {"action": "deleteAfter",
         "constraint": {"leftOperand": "state", "operator": "eq", "rightOperand": "event_finished"}}
    ]
    return {
        "@context": ODRL_CTX,
        "@type": "Set",
        "@id": f"urn:policy:{policy_id}",
        "permission": [{
            "target": f"urn:edc:asset:{_short_id(f'asset-{org.id}-{event.id}')}",
            "action": [{"type": "use"}, {"type": "read"}, {"type": "access"}],
            "constraint": constraints
        }],
        "duty": duties
    }

def _pretty(data):
    return json.dumps(data, indent=2, ensure_ascii=False)

# ---- Asset + Contract registration ----
def edc_register_asset_and_offer(org: Organization, event: VolunteerEvent):
    base = (org.connector_endpoint or "").rstrip("/")
    endpoint = f"{base}/api/catalog/{org.id}/events/{event.id}/"
    asset_id = _short_id(f"asset-{org.id}-{event.id}")
    offer_id = _short_id(f"offer-{org.id}-{event.id}")

    asset = {
        "@type": "edc:AssetEntryDto",
        "edc:assetId": asset_id,
        "edc:dataAddress": {
            "@type": "edc:DataAddress",
            "edc:type": "HttpData",
            "edc:baseUrl": endpoint,
            "edc:proxyMethod": True,
            "edc:proxyPath": True
        },
        "edc:properties": {
            "edc:contentType": "application/ld+json",
            "vms:eventId": str(event.id),
            "vms:organizationId": str(org.id),
        }
    }
    log_event("EDC.AssetRegistered", _pretty(asset))

    policy = build_usage_policy(org, event)
    log_event("Policy.UsageCreated", _pretty(policy))

    offer = {
        "@type": "edc:ContractOfferDescription",
        "edc:offerId": offer_id,
        "edc:assetId": asset_id,
        "edc:policy": policy
    }
    log_event("EDC.ContractOfferPublished", _pretty(offer))

    return {
        "endpoint": endpoint,
        "asset_id": asset_id,
        "contract_id": offer_id,
        "policy": policy,
    }

# ---- Federated Notifications ----
def notify_trust_anchor_and_members(org: Organization, event: VolunteerEvent, endpoint: str):
    log_event("DSGA.Notification", _pretty({
        "subject": "New event asset published",
        "organization": org.name,
        "event": event.name,
        "endpoint": endpoint
    }))
    log_event("DSGA.Acknowledged", f"DSGA validated metadata for '{event.name}' and recorded endpoint.")

    other_members = Organization.objects.filter(member_ds=True).exclude(id=org.id)
    recipients = list(other_members.values_list("name", flat=True))
    # log_event("FederatedBroadcast", _pretty({
    #     "message": "New shared event available",
    #     "from": org.name,
    #     "to_count": len(recipients),
    #     "to": recipients,
    #     "endpoint": endpoint
    # }))

# ---- Volunteer joins event scenario ----
def log_volunteer_join(volunteer, event: VolunteerEvent, from_org: Organization, to_org: Organization, contract_id: str):
    """
    Simulates PlatformA volunteer joining PlatformB event via EDC.
    Logs both the subset data exchange and the dual participation records.
    """
    # Step 1. PlatformA requests event catalog from PlatformB via EDC
    log_event("EDC.CatalogRequest", _pretty({
        "from": from_org.name,
        "to": to_org.name,
        "request": "list available events",
    }))

    # Step 2. PlatformB provides event metadata + contract offer
    log_event("EDC.CatalogResponse", _pretty({
        "from": to_org.name,
        "to": from_org.name,
        "event": {
            "EventID": event.id,
            "Name": event.name,
            "Location": event.location,
            "Time": f"{event.duration_hours}h",
        },
        "contract_offer": contract_id
    }))

    # ✅ Step 3. Contract negotiation and agreement
    log_event("EDC.ContractNegotiated", _pretty({
        "between": [from_org.name, to_org.name],
        "contract_id": contract_id,
        "purpose": "volunteer_matching",
        "data_minimization": "only VolunteerID + Name shared to host",
        "retention": "until event_finished or max 6 months",
        "note": f"Agreement reached via EDC connector. {to_org.name} cannot request full profile."
    }))

    # Step 4. Volunteer signs up — PlatformA only shares agreed subset
    parts = volunteer.name.split(" ", 1)
    if len(parts) == 2:
        display_name = f"{parts[0]} {parts[1][0]}."
    else:
        display_name = volunteer.name

    shared_subset = {
        "VolunteerID": str(volunteer.id),
        "Name": display_name,
    }
    log_event("Participation.Requested", _pretty({
        "from": from_org.name,
        "to": to_org.name,
        "contract_used": contract_id,
        "volunteer_subset": shared_subset,
        "note": "Full profile (contact, history) stays at PlatformA"
    }))

    # Step 5. Both sides record participation locally
    # Volunteer org keeps richer event context
    log_event("Participation.Recorded", _pretty({
        "system": from_org.name,
        "record": {
            "VolunteerID": volunteer.id,
            "VolunteerName": display_name,
            "EventID": event.id,
            "EventName": event.name,
            "EventLocation": event.location,
            "EventDuration": f"{event.duration_hours}h",
            "status": "joined"
        }
    }))
    # Event org keeps minimal participant info
    log_event("Participation.Recorded", _pretty({
        "system": to_org.name,
        "record": {
            "EventID": event.id,
            "ParticipantID": volunteer.id,
            "ParticipantName": display_name,
            "status": "confirmed"
        }
    }))


def log_volunteer_cancel(volunteer, event: VolunteerEvent, from_org: Organization, to_org: Organization):
    """
    Simulates a volunteer cancelling participation in a cross-org event.
    Logs withdrawal of subset data and dual record deletion.
    """
    # Step 1. PlatformA notifies PlatformB of cancellation
    parts = volunteer.name.split(" ", 1)
    if len(parts) == 2:
        display_name = f"{parts[0]} {parts[1][0]}."
    else:
        display_name = volunteer.name

    log_event("Participation.Cancelled", _pretty({
        "from": from_org.name,
        "to": to_org.name,
        "volunteer_subset": {
            "VolunteerID": str(volunteer.id),
            "Name": display_name
        },
        "note": "Only minimal subset used; full profile remains at PlatformA"
    }))

    # Step 2. Both systems update their records

    # Volunteer’s org updates its richer local record
    log_event("Participation.RecordUpdated", _pretty({
        "system": from_org.name,
        "record": {
            "VolunteerID": volunteer.id,
            "EventID": event.id,
            "EventName": event.name,
            "status": "cancelled"
        }
    }))

    # Event’s org updates only the minimal record
    log_event("Participation.RecordUpdated", _pretty({
        "system": to_org.name,
        "record": {
            "EventID": event.id,
            "ParticipantID": volunteer.id,
            "status": "cancelled"
        }
    }))

