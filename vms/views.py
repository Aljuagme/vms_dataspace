from django.shortcuts import render
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone

from vms.services.decorators import volunteer_login_required
from .models import Organization, Volunteer, VolunteerEvent, LogEntry
from .forms import LoginForm
import json, hashlib
from django.views.decorators.csrf import csrf_exempt

from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages

from .events import annotate_event
from .services.logging import log_event


# ---------------- UI Views ----------------
@volunteer_login_required
def index(request):
    return render(request, "vms/index.html")

def login_view(request):
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["name"].capitalize()
            password = form.cleaned_data["password"]
            try:
                v = Volunteer.objects.get(name=name, password=password)
                request.session["volunteer_id"] = v.id
                return redirect("vms:dashboard", vid=v.id)
            except Volunteer.DoesNotExist:
                form.add_error(None, "Invalid name or password")
    else:
        form = LoginForm()
    return render(request, "vms/login.html", {"form": form})

def logout_view(request):
    request.session.flush()
    return redirect("vms:login")


@volunteer_login_required
def dashboard_view(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    org = v.organization

    all_events = org.events.all() if org else VolunteerEvent.objects.none()
    registered_ids = set(v.events.values_list("id", flat=True))

    # Split events into registered/unregistered
    registered_events = [annotate_event(e, v, registered_ids) for e in all_events if e.id in registered_ids]
    unregistered_events = [annotate_event(e, v, registered_ids) for e in all_events if e.id not in registered_ids]

    volunteers = org.volunteers.all() if org else Volunteer.objects.none()

    # Quick stats
    registered_active = [e for e in registered_events if not e.isFinished]
    registered_completed = [e for e in registered_events if e.isFinished]

    registered_events_count = len(registered_active)
    completed_events_count = len(registered_completed)
    hours_volunteered = sum(e.duration_hours for e in registered_completed)

    return render(request, "vms/dashboard.html", {
        "volunteer": v,
        "events_registered": registered_events,
        "events_unregistered": unregistered_events,
        "volunteers": volunteers,
        # quick stats
        "registered_events_count": registered_events_count,
        "completed_events_count": completed_events_count,
        "hours_volunteered": hours_volunteered,
    })


@volunteer_login_required
def events_page(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    org = v.organization

    all_events = org.events.all() if org else VolunteerEvent.objects.none()
    registered_ids = set(v.events.values_list("id", flat=True))

    # Annotate all events
    all_events = [annotate_event(e, v, registered_ids) for e in all_events]

    return render(request, "vms/events.html", {
        "volunteer": v,
        "events": all_events,
    })


def certificate_view(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    return render(request, "vms/certificate.html", {"volunteer": v})


def onboard_view(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    return render(request, "vms/onboard.html", {"volunteer": v})


def logs_view(request):
    return render(request, "vms/logs.html")

# ---------------- API Endpoints ----------------

@csrf_exempt
def api_register_volunteer(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Use POST")
    try:
        payload = json.loads(request.body)
        v = Volunteer.objects.create(
            name=payload.get("name", ""),
            email=payload.get("email", ""),
            location=payload.get("location", ""),
        )
        return JsonResponse({"status": "ok", "volunteer_id": v.id})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)

@csrf_exempt
def api_import_history(request, vid):
    print("importing history from {}".format(vid))
    pass



@volunteer_login_required
def register_event(request, vid, eid):
    """Register a volunteer to an event."""
    v = get_object_or_404(Volunteer, pk=vid)
    event = get_object_or_404(VolunteerEvent, pk=eid)

    if request.method == "POST":
        v.events.add(event)
        messages.success(request, f"You have registered for {event.name}.")
    return redirect("vms:dashboard", vid=vid)

@csrf_exempt
def api_onboard_organization(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Use POST (JSON)")

    payload = json.loads(request.body)
    log_event("OnboardingRequestReceived", json.dumps(payload))

    # Step 1: metadata validation
    required = ["name", "contact_email", "connector_endpoint", "certificate_thumbprint", "catalog_sample"]
    missing = [f for f in required if not payload.get(f)]
    if missing:
        msg = {"status": "rejected", "reason": f"Missing fields: {missing}"}
        log_event("OnboardingRejected.MissingMetadata", json.dumps(msg), level="WARN")
        return JsonResponse(msg, status=400)
    log_event("MetadataValidation", f"All required fields present for {payload.get('name')}")

    # Step 2: governance check
    if not payload.get("privacy_policy_url"):
        log_event("GovernanceCheck", "No privacy_policy_url provided", level="WARN")
    else:
        log_event("GovernanceCheck", f"Privacy policy present: {payload['privacy_policy_url']}")

    # Step 3: volunteer schema mapping simulation
    mapping_log = []
    for local, mapped in Organization.local_volunteer_schema.items():
        mapping_log.append(f"{local} → {mapped}")
    log_event("VolunteerSchemaMapping", json.dumps(mapping_log))

    # Step 4: ontology mapping for skills
    catalog = payload.get("catalog_sample", [])
    mapped_catalog = []
    unknowns = 0
    for item in catalog:
        skills = item.get("skills", [])
        mapped_skills = []
        for s in skills:
            esco = Organization.local_skill_mapping.get(s, None)
            if esco:
                mapped_skills.append({"skill": s, "esco": esco})
            else:
                mapped_skills.append({"skill": s, "esco": "UNKNOWN"})
                unknowns += 1
        mapped_catalog.append({
            "title": item.get("title"),
            "hours": item.get("hours"),
            "mapping": mapped_skills
        })
    log_event("SkillMapping", json.dumps(mapped_catalog))

    # Step 5: contract generation
    contract = {
        "template_id": f"tmpl-{hashlib.sha1(payload['name'].encode()).hexdigest()[:8]}",
        "usage": "volunteer-activity-sharing",
        "constraints": {"purpose": "volunteer_record_verification", "retention": "36 months"}
    }
    log_event("ContractTemplateGenerated", json.dumps(contract))

    # Step 6: decision
    if unknowns > 2:
        msg = {"status": "rejected", "reason": f"Too many unknown skills ({unknowns})"}
        log_event("OnboardingRejected.OntologyGap", json.dumps(msg), level="WARN")
        return JsonResponse(msg, status=400)

    # Step 7: persist organization
    org = Organization.objects.create(
        name=payload["name"],
        contact_email=payload["contact_email"],
        connector_endpoint=payload["connector_endpoint"],
        certificate_thumbprint=payload["certificate_thumbprint"],
        metadata_json=payload,
        member_ds=True
    )
    log_event("OnboardingApproved", f"{org.name} accepted into Data Space")

    return JsonResponse({
        "status": "approved",
        "organization_id": org.id,
        "volunteer_schema": mapping_log,
        "mapped_catalog": mapped_catalog,
        "contract": contract
    })


def api_get_logs(request):
    """
    Returns recent log entries as JSON for the log panel.
    """
    limit = int(request.GET.get("limit", 50))
    logs = LogEntry.objects.all().order_by("-timestamp")[:limit]
    data = []
    for l in logs:
        data.append({
            "timestamp": l.timestamp.isoformat(),
            "level": l.level,
            "action": l.action,
            "details": l.details
        })
    return JsonResponse({"count": len(data), "entries": data})


def api_catalog(request, org_id):
    org = get_object_or_404(Organization, pk=org_id)
    events = [
        e.to_jsonld() | {"skills_needed": e.skills_needed}
        for e in org.events.all()
    ]
    return JsonResponse({"org": org.to_jsonld(), "events": events})


@volunteer_login_required
def unregister_event(request, vid, eid):
    """Unregister a volunteer from an event."""
    v = get_object_or_404(Volunteer, pk=vid)
    event = get_object_or_404(VolunteerEvent, pk=eid)

    if request.method == "POST":
        v.events.remove(event)
        messages.info(request, f"You have unregistered from {event.name}.")
    return redirect("vms:dashboard", vid=vid)

def api_orgs(request):
    orgs = list(Organization.objects.values("id", "name"))
    return JsonResponse({"organizations": orgs})