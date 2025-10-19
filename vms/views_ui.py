import hashlib

from django.shortcuts import render
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST

from vms.services.decorators import volunteer_login_required
from .models import Organization, Volunteer, VolunteerEvent, Skill, Certificate
from .forms import LoginForm
import json
from django.views.decorators.csrf import csrf_exempt

from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages

from .events import annotate_event
from .services.logging import log_event

from django.utils import timezone
from vms.services.dataspace import (
    edc_register_asset_and_offer,
    map_local_event_to_shared,
    build_event_jsonld,
    notify_trust_anchor_and_members, log_volunteer_join, log_volunteer_cancel,
)


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
def ranking_view(request):
    volunteer_id = request.session.get('volunteer_id')

    if not volunteer_id:
        return redirect('vms:login')

    try:
        volunteer = Volunteer.objects.get(id=volunteer_id)
    except Volunteer.DoesNotExist:
        messages.error(request, "Volunteer not found.")
        return redirect('vms:login')

    # Dummy ranking list
    dummy_ranking = [
        {"name": "Rick", "skills": "Organization, Communication", "organization": "Helping Hands", "hours": 120},
        {"name": "You", "skills": "First Aid, Lead a team",
         "organization": volunteer.organization.name if volunteer.organization else "Independent",
         "hours": volunteer.total_hours()},
        {"name": "Beck", "skills": "First Aid, Disaster Response", "organization": "Red Cross", "hours": 90},
        {"name": "Maria", "skills": "Teaching, Creativity", "organization": "EduCare", "hours": 85},

        {"name": "Mark", "skills": "Cooking, Teamwork", "organization": "Food for All", "hours": 60},
    ]

    context = {
        "volunteer": volunteer,
        "ranking": dummy_ranking,
    }
    return render(request, "vms/ranking.html", context)
