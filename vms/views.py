from django.shortcuts import render
from django.http import JsonResponse, HttpResponseBadRequest
from .models import Organization, Volunteer, VolunteerEvent, Certificate, Skill, LogEntry
from .forms import LoginForm
import json, hashlib
from django.views.decorators.csrf import csrf_exempt

from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages

from django.db.models import Sum


from functools import wraps

def volunteer_login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if "volunteer_id" not in request.session:
            return redirect("vms:login")
        return view_func(request, *args, **kwargs)
    return wrapper

# ---------- helper: structured logging (in DB) ----------
def log_event(action, details="", level="INFO"):
    """
    Create a LogEntry; details should be a string (JSON if structured).
    Keep messages clear for presentation in defense.
    """
    entry = LogEntry.objects.create(action=action, details=details, level=level)
    return entry

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
    registered_events = v.events.all()
    unregistered_events = all_events.exclude(id__in=registered_events)

    # Mark registered status
    for event in registered_events:
        event.is_registered = True
    for event in unregistered_events:
        event.is_registered = False

    # 🔹 Add skill checks for all events
    def annotate_event(event):
        event_skills = list(event.skills.all())
        volunteer_skills = set(v.skills.all())
        skill_status = {}
        missing_skills = []

        for s in event_skills:
            if s in volunteer_skills:
                skill_status[s.label] = "has"
            else:
                skill_status[s.label] = "missing"
                missing_skills.append(s.label)

        event.skill_status = skill_status       # dict: { "First Aid": "has", "CPR": "missing" }
        event.missing_skills = missing_skills   # list of missing ones
        event.can_register = len(missing_skills) == 0  # ✅ True only if all required are met
        return event

    registered_events = [annotate_event(e) for e in registered_events]
    unregistered_events = [annotate_event(e) for e in unregistered_events]

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

    def annotate_event(event):
        # Mark if already registered
        event.is_registered = event.id in registered_ids

        # 🔹 Skill eligibility
        event_skills = list(event.skills.all())
        volunteer_skills = set(v.skills.all())
        skill_status = {}
        missing_skills = []

        for s in event_skills:
            if s in volunteer_skills:
                skill_status[s.label] = "has"
            else:
                skill_status[s.label] = "missing"
                missing_skills.append(s.label)

        event.skill_status = skill_status
        event.missing_skills = missing_skills
        event.can_register = len(missing_skills) == 0  # ✅ True if all required are met
        return event

    all_events = [annotate_event(e) for e in all_events]

    return render(request, "vms/events.html", {
        "volunteer": v,
        "events": all_events,
    })



def certificate_view(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    return render(request, "vms/certificate.html", {"volunteer": v})


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
    pass

def api_dashboard(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    activities = [
        {
            "id": a.id,
            "title": a.title,
            "hours": float(a.hours),
            "date": a.date.isoformat() if a.date else None,
            "skills": [s.label for s in a.skills.all()],
            "provider": a.provider.name if a.provider else None,
        }
        for a in v.activities.all()
    ]
    return JsonResponse({
        "profile": {"id": v.id, "name": v.name, "email": v.email},
        "total_hours": v.total_hours(),
        "activities": activities,
        "jsonld": v.to_jsonld(),  # export JSON-LD profile
    })

@csrf_exempt
def api_request_certificate(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")
    payload = json.loads(request.body)
    vid = payload.get("volunteer_id")
    items = payload.get("items", [])
    v = get_object_or_404(Volunteer, pk=vid)

    verification = []
    ok_all = True
    for it in items:
        prov_name = it.get("provider")
        ok = Organization.objects.filter(name=prov_name).exists()
        verification.append({"item": it, "ok": ok})
        if not ok:
            ok_all = False
    if not ok_all:
        return JsonResponse({"status": "pending_verification", "details": verification})

    proof = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
    cert = Certificate.objects.create(volunteer=v, items=items, proof_hash=proof)
    return JsonResponse({
        "status": "issued",
        "certificate_id": cert.id,
        "proof": proof,
        "jsonld": cert.to_jsonld(),
    })



def api_orgs(request):
    orgs = list(Organization.objects.values("id", "name"))
    return JsonResponse({"organizations": orgs})


@volunteer_login_required
def register_event(request, vid, eid):
    """Register a volunteer to an event."""
    v = get_object_or_404(Volunteer, pk=vid)
    event = get_object_or_404(VolunteerEvent, pk=eid)

    if request.method == "POST":
        v.events.add(event)
        messages.success(request, f"You have registered for {event.name}.")
    return redirect("vms:dashboard", vid=vid)


@volunteer_login_required
def unregister_event(request, vid, eid):
    """Unregister a volunteer from an event."""
    v = get_object_or_404(Volunteer, pk=vid)
    event = get_object_or_404(VolunteerEvent, pk=eid)

    if request.method == "POST":
        v.events.remove(event)
        messages.info(request, f"You have unregistered from {event.name}.")
    return redirect("vms:dashboard", vid=vid)

