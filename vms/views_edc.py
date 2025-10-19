# vms/views_edc.py
import hashlib
import json

from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from vms.models import LogEntry, Organization, Volunteer
from vms.services.logging import log_event


@csrf_exempt
def api_onboard_organization(request):
    """
    Simulates onboarding an organization into the dataspace.
    Produces a clear, prototype-friendly sequence of logs.
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Use POST (JSON)")

    payload = json.loads(request.body)
    log_event("OnboardingRequestReceived", json.dumps(payload))

    # --- Step 1: metadata validation ---
    required = ["name", "contact_email", "connector_endpoint"]
    missing = [f for f in required if not payload.get(f)]
    if missing:
        msg = {"status": "rejected", "reason": f"Missing fields: {missing}"}
        log_event("OnboardingRejected", json.dumps(msg), level="WARN")
        return JsonResponse(msg, status=400)
    log_event("MetadataValidation", f"All required fields present for {payload.get('name')}")

    # --- Step 2: governance check ---
    if not payload.get("privacy_policy_url"):
        log_event("GovernanceCheck", "Privacy policy missing", level="WARN")
    else:
        log_event("GovernanceCheck", f"Privacy policy present: {payload['privacy_policy_url']}")

    # --- Step 3: schema mapping example ---
    sample_volunteer = {
        "name": "Alvaro Juan Gomez",
        "email_address": "alvaro@example.org",
        "hours_served": 99,
        "skills_list": ["First Aid", "Lead a Team"],
        "org_membership": "Volunet"
    }
    schema_mapping = [
        {"local_field": "name", "mapped_to": ["schema:givenName", " schema:familyName"], "sample_value": "Alvaro, Juan Gomez"},
        {"local_field": "email_address", "mapped_to": ["schema:email"], "sample_value": sample_volunteer["email_address"]},
        {"local_field": "skills_list", "mapped_to": ["schema:skills"], "sample_value": ", ".join(sample_volunteer["skills_list"])},
        {"local_field": "org_membership", "mapped_to": ["schema:memberOf"], "sample_value": sample_volunteer["org_membership"]},
        {"local_field": "days_available", "mapped_to": ["vms:availabilityPreference"], "sample_value":"Weekends"},
        {"local_field": "hours_available", "mapped_to": ["vms:availableHoursPerWeek"], "sample_value": 10},

    ]
    log_event("VolunteerSchemaMapping", json.dumps(schema_mapping, indent=2))

    # --- Step 3b: JSON-LD normalization example ---
    normalized_example = {
        "@context": {"schema": "https://schema.org/", "esco": "http://data.europa.eu/esco/skill/", "vms": "https://example.org/vms/"},
        "@type": "vms:Volunteer",
        "@id": "https://volunet.example/volunteers/123",
        "schema:givenName": "Alvaro",
        "schema:familyName": "Juan Gomez",
        "schema:email": "alvaro@example.org",
        "schema:memberOf": {"@id": "https://vms.example.org/orgs/volunet", "schema:name": "Volunet"},
        "vms:availabilityPreference": "Weekends",
        "vms:availableHoursPerWeek": {"schema:value": 10, "schema:unitText": "hours"},
        "schema:skills": [
            {"@id": "http://data.europa.eu/esco/skill/f7464f30-662b-4177-85a0-3df9693e9e58", "schema:name": "First Aid"},
            {"@id": "http://data.europa.eu/esco/skill/1f1d2ff8-c4c1-45cc-9812-6a7ee84a73cb", "schema:name": "Lead a Team"},
        ]
    }
    log_event("VolunteerSchemaNormalized", json.dumps(normalized_example, indent=2))

    # --- Step 4: ESCO enrichment log ---
    esco_log = [
        {"label": "First Aid", "uri": "http://data.europa.eu/esco/skill/f7464f30-662b-4177-85a0-3df9693e9e58"},
        {"label": "Team Leadership", "uri": "http://data.europa.eu/esco/skill/1f1d2ff8-c4c1-45cc-9812-6a7ee84a73cb"},
    ]
    log_event("ESCO_SkillMapping", json.dumps(esco_log, indent=2))

    # --- Step 5: contract template ---
    contract_id = f"tmpl-{hashlib.sha1(payload['name'].encode()).hexdigest()[:8]}"
    contract = {
        "contract_id": contract_id,
        "usage": "volunteer-activity-sharing",
        "constraints": {
            "purpose": "volunteer_record_verification",
            "retention": "36 months",
            "audience": "dataspace-members"
        }
    }
    log_event("ContractTemplateGenerated", json.dumps(contract, indent=2))

    # --- Step 5b: negotiated policies ---
    policy_contracts = {
        "dataUsage": {"allowed": ["volunteer_record_verification", "skill_matching"]},
        "retentionPolicy": {"maxDuration": "36 months", "renewable": True},
        "sharingPolicy": {"canExposeEvents": True, "mustProvidePrivacyPolicy": True}
    }
    log_event("PolicyContractsNegotiated", json.dumps(policy_contracts, indent=2))

    # ✅ New: explicit contract negotiation acceptance
    log_event("EDC.ContractNegotiated", json.dumps({
        "between": [payload["name"], "TrustAnchor"],
        "contract_id": contract_id,
        "note": f"{payload['name']} may now share events and limited volunteer info under agreed terms."
    }, indent=2))

    # --- Step 6: certificate issuance ---
    cert_thumbprint = hashlib.sha1(payload["name"].encode()).hexdigest().upper()[:32]
    log_event("CertificateIssued", cert_thumbprint)

    # --- Step 7: approve and update org ---
    volunteer_id = request.session.get("volunteer_id")
    if not volunteer_id:
        return JsonResponse({"status": "rejected", "reason": "No volunteer session found"}, status=400)

    vol = Volunteer.objects.get(pk=volunteer_id)
    org = vol.organization
    if not org:
        return JsonResponse({"status": "rejected", "reason": "Volunteer has no organization"}, status=400)

    org.contact_email = payload["contact_email"]
    org.connector_endpoint = payload["connector_endpoint"]
    org.metadata_json = payload
    org.certificate_thumbprint = cert_thumbprint
    org.member_ds = True
    org.save()

    log_event("OnboardingApproved", f"{org.name} accepted into Data Space")

    # --- Step 8: exposed endpoints ---
    base = org.connector_endpoint.rstrip("/")
    endpoints = {
        "catalog": f"{base}/api/catalog/{org.id}/",
        "events": [
            {"title": e.name, "endpoint": f"{base}/api/catalog/{org.id}/events/{e.id}/"}
            for e in org.events.all()
        ]
    }
    log_event("ExposedEndpoints", json.dumps(endpoints, indent=2))

    return JsonResponse({
        "status": "approved",
        "organization_id": org.id,
        "volunteer_schema": schema_mapping,
        "normalized_example": normalized_example,
        "contract": contract,
        "policy_contracts": policy_contracts,
        "endpoints": endpoints,
        "certificate_thumbprint": cert_thumbprint,
        "esco_skills": esco_log,
    })


def api_get_logs(request):
    """Return recent log entries as JSON."""
    limit = int(request.GET.get("limit", 50))
    logs = LogEntry.objects.all().order_by("-timestamp")[:limit]
    return JsonResponse({
        "count": len(logs),
        "entries": [
            {"timestamp": l.timestamp.isoformat(), "level": l.level, "action": l.action, "details": l.details}
            for l in logs
        ]
    })


def api_catalog(request, org_id):
    org = get_object_or_404(Organization, pk=org_id)
    base = org.connector_endpoint.rstrip("/")
    events = [{"title": e.name, "endpoint": f"{base}/api/catalog/{org.id}/events/{e.id}/"} for e in org.events.all()]
    catalog = {"org": org.to_jsonld(), "endpoints": {"catalog": f"{base}/api/catalog/{org.id}/", "events": events}}
    return JsonResponse(catalog)


def api_event_detail(request, org_id, event_id):
    org = get_object_or_404(Organization, pk=org_id)
    event = get_object_or_404(org.events, pk=event_id)
    return JsonResponse(event.to_jsonld() | {"skills_needed": event.skills_needed, "organization": org.to_jsonld()})



def toggle_dataspace(request, volunteer_id):
    volunteer = get_object_or_404(Volunteer, pk=volunteer_id)
    org = volunteer.organization
    if not org:
        return JsonResponse({"status": "error", "reason": "Volunteer has no organization"}, status=400)

    if org.member_ds:
        org.member_ds = False
        org.certificate_thumbprint = ""
        org.save()
        log_event("DataSpaceLeft", f"{org.name} left the Data Space")
        return redirect("vms:dashboard", vid=volunteer.id)
    else:
        return redirect("vms:onboard", volunteer.id)