@volunteer_login_required
def dashboard_view(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    org = v.organization

    # --- collect events ---
    org_events = org.events.all() if org else VolunteerEvent.objects.none()

    if org and org.member_ds:
        # Add shared events from other orgs in Data Space
        ds_events = VolunteerEvent.objects.filter(
            isShared=True,
            organization__member_ds=True
        ).exclude(organization=org)
        all_events = org_events | ds_events
    else:
        all_events = org_events

    registered_ids = set(v.events.values_list("id", flat=True))

    # Annotate
    all_events = [annotate_event(e, v, registered_ids) for e in all_events]

    # Split into registered/unregistered
    registered_events = [e for e in all_events if e.is_registered]
    unregistered_events = [e for e in all_events if not e.is_registered]

    volunteers = org.volunteers.all() if org else Volunteer.objects.none()

    # Quick stats
    registered_active = [e for e in registered_events if not e.isFinished]
    registered_completed = [e for e in registered_events if e.isFinished]

    registered_events_count = len(registered_active)
    completed_events_count = len(registered_completed)
    hours_volunteered = sum(e.duration_hours for e in registered_completed)

    # Milestone logic (example: 100 hours = milestone)
    milestone_target = 100
    progress_percent = min(int((hours_volunteered / milestone_target) * 100), 100)
    remaining_percent = max(0, 100 - progress_percent)
    milestone_reached = hours_volunteered >= milestone_target

    return render(request, "vms/dashboard.html", {
        "volunteer": v,
        "events_registered": registered_active,
        "events_unregistered": [e for e in unregistered_events if not e.isFinished],
        "events_completed": registered_completed,
        "volunteers": volunteers,
        "registered_events_count": registered_events_count,
        "completed_events_count": completed_events_count,
        "hours_volunteered": hours_volunteered,
        "progress_percent": progress_percent,
        "remaining_percent": remaining_percent,
        "milestone_target": milestone_target,
        "milestone_reached": milestone_reached,

    })


@volunteer_login_required
def events_page(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    org = v.organization

    # --- collect events ---
    org_events = org.events.all() if org else VolunteerEvent.objects.none()

    if org and org.member_ds:
        ds_events = VolunteerEvent.objects.filter(
            isShared=True, organization__member_ds=True
        ).exclude(organization=org)
        # if ds_events.exists():
            # log_event("FederatedDiscovery",
            #           f"Discovered {ds_events.count()} shared events from other orgs in Data Space for {org.name}")
        all_events = org_events | ds_events
    else:
        all_events = org_events

    registered_ids = set(v.events.values_list("id", flat=True))

    # Annotate all events and filter out finished
    all_events = [annotate_event(e, v, registered_ids) for e in all_events if not e.isFinished]

    return render(request, "vms/events.html", {
        "volunteer": v,
        "events": all_events,
    })

def _pretty(data):
    return json.dumps(data, indent=2, ensure_ascii=False)

@volunteer_login_required
def create_event(request):
    volunteer_id = request.session.get("volunteer_id")
    if not volunteer_id:
        return redirect("vms:login")

    volunteer = get_object_or_404(Volunteer, pk=volunteer_id)

    if not volunteer.is_manager:
        messages.error(request, "Only managers can create events.")
        return redirect("vms:dashboard", volunteer_id)

    if request.method == "POST":
        name = request.POST.get("name")
        description = request.POST.get("description")
        location = request.POST.get("location")
        duration = request.POST.get("duration")
        skills = request.POST.get("skills", "")
        expose = request.POST.get("expose") == "on"
        prioritize = request.POST.get("prioritize") == "on"

        # Create event
        event = VolunteerEvent.objects.create(
            name=name,
            description=description or "",
            location=location or "",
            duration_hours=int(duration) if duration else 1,
            organization=volunteer.organization,
            isShared=expose,
            prioritize_local=prioritize,
            shared_since=timezone.now() if expose else None,
        )

        # Attach skills
        for s in [s.strip() for s in skills.split(",") if s.strip()]:
            skill, _ = Skill.objects.get_or_create(label=s)
            event.skills.add(skill)

        log_event("EventCreated", f"Event '{event.name}' created by {volunteer.name}")

        if expose:
            # 1) Register on connector
            edc_info = edc_register_asset_and_offer(volunteer.organization, event)
            event.ds_endpoint = edc_info["endpoint"]
            event.ds_asset_id = edc_info["asset_id"]
            event.ds_contract_id = edc_info["contract_id"]
            event.save()

            # 2) Asset + Contract published (short logs only)
            log_event("EDC.AssetRegistered", f"Asset {event.ds_asset_id} published for event '{event.name}'")
            log_event("EDC.ContractOfferPublished", f"Contract {event.ds_contract_id} offered for event '{event.name}'")

            # 3) Mapping log (short)
            mapping = map_local_event_to_shared(volunteer.organization, event)
            mapping_short = [
                {"local": m["local_field"], "mapped_to": m["mapped_to"], "sample": m["sample_value"]}
                for m in mapping
            ]
            log_event("EventSchemaMapped", json.dumps(mapping_short, indent=2))

            # 4) JSON-LD view (normalized event doc)
            jsonld = build_event_jsonld(volunteer.organization, event, event.ds_endpoint, event.ds_asset_id,
                                        event.ds_contract_id)
            log_event("EventShared.JSONLD", json.dumps(jsonld, indent=2))

            # 5) Catalog update
            # log_event("CatalogUpdated",
            #           f"{volunteer.organization.name} catalog now has {len(volunteer.organization.catalog()['events'])} events")

            # 6) Notify trust anchor + broadcast
            notify_trust_anchor_and_members(volunteer.organization, event, event.ds_endpoint)

            # 7) Policy hint if applicable
            if event.prioritize_local:
                log_event("PolicyHint", "Local-first constraint applied: volunteers from this org prioritized.")
        else:
            log_event("EventPrivate", f"Event '{event.name}' remains local-only (not published to dataspace).")

        messages.success(request, f"Event '{event.name}' created successfully!")
        return redirect("vms:dashboard", volunteer_id)

    # Defaults
    next_id = (VolunteerEvent.objects.order_by("-id").first().id + 1) if VolunteerEvent.objects.exists() else 1
    defaults = {
        "name": f"Volunteer event nº {next_id}",
        "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor.",
        "location": "Linz",
        "duration": 1,
    }
    return render(request, "vms/create_event.html", {"volunteer": volunteer, "defaults": defaults})




@require_POST
def finish_event(request, vid, eid):
    volunteer = get_object_or_404(Volunteer, pk=vid)
    if not volunteer.is_manager:
        messages.error(request, "Only managers can finish events.")
        return redirect("vms:dashboard", vid=vid)

    event = get_object_or_404(VolunteerEvent, pk=eid, organization=volunteer.organization)
    event.isFinished = True
    event.save()

    log_event("EventFinished", f"Event '{event.name}' marked as finished by {volunteer.name}")
    messages.success(request, f"Event '{event.name}' marked as finished.")
    return redirect("vms:dashboard", vid=vid)

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
    """Register a volunteer to an event and log dataspace interactions."""
    v = get_object_or_404(Volunteer, pk=vid)
    event = get_object_or_404(VolunteerEvent, pk=eid)

    if request.method == "POST":
        v.events.add(event)

        # If volunteer’s org and event org are both in dataspace → log subset contract flow
        from_org = v.organization
        to_org = event.organization
        if from_org and to_org and from_org.member_ds and to_org.member_ds and from_org != to_org:
            # use the event’s published contract id if available
            contract_id = event.ds_contract_id or "no-contract"
            log_volunteer_join(v, event, from_org, to_org, contract_id)

        messages.success(request, f"You have registered for {event.name}.")
    return redirect("vms:dashboard", vid=vid)



@volunteer_login_required
def unregister_event(request, vid, eid):
    """Unregister a volunteer from an event and log dataspace cancellation."""
    v = get_object_or_404(Volunteer, pk=vid)
    event = get_object_or_404(VolunteerEvent, pk=eid)

    if request.method == "POST":
        v.events.remove(event)

        from_org = v.organization
        to_org = event.organization
        if from_org and to_org and from_org.member_ds and to_org.member_ds and from_org != to_org:
            log_volunteer_cancel(v, event, from_org, to_org)

        messages.info(request, f"You have unregistered from {event.name}.")
    return redirect("vms:dashboard", vid=vid)

def api_orgs(request):
    orgs = list(Organization.objects.values("id", "name"))
    return JsonResponse({"organizations": orgs})


def toggle_role(request, volunteer_id):
    volunteer = get_object_or_404(Volunteer, id=volunteer_id)

    # Flip the role
    volunteer.is_manager = not volunteer.is_manager
    volunteer.save()

    # Redirect back to the same dashboard (or wherever you want)
    return redirect("vms:dashboard", vid=volunteer.id)


def switch_volunteer(request, volunteer_id):
    current = get_object_or_404(Volunteer, id=volunteer_id)

    # Example hardcoded swap
    if current.name == "Alvaro":
        new_volunteer = get_object_or_404(Volunteer, name="Andrea")
    else:
        new_volunteer = get_object_or_404(Volunteer, name="Alvaro")

    # Store the new volunteer in session
    request.session["volunteer_id"] = new_volunteer.id

    # Redirect back to the dashboard with Andrea (or Alvaro)
    return redirect("vms:dashboard", vid=new_volunteer.id)


MILESTONE_HOURS = 100

def _minimal_subset_to_reach(target, events):
    """
    Greedy: pick largest durations first until >= target.
    events: list of dicts with 'id', 'hours', ...
    returns: set of event ids selected
    """
    ordered = sorted(events, key=lambda e: int(e["hours"]), reverse=True)
    out, total = [], 0
    for e in ordered:
        if total >= target: break
        out.append(e["id"])
        total += int(e["hours"])
    return set(out), total


def api_certificate_context(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    home_org = v.organization.name if v.organization else None

    # completed activities = all registered events marked finished
    completed = v.events.filter(isFinished=True).select_related("organization").prefetch_related("skills")
    activities = []
    hours_total = 0
    hours_home = 0
    hours_remote = 0

    # build list
    for e in completed:
        hrs = int(e.duration_hours)
        hours_total += hrs
        if home_org and e.organization and e.organization.name == home_org:
            hours_home += hrs
        else:
            hours_remote += hrs
        activities.append({
            "id": str(e.id),
            "title": e.name,
            "hours": hrs,
            "provider": e.organization.name if e.organization else "Unknown",
            "skills": [s.label for s in e.skills.all()],
        })

    # choose a minimal subset that reaches 100h (if possible)
    contrib_ids, contrib_sum = _minimal_subset_to_reach(MILESTONE_HOURS, activities) if hours_total >= MILESTONE_HOURS else (set(), 0)
    for a in activities:
        a["contributes"] = a["id"] in contrib_ids

    data = {
        "total_hours": hours_total,
        "hours_by_platform": {"home": hours_home, "remote": hours_remote},
        "eligible": hours_total >= MILESTONE_HOURS,
        "contrib_sum": contrib_sum,
        "activities": activities
    }
    return JsonResponse(data)

@csrf_exempt

def api_certificate_request(request):
    """
    Issue a certificate if the volunteer has >=100h.
    Follows a data-space pattern: request → contract → cross-org attestations → issuance.
    """
    try:
        payload = json.loads(request.body)
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    vid = payload.get("volunteer_id")
    items = payload.get("items", [])
    if not vid:
        return HttpResponseBadRequest("Missing volunteer_id")

    v = get_object_or_404(Volunteer, pk=vid)
    home_org = v.organization.name if v.organization else None

    # Load selected events (proof set)
    event_ids = [int(i["id"]) for i in items]
    ev_qs = VolunteerEvent.objects.filter(id__in=event_ids).select_related("organization").prefetch_related("skills")
    if ev_qs.count() != len(event_ids):
        return HttpResponseBadRequest("Some selected activities not found")

    # recompute hours and breakdown
    total = 0
    from_home = 0
    from_remote = 0
    first_aid_skill = Skill.objects.filter(label__iexact="First Aid").first()
    first_aid_hours = 0

    cert_items = []
    for e in ev_qs:
        hrs = int(e.duration_hours)
        total += hrs
        if home_org and e.organization and e.organization.name == home_org:
            from_home += hrs
        else:
            from_remote += hrs

        # hours towards First Aid recognition
        if first_aid_skill and e.skills.filter(id=first_aid_skill.id).exists():
            first_aid_hours += hrs

        cert_items.append({
            "event_id": e.id,
            "event_name": e.name,
            "hours": hrs,
            "provider": e.organization.name if e.organization else "Unknown",
            "skills": [s.label for s in e.skills.all()],
        })

    # must meet milestone
    if total < MILESTONE_HOURS:
        return JsonResponse({"status": "rejected", "reason": f"Need {MILESTONE_HOURS}h; provided {total}h"}, status=400)

    # -------- Data space logs (story style) ----------
    # Request
    log_event("EDC.CredentialRequest", f"{v.name} (via {home_org}) requests volunteer certificate based on {len(cert_items)} activities")

    # Contract for credential issuance
    contract_id = hashlib.sha1(f"credential-{vid}-{total}".encode()).hexdigest()[:12]
    log_event("EDC.ContractNegotiated", json.dumps({
        "between": [home_org or "Unknown", "CredentialIssuer"],
        "contract_id": contract_id,
        "purpose": "credential_issuance",
        "data_minimization": "Only activity IDs, hours and provider attestations shared",
        "retention": "P36M or until revoked"
    }, indent=2))

    # Cross-org attestations (simulate one per distinct provider other than home)
    providers = sorted({ci["provider"] for ci in cert_items if ci["provider"]})
    for p in providers:
        if home_org and p == home_org:  # home org doesn't need external attestation
            continue
        log_event("EDC.AttestationRequested", f"Requesting hours attestation from {p} for {v.name}")
        log_event("EDC.AttestationReceived", f"{p} confirms contributed hours for {v.name} under contract {contract_id}")

    # -------- Persist certificate ----------
    issuer = Organization.objects.filter(is_dsga=True).first() or v.organization  # mock: DSGA or home org
    proof = hashlib.sha1(json.dumps(cert_items, sort_keys=True).encode()).hexdigest()

    cert = Certificate.objects.create(
        volunteer=v,
        issuer=issuer,
        items=cert_items,
        proof_hash=proof
    )
    # attach skills (for JSON-LD nice output)
    if first_aid_skill:
        cert.skills.add(first_aid_skill)

    # Build JSON-LD with breakdown + recognitions
    cert_jsonld = cert.to_jsonld()
    cert_jsonld["vms:hoursBreakdown"] = {
        "total": total,
        "fromHomeOrg": from_home,
        "fromOtherOrgs": from_remote
    }
    recognitions = []
    if first_aid_hours >= MILESTONE_HOURS:
        recognitions.append({
            "@type": "schema:CategoryCode",
            "schema:name": "First Aid",
            "vms:hours": first_aid_hours,
            "vms:reason": "≥100h using First Aid across volunteer events"
        })
    if recognitions:
        cert_jsonld["vms:recognitions"] = recognitions

    # Issued & distribution logs
    log_event("Credential.Issued", f"Issued Volunteer Certificate {cert.id} to {v.name} by {issuer.name if issuer else 'Unknown'}")
    log_event("EDC.CredentialDelivered", f"Certificate {cert.id} delivered to {home_org} (holder)")

    return JsonResponse({
        "status": "issued",
        "certificate": cert_jsonld,
        "contract_id": contract_id
    })
