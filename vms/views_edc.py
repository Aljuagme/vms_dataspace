import hashlib
import json

from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt

from vms.models import Organization, Volunteer


from vms.interop.services import onboard_organization_schema_mapping


@csrf_exempt
def api_onboard_organization(request):

    if request.method != "POST":
        return HttpResponseBadRequest("Use POST (JSON)")

    payload = json.loads(request.body)

    required = ["name", "contact_email", "connector_endpoint"]
    missing = [f for f in required if not payload.get(f)]
    if missing:
        msg = {"status": "rejected", "reason": f"Missing fields: {missing}"}
        return JsonResponse(msg, status=400)

    sample_volunteer = {
        "name": "Alvaro Juan Gomez",
        "email_address": "alvaro@example.org",
        "hours_served": 99,
        "skills_list": ["First Aid", "Lead a Team"],
        "org_membership": "Mima"
    }

    schema_mapping = [
        {"local_field": "name", "mapped_to": ["schema:givenName", "schema:familyName"], "sample_value": "Alvaro, Juan Gomez"},
        {"local_field": "email_address", "mapped_to": ["schema:email"], "sample_value": sample_volunteer["email_address"]},
        {"local_field": "skills_list", "mapped_to": ["schema:skills"], "sample_value": ", ".join(sample_volunteer["skills_list"])},
        {"local_field": "org_membership", "mapped_to": ["schema:memberOf"], "sample_value": sample_volunteer["org_membership"]},
        {"local_field": "days_available", "mapped_to": ["vms:availabilityPreference"], "sample_value": "Weekends"},
        {"local_field": "hours_available", "mapped_to": ["vms:availableHoursPerWeek"], "sample_value": 11},
    ]

    normalized_example = {
        "@context": {
            "schema": "https://schema.org/",
            "esco": "http://data.europa.eu/esco/skill/",
            "vms": "https://example.org/vms/"
        },
        "@type": "vms:Volunteer",
        "@id": "https://mima.example/volunteers/123",
        "schema:givenName": "Alvaro",
        "schema:familyName": "Juan Gomez",
        "schema:email": "alvaro@example.org",
        "schema:memberOf": {
            "@id": "https://vms.example.org/orgs/mima",
            "schema:name": "Mima"
        },
        "vms:availabilityPreference": "Weekends",
        "vms:availableHoursPerWeek": {
            "schema:value": 11,
            "schema:unitText": "hours"
        },
        "schema:skills": [
            {
                "@id": "http://data.europa.eu/esco/skill/f7464f30-662b-4177-85a0-3df9693e9e58",
                "schema:name": "First Aid"
            },
            {
                "@id": "http://data.europa.eu/esco/skill/1f1d2ff8-c4c1-45cc-9812-6a7ee84a73cb",
                "schema:name": "Lead a Team"
            },
        ],
        "schema:hasOccupation": [
            {"@id": "https://vms.example.org/roles/beck-flood-relief-2025",
             "@type": "vms:VolunteerRole",
             "schema:roleName": "Field Team Leader",
             "vms:hoursPerWeek": 11,

             "schema:about": {
                 "@id": "https://vms.example.org/events/First-Aid-Force-2025",
                 "@type": "schema:Event",
                 "schema:name": "First Aid Force",
                 "schema:startDate": "2025-05-12",
                 "schema:endDate": "2025-08-15",
                 "schema:duration": "3M3D",
                 "schema:location": {
                     "@type": "schema:Place",
                     "schema:name": "Linz"
                 },
                 "schema:organizer": {
                     "@type": "schema:Organization",
                     "schema:name": "Mima"
                 },
                 "schema:maximumAttendeeCapacity": 20
             },

             "vms:requiresSkill": [
                 {"@id":
                      "https://data.europa.eu/esco/skill/f7464f30-662b-4177-85a0-3df9693e9e58",
                  "schema:name": "First Aid"}
             ]
             }
        ]
    }


    esco_log = [
        {
            "label": "First Aid",
            "uri": "http://data.europa.eu/esco/skill/f7464f30-662b-4177-85a0-3df9693e9e58"
        },
        {
            "label": "Team Leadership",
            "uri": "http://data.europa.eu/esco/skill/1f1d2ff8-c4c1-45cc-9812-6a7ee84a73cb"
        },
    ]

    contract_id = f"tmpl-{hashlib.sha1(payload['name'].encode()).hexdigest()[:8]}"

    contract = {
        "contract_id": contract_id,
        "usageScope": "volunteer-activity-sharing",
        "actions": ["view", "aggregate"],
        "target": {
            "assetType": "volunteer_events",
            "provider": payload["name"]
        },
        "constraints": {
            "purpose": ["volunteer_record_verification"],
            "retention": "36 months",
            "audience": "dataspace-members"
        },
        "obligations": [
            "must_log_access",
            "must_provide_privacy_policy"
        ]
    }

    policy_contracts = {
        "dataUsage": {
            "allowedPurposes": ["volunteer_record_verification", "skill_matching"]
        },
        "retentionPolicy": {
            "maxDuration": "36 months",
            "renewable": True
        },
        "sharingPolicy": {
            "canExposeEvents": True,
            "audience": "dataspace-members",
            "obligations": [
                "mustProvidePrivacyPolicy",
                "mustLogAccess"
            ]
        }
    }

    cert_thumbprint = hashlib.sha1(payload["name"].encode()).hexdigest().upper()[:32]

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
    onboard_organization_schema_mapping(org.id, entity_types=("OPPORTUNITY",))
    org.member_ds = True

    org.save()

    base = org.connector_endpoint.rstrip("/")
    endpoints = {
        "catalog": f"{base}/api/catalog/{org.id}/",
        "events": [
            {
                "title": e.name,
                "endpoint": f"{base}/api/catalog/{org.id}/events/{e.id}/"
            }
            for e in org.events.all()
        ]
    }

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





def api_catalog(request, org_id):
    org = get_object_or_404(Organization, pk=org_id)
    base = org.connector_endpoint.rstrip("/")
    events = [
        {
            "title": e.name,
            "endpoint": f"{base}/api/catalog/{org.id}/events/{e.id}/"
        }
        for e in org.events.all()
    ]
    catalog = {
        "org": org.to_jsonld(),
        "endpoints": {
            "catalog": f"{base}/api/catalog/{org.id}/",
            "events": events
        }
    }
    return JsonResponse(catalog)


def api_event_detail(request, org_id, event_id):
    org = get_object_or_404(Organization, pk=org_id)
    event = get_object_or_404(org.events, pk=event_id)
    return JsonResponse(event.to_jsonld() | {
        "skills_needed": event.skills_needed,
        "organization": org.to_jsonld()
    })


def toggle_dataspace(request, volunteer_id):
    volunteer = get_object_or_404(Volunteer, pk=volunteer_id)
    org = volunteer.organization
    if not org:
        return JsonResponse({"status": "error", "reason": "Volunteer has no organization"}, status=400)

    if org.member_ds:
        org.member_ds = False
        org.certificate_thumbprint = ""
        org.save()
        return redirect("vms:dashboard", vid=volunteer.id)

    else:
        return redirect("vms:onboard", volunteer.id)
