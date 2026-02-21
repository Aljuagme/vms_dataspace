import json

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt, csrf_protect, ensure_csrf_cookie
from django.contrib import messages
from django.utils import timezone

from vms.services.decorators import volunteer_login_required
from vms.interop.services import on_local_event_created_run_pipelines

from .forms import LoginForm
from .events import annotate_event
from .mapping_bootstrap import (
    ensure_draft_opportunity_catalog_for_review,
    save_opportunity_catalog_from_review,
    has_active_catalog,
)
from .models import Organization, Volunteer, VolunteerEvent, CertificateIssue, CertificateLog

def root_redirect(request):
    vid = request.session.get("volunteer_id")
    if vid:
        return redirect("vms:dashboard", vid=vid)
    return redirect("vms:login")


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
                v = Volunteer.objects.get(name=name)
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
    volunteer_id = request.session.get("volunteer_id")
    if not volunteer_id:
        return redirect("vms:login")

    try:
        volunteer = Volunteer.objects.get(id=volunteer_id)
    except Volunteer.DoesNotExist:
        messages.error(request, "Volunteer not found.")
        return redirect("vms:login")

    dummy_ranking = [
        {"name": "Rick", "skills": "Organization, Communication", "organization": "Adelante Mujer", "hours": 120},
        {"name": "You", "skills": "First Aid, Lead a team",
         "organization": volunteer.organization.name if volunteer.organization else "Independent",
         "hours": volunteer.total_hours()},
        {"name": "Beck", "skills": "First Aid, Disaster Response", "organization": "Volgistics", "hours": 90},
        {"name": "Maria", "skills": "Teaching, Creativity", "organization": "Better Impact", "hours": 85},
        {"name": "Mark", "skills": "Cooking, Teamwork", "organization": "Mima", "hours": 60},
    ]

    dummy_ranking = sorted(dummy_ranking, key=lambda x: x["hours"], reverse=True)

    return render(request, "vms/ranking.html", {
        "volunteer": volunteer,
        "ranking": dummy_ranking,
    })


@volunteer_login_required
def dashboard_view(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    org = v.organization

    registered_ids = set(v.events.values_list("id", flat=True))

    registered_qs = v.events.select_related("organization").all()

    if not (org and org.member_ds):
        registered_qs = registered_qs.filter(organization=org)

    registered_cards = []
    for ev in registered_qs:
        card = annotate_event(ev, v, registered_ids)

        if org and org.platform_key == "demorg" and getattr(ev, "organization_id", None) == getattr(org, "id", None):
            try:
                card.tshirt_size = getattr(ev, "tshirt_size", "") or ""
            except Exception:
                pass

        registered_cards.append(card)

    registered_active = [e for e in registered_cards if not e.isFinished]
    registered_completed = [e for e in registered_cards if e.isFinished]

    org_events = list(org.events.all()) if org else []
    org_cards = []

    for ev in org_events:
        card = annotate_event(ev, v, registered_ids)

        if org and org.platform_key == "demorg":
            try:
                card.tshirt_size = getattr(ev, "tshirt_size", "") or ""
            except Exception:
                pass

        org_cards.append(card)

    unregistered_events = [e for e in org_cards if not e.is_registered and not e.isFinished]

    registered_events_count = len(registered_active)
    completed_events_count = len(registered_completed)
    hours_volunteered = sum(e.duration_hours for e in registered_completed)

    milestone_target = 100
    progress_percent = min(int((hours_volunteered / milestone_target) * 100), 100)
    remaining_percent = max(0, 100 - progress_percent)
    milestone_reached = hours_volunteered >= milestone_target

    volunteers = org.volunteers.all() if org else Volunteer.objects.none()

    return render(request, "vms/dashboard.html", {
        "volunteer": v,
        "events_registered": registered_active,
        "events_unregistered": unregistered_events,
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

    org_events = list(org.events.all()) if org else []
    registered_ids = set(v.events.values_list("id", flat=True))

    cards = []
    for ev in org_events:
        if ev.isFinished:
            continue

        card = annotate_event(ev, v, registered_ids)

        if org and org.platform_key == "demorg":
            try:
                card.tshirt_size = getattr(ev, "tshirt_size", "") or ""
            except Exception:
                pass

        cards.append(card)

    return render(request, "vms/events.html", {
        "volunteer": v,
        "events": cards,
    })



def _event_payload_from_post(post) -> dict:
    title = (post.get("title") or "").strip()
    description = (post.get("description") or "").strip()
    meeting_point = (post.get("meeting_point") or "").strip()
    duration = post.get("duration")
    max_volunteers = post.get("max_volunteers")
    tshirt_size = (post.get("tshirt_size") or "").strip()

    payload = {
        "title": title,
        "description": description,
        "meeting_point": meeting_point,
        "duration_hours": int(duration) if str(duration).strip().isdigit() else 1,
        "n_volunteers": int(max_volunteers) if str(max_volunteers).strip().isdigit() else 0,
        "tshirt_size": tshirt_size,
    }
    return payload


def _defaults_from_payload(payload: dict) -> dict:
    return {
        "name": payload.get("title", ""),
        "description": payload.get("description", ""),
        "location": payload.get("meeting_point", ""),
        "duration": payload.get("duration_hours", 1),
        "max_attendee_capacity": payload.get("n_volunteers", 0),
        "tshirt_size": payload.get("tshirt_size", ""),
    }


@volunteer_login_required
@ensure_csrf_cookie
def create_event(request):
    from .pipeline_runtime import run_opportunity_pipeline_missing_fields_only

    volunteer_id = request.session.get("volunteer_id")
    if not volunteer_id:
        return redirect("vms:login")

    volunteer = get_object_or_404(Volunteer, pk=volunteer_id)

    if not volunteer.is_manager:
        messages.error(request, "Only managers can create events.")
        return redirect("vms:dashboard", volunteer_id)

    org = volunteer.organization
    if not org:
        messages.error(request, "No organization found for this volunteer.")
        return redirect("vms:dashboard", volunteer.id)

    restored_payload = None
    if request.GET.get("restore") == "1":
        restored_payload = request.session.pop("pending_event_payload", None)

    pipeline_debug = request.session.pop("last_pipeline_debug", None)
    pipeline_result = request.session.pop("last_pipeline_result", None)

    catalog_missing = not has_active_catalog(org, "Opportunity")

    if request.method == "POST":
        payload = _event_payload_from_post(request.POST)
        request.session["pending_event_payload"] = payload  # so catalog flow can restore

        expose = request.POST.get("expose") == "on"

        if expose and catalog_missing:
            messages.error(
                request,
                "Mapping catalog not detected. Generate it first to enable Cross-Platform Visibility."
            )
            defaults = _defaults_from_payload(payload)
            return render(request, "vms/create_event.html", {
                "volunteer": volunteer,
                "defaults": defaults,
                "catalog_missing": catalog_missing,
                "pipeline_result": pipeline_result,
                "pipeline_debug": pipeline_debug,
            })

        event = VolunteerEvent.objects.create(
            name=payload["title"] or "Untitled event",
            description=payload["description"] or "",
            location=payload["meeting_point"] or "",
            duration_hours=int(payload["duration_hours"] or 1),
            max_attendee_capacity=int(payload["n_volunteers"] or 0),
            organization=org,
            isShared=expose,
            tshirt_size=payload.get("tshirt_size", ""),
            shared_since=timezone.now() if expose else None,
        )

        if not expose:
            messages.success(request, f"Event '{event.name}' created (local only).")
            return redirect("vms:create_event")

        state = org.get_mapping_state("Opportunity")
        active_catalog_dict = state.get("catalog")

        if not active_catalog_dict:
            messages.error(request, "Catalog missing unexpectedly. Generate it again.")
            return redirect("vms:create_event")

        results, debug = run_opportunity_pipeline_missing_fields_only(
            local_payload=payload,
            org_name=org.name,
            active_catalog_dict=active_catalog_dict,
            normalize_skills=True,
        )

        event.canonical_jsonld = results["canonical_jsonld"]
        event.save(update_fields=["canonical_jsonld"])

        request.session["last_pipeline_result"] = results
        request.session["last_pipeline_debug"] = debug

        messages.success(request, f"Event '{event.name}' created and canonical JSON-LD generated.")
        return redirect("vms:create_event")

    if restored_payload:
        defaults = _defaults_from_payload(restored_payload)
    else:
        next_id = (VolunteerEvent.objects.order_by("-id").first().id + 1) if VolunteerEvent.objects.exists() else 1
        defaults = {
            "name": f"Kitchen community helper",
            "description": (
                "Volunteers help prepare and distribute meals for vulnerable groups. "
                "Tasks include food preparation, cleaning, logistics support, and coordination with staff. "
                "From Monday to Friday. Requirements: basic hygiene awareness; ability to work in a team; "
                "punctuality; speak either Spanish or basic English. Contact: Ana López, volunteer coordinator. "
                "Email analopez@example.org, phone +34 612 345 678."
            ),
            "location": "Altenberger Straße 69, 4040 Linz, Austria",
            "duration": 1,
            "max_attendee_capacity": 20,
            "tshirt_size": "M",
        }

    return render(request, "vms/create_event.html", {
        "volunteer": volunteer,
        "defaults": defaults,
        "catalog_missing": catalog_missing,
        "pipeline_result": pipeline_result,
        "pipeline_debug": pipeline_debug,
    })


@require_POST
def finish_event(request, vid, eid):
    event = get_object_or_404(VolunteerEvent, pk=eid)
    event.isFinished = True
    event.save(update_fields=["isFinished"])
    messages.success(request, f"Event '{event.name}' marked as finished.")
    return redirect("vms:dashboard", vid=vid)


@volunteer_login_required
def certificate_view(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    return render(request, "vms/certificate.html", {"volunteer": v})


@volunteer_login_required
@ensure_csrf_cookie
def onboard_view(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    return render(request, "vms/onboard.html", {"volunteer": v})

@volunteer_login_required
def logs_view(request):
    return render(request, "vms/logs.html")



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
    return JsonResponse({"status": "todo"})


@volunteer_login_required
def register_event(request, vid, eid):
    v = get_object_or_404(Volunteer, pk=vid)
    event = get_object_or_404(VolunteerEvent, pk=eid)

    if request.method == "POST":
        v.events.add(event)
        messages.success(request, f"You have registered for {event.name}.")
    return redirect("vms:dashboard", vid=vid)


@volunteer_login_required
def unregister_event(request, vid, eid):
    v = get_object_or_404(Volunteer, pk=vid)
    event = get_object_or_404(VolunteerEvent, pk=eid)

    if request.method == "POST":
        v.events.remove(event)
        messages.info(request, f"You have unregistered from {event.name}.")
    return redirect("vms:dashboard", vid=vid)


def api_orgs(request):
    orgs = list(Organization.objects.values("id", "name"))
    return JsonResponse({"organizations": orgs})


def toggle_role(request, volunteer_id):
    volunteer = get_object_or_404(Volunteer, id=volunteer_id)
    volunteer.is_manager = not volunteer.is_manager
    volunteer.save(update_fields=["is_manager"])
    return redirect("vms:dashboard", vid=volunteer.id)


def switch_volunteer(request, volunteer_id):
    return redirect("vms:dashboard", vid=volunteer_id)


@require_GET
def api_certificate_context(request, vid):
   pass

@csrf_exempt
@require_POST
def api_certificate_request(request):
    pass


@require_GET
def api_certificate_logs(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    logs = CertificateLog.objects.filter(volunteer=v).order_by("created_at")
    return JsonResponse({
        "logs": [
            {
                "type": l.type,
                "message": l.message,
                "timestamp": l.created_at.isoformat(timespec="seconds"),
            }
            for l in logs
        ]
    })

@require_POST
@csrf_protect
@volunteer_login_required
def save_mapping_catalog(request):
    volunteer_id = request.session.get("volunteer_id")
    volunteer = get_object_or_404(Volunteer, pk=volunteer_id)

    if not volunteer.is_manager:
        messages.error(request, "Only managers can save mapping catalogs.")
        return redirect("vms:dashboard", vid=volunteer.id)

    org = volunteer.organization
    entity = request.POST.get("entity") or "Opportunity"
    rule_count = int(request.POST.get("rule_count") or "0")

    keep_rules = []
    for i in range(rule_count):
        src = request.POST.get(f"rule_{i}_source")
        tgt = request.POST.get(f"rule_{i}_target")
        keep = request.POST.get(f"rule_{i}_keep") == "on"

        if keep and src and tgt:
            keep_rules.append({"source_path": src, "target_key": tgt})

    save_opportunity_catalog_from_review(org, keep_rules)

    messages.success(request, "Mapping catalog saved (ACTIVE). Returning to Create Event (form restored).")
    return redirect("vms:create_event")


@require_POST
@csrf_protect
@volunteer_login_required
def generate_opportunity_catalog(request):
    volunteer_id = request.session.get("volunteer_id")
    volunteer = get_object_or_404(Volunteer, pk=volunteer_id)

    if not volunteer.is_manager:
        messages.error(request, "Only managers can generate mapping catalogs.")
        return redirect("vms:dashboard", vid=volunteer.id)

    org = volunteer.organization
    if not org:
        messages.error(request, "No organization found.")
        return redirect("vms:dashboard", vid=volunteer.id)

    payload = _event_payload_from_post(request.POST)
    request.session["pending_event_payload"] = payload  # so we can restore after saving

    created, review_payload = ensure_draft_opportunity_catalog_for_review(org, payload)
    if created:
        return render(request, "vms/mapping_catalog_review.html", review_payload)

    messages.info(request, "Mapping catalog already exists.")
    return redirect("vms:create_event")


def _canonical_get(doc: dict, key: str):
    v = doc.get(key)
    if isinstance(v, dict):
        if key in ("schema:location", "schema:address"):
            return (
                v.get("schema:name")
                or v.get("schema:streetAddress")
                or v.get("schema:addressLocality")
                or json.dumps(v, ensure_ascii=False)
            )
        if key == "schema:organizer":
            return v.get("schema:name") or json.dumps(v, ensure_ascii=False)
        if v.get("@type") == "schema:DefinedTerm":
            return v.get("schema:name") or v.get("@id")
    return v


def _reverse_map_canonical_to_local_payload(canonical_jsonld: dict, active_catalog_dict: dict) -> dict:
    rules = (active_catalog_dict or {}).get("rules", [])
    canon_to_local = {}
    used_canon_keys = set()

    for r in rules:
        if r.get("transform") in ("constant", "constant_if_missing"):
            continue
        sources = r.get("sources") or []
        if len(sources) != 1:
            continue
        local_key = sources[0]
        canon_key = r.get("target_key")
        if canon_key:
            canon_to_local[canon_key] = local_key
            used_canon_keys.add(canon_key)

    local = {
        "title": "",
        "description": "",
        "meeting_point": "",
        "duration_hours": 1,
        "n_volunteers": 0,
        "tshirt_size": "",
    }

    for canon_key, local_key in canon_to_local.items():
        val = _canonical_get(canonical_jsonld, canon_key)
        if val is None:
            continue

        if local_key in ("title",):
            local["title"] = str(val)
        elif local_key in ("description",):
            local["description"] = str(val)
        elif local_key in ("meeting_point", "location"):
            local["meeting_point"] = str(val)
        elif local_key in ("duration_hours", "duration"):
            try:
                local["duration_hours"] = int(val)
            except Exception:
                pass
        elif local_key in ("n_volunteers", "max_volunteers", "max_attendee_capacity"):
            try:
                local["n_volunteers"] = int(val)
            except Exception:
                pass
        else:
            local["description"] += f"\n{local_key}: {val}"

    def _pretty_extra(k: str, v):
        if k == "schema:organizer" and isinstance(v, dict):
            name = v.get("schema:name") or v.get("name")
            cp = v.get("schema:contactPoint") or v.get("contactPoint") or {}
            if isinstance(cp, dict):
                email = cp.get("schema:email") or cp.get("email")
                phone = cp.get("schema:telephone") or cp.get("telephone")
                contact_name = cp.get("schema:name") or cp.get("name")
            else:
                email = phone = contact_name = None

            parts = []
            if name:
                parts.append(str(name))
            if contact_name:
                parts.append(f"Contact: {contact_name}")
            if email:
                parts.append(f"Email: {email}")
            if phone:
                parts.append(f"Phone: {phone}")
            return " . ".join(parts) if parts else None

        if k in ("vms:commitment", "commitment") and isinstance(v, dict):
            days = v.get("vms:daysOfWeek") or v.get("daysOfWeek") or []
            blocks = v.get("vms:timeBlocks") or v.get("timeBlocks") or []
            if not isinstance(days, list):
                days = [days]
            if not isinstance(blocks, list):
                blocks = [blocks]
            parts = []
            if days:
                parts.append("Days: " + ", ".join([str(x) for x in days if x]))
            if blocks:
                parts.append("Time blocks: " + ", ".join([str(x) for x in blocks if x]))
            return " . ".join(parts) if parts else None

        if k in ("vms:requiresSkill", "requiresSkill"):
            labels = []
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        lbl = it.get("schema:name") or it.get("name") or it.get("label")
                        if lbl:
                            labels.append(str(lbl))
                    else:
                        labels.append(str(it))
            elif isinstance(v, dict):
                lbl = v.get("schema:name") or v.get("name") or v.get("label")
                if lbl:
                    labels.append(str(lbl))
            else:
                labels.append(str(v))
            labels = [x for x in labels if x.strip()]
            return ", ".join(labels) if labels else None

        if k in ("schema:location", "schema:address") and isinstance(v, dict):
            name = v.get("schema:name") or v.get("name")
            addr = v.get("schema:address") or v.get("address") or {}
            if isinstance(addr, dict):
                street = addr.get("schema:streetAddress") or addr.get("streetAddress")
                postal = addr.get("schema:postalCode") or addr.get("postalCode")
                city = addr.get("schema:addressLocality") or addr.get("addressLocality")
                country = addr.get("schema:addressCountry") or addr.get("addressCountry")
                parts = [p for p in [street, postal, city, country] if p]
                addr_str = ", ".join([str(p) for p in parts]) if parts else None
            else:
                addr_str = None

            if name and addr_str:
                return f"{name} ({addr_str})"
            return str(name or addr_str) if (name or addr_str) else None

        if isinstance(v, list):
            flat = []
            for it in v:
                if isinstance(it, dict):
                    flat.append(it.get("schema:name") or it.get("name") or it.get("@id") or "")
                else:
                    flat.append(str(it))
            flat = [str(x).strip() for x in flat if str(x).strip()]
            return ", ".join(flat) if flat else None

        if isinstance(v, dict):
            for key in ("schema:name", "name", "label", "schema:description", "description", "@id"):
                if key in v and v.get(key):
                    return str(v.get(key))
            return None

        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    extras = []
    for k, v in canonical_jsonld.items():
        if k in ("@context", "@type", "@id"):
            continue
        if k in used_canon_keys:
            continue

        pretty = _pretty_extra(k, v)
        if pretty:
            friendly = {
                "schema:description": "Description",
                "schema:startDate": "Start date",
                "schema:endDate": "End date",
                "schema:organizer": "Organizer",
                "vms:commitment": "Schedule",
                "vms:requiresSkill": "Skills",
            }.get(k, k)
            extras.append(f"{friendly}: {pretty}")

    if extras:
        base = local["description"].strip()
        tail = "\n".join(extras)
        local["description"] = (base + "\n\n" if base else "") + tail

    if not local["title"]:
        local["title"] = canonical_jsonld.get("schema:name") or "Federated opportunity"
    if not local["description"]:
        local["description"] = canonical_jsonld.get("schema:description") or ""

    return local


@volunteer_login_required
def federated_register_event(request, vid, provider_key: str, opportunity_id: str):

    if request.method != "POST":
        return HttpResponseBadRequest("Use POST")

    v = get_object_or_404(Volunteer, pk=vid)
    my_org = v.organization
    if not my_org:
        messages.error(request, "No organization found for this volunteer.")
        return redirect("vms:dashboard", vid=vid)

    st = my_org.get_mapping_state("Opportunity")
    active_catalog = st.get("catalog")
    if not active_catalog or st.get("status") != "active":
        messages.error(request, "Your mapping catalog is not active. Activate it first.")
        return redirect("vms:dashboard", vid=vid)

    from vms.remote_feeds import remote_opportunities_jsonld
    remote = remote_opportunities_jsonld()
    docs = remote.get(provider_key, [])

    canonical = None
    for d in docs:
        _id = str(d.get("@id") or "")
        if opportunity_id == _id:
            canonical = d
            break
        if _id.endswith("/" + str(opportunity_id)):
            canonical = d
            break

    if not canonical:
        messages.error(request, "Federated opportunity not found.")
        return redirect("vms:dashboard", vid=vid)

    local_payload = _reverse_map_canonical_to_local_payload(canonical, active_catalog)

    remote_org = get_object_or_404(Organization, platform_key=provider_key)
    remote_id = opportunity_id

    ev, created = VolunteerEvent.objects.get_or_create(
        organization=remote_org,
        is_federated_cache=True,
        source_local_id=remote_id,
        defaults=dict(
            name=local_payload.get("title") or "Federated opportunity",
            description=local_payload.get("description") or "",
            location=local_payload.get("meeting_point") or "",
            duration_hours=int(local_payload.get("duration_hours") or 1),
            max_attendee_capacity=int(local_payload.get("n_volunteers") or 0),
            isShared=True,
            isFinished=False,
            canonical_jsonld=canonical,
        ),
    )

    if not created:
        ev.name = local_payload.get("title") or ev.name
        ev.description = local_payload.get("description") or ev.description
        ev.location = local_payload.get("meeting_point") or ev.location
        try:
            ev.duration_hours = int(local_payload.get("duration_hours") or ev.duration_hours)
        except Exception:
            pass
        try:
            ev.max_attendee_capacity = int(local_payload.get("n_volunteers") or ev.max_attendee_capacity)
        except Exception:
            pass
        ev.canonical_jsonld = canonical
        ev.save()

    v.events.add(ev)
    messages.success(request, f"✅ Registered to federated opportunity: {ev.name}")
    return redirect("vms:dashboard", vid=vid)


def _cert_log(volunteer: Volunteer, typ: str, msg: str) -> None:
    try:
        CertificateLog.objects.create(volunteer=volunteer, type=typ, message=msg)
    except Exception:
        pass


ESCO_FIRST_AID_UUID = "f7464f30-662b-4177-85a0-3df9693e9e58"
ESCO_FIRST_AID_URI = f"http://data.europa.eu/esco/skill/{ESCO_FIRST_AID_UUID}"
ESCO_FIRST_AID_LABEL = "First Aid"


def _normalize_skill_phrase_to_esco(phrase: str):

    if not phrase:
        return None
    key = str(phrase).strip().lower()

    if key == "first aid":
        return {"uri": ESCO_FIRST_AID_URI, "label": ESCO_FIRST_AID_LABEL, "conf": 0.99, "method": "lexical", "raw": phrase}

    if key == "emergency care":
        return {"uri": ESCO_FIRST_AID_URI, "label": ESCO_FIRST_AID_LABEL, "conf": 0.82, "method": "semantic", "raw": phrase}

    if "first aid" in key:
        return {"uri": ESCO_FIRST_AID_URI, "label": ESCO_FIRST_AID_LABEL, "conf": 0.75, "method": "heuristic", "raw": phrase}

    if "emergency" in key and ("care" in key or "aid" in key):
        return {"uri": ESCO_FIRST_AID_URI, "label": ESCO_FIRST_AID_LABEL, "conf": 0.70, "method": "heuristic", "raw": phrase}

    return None


def _extract_required_skills_from_event(ev: VolunteerEvent) -> list[str]:

    out: list[str] = []

    if isinstance(getattr(ev, "skills", None), list):
        out.extend([str(s).strip() for s in ev.skills if str(s).strip()])

    doc = ev.canonical_jsonld or {}
    if isinstance(doc, dict):
        req = doc.get("vms:requiresSkill")
        if isinstance(req, list):
            for it in req:
                if isinstance(it, dict):
                    nm = it.get("schema:name") or it.get("name")
                    if nm:
                        out.append(str(nm).strip())
                elif isinstance(it, str) and it.strip():
                    out.append(it.strip())

    seen = set()
    uniq = []
    for s in out:
        k = s.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    return uniq


def _event_hours(ev: VolunteerEvent) -> int:

    doc = ev.canonical_jsonld or {}
    if isinstance(doc, dict) and doc.get("vms:durationHours") is not None:
        try:
            return int(doc.get("vms:durationHours"))
        except Exception:
            pass
    return int(getattr(ev, "duration_hours", 0) or 0)


def _activity_provider_label(home_org: Organization, ev: VolunteerEvent) -> str:
    if not ev.organization:
        return "Unknown"
    if home_org and ev.organization_id == home_org.id:
        return str(home_org.name)
    return ev.organization.name or (ev.organization.platform_key or "Remote")


def _is_remote_for_volunteer(home_org: Organization, ev: VolunteerEvent) -> bool:
    if not ev.organization or not home_org:
        return True
    if ev.organization_id != home_org.id:
        return True
    if getattr(ev, "is_federated_cache", False):
        return True
    return False


@require_GET
def api_certificate_context(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    home_org = v.organization

    CertificateLog.objects.filter(volunteer=v).delete()

    target = {"uri": ESCO_FIRST_AID_URI, "label": ESCO_FIRST_AID_LABEL}
    _cert_log(v, "TARGET", f"Target field: {target['label']} (ESCO={target['uri']})")

    # Thesis-like calls (represented)
    _cert_log(v, "DISCOVERY", "Discovery: find providers exposing participation/VolunteerRole evidence for certification.")
    _cert_log(v, "CONTRACT", "Connector: contract negotiation (policy+purpose) granted for certificate aggregation.")
    _cert_log(v, "CALL", "Interop: retrieve participation evidence (local DB + cached federated registrations).")

    # REAL evidence: finished registered events
    qs = v.events.select_related("organization").all()
    finished = [e for e in qs if getattr(e, "isFinished", False)]

    activities = []
    home_hours = 0
    remote_hours = 0
    contributing_total = 0

    for ev in finished:
        raw_skills = _extract_required_skills_from_event(ev)
        norm = []
        for s in raw_skills:
            mapped = _normalize_skill_phrase_to_esco(s)
            if mapped:
                norm.append(mapped)

        contributes = any(x["uri"] == target["uri"] for x in norm)
        hours = _event_hours(ev)

        provider = _activity_provider_label(home_org, ev)
        is_remote = _is_remote_for_volunteer(home_org, ev)

        if is_remote:
            remote_hours += hours
        else:
            home_hours += hours
        if contributes:
            contributing_total += hours

        if norm:
            lines = ", ".join([f'"{x["raw"]}"→{x["label"]} (conf={x["conf"]:.2f}, {x["method"]})' for x in norm])
            _cert_log(v, "NORMALIZE", f"{ev.name}: {lines}")
        else:
            _cert_log(v, "NORMALIZE", f"{ev.name}: no ESCO match for skills={raw_skills}")

        activities.append({
            "id": ev.id,
            "title": ev.name,
            "provider": provider,
            "hours": hours,
            "is_remote": bool(is_remote),
            "skills": raw_skills,
            "normalized": norm,
            "contributes": bool(contributes),
        })

    if contributing_total < 100:
        _cert_log(v, "DEMO", "Demo mode enabled: injecting evidence 70h (Demorg) + 40h (Volgistics) → 110h.")

        activities = [
            {
                "id": "DEMO-DEMORG-001",
                "title": "Light Medical Assistance",
                "provider": "Demorg",
                "hours": 70,
                "is_remote": False,
                "skills": ["Emergency Care"],
                "normalized": [
                    {"uri": ESCO_FIRST_AID_URI, "label": ESCO_FIRST_AID_LABEL, "conf": 0.82, "method": "semantic", "raw": "Emergency Care"}
                ],
                "contributes": True,
            },
            {
                "id": "DEMO-VOL-102",
                "title": "Hospital Reception Support",
                "provider": "Volgistics",
                "hours": 40,
                "is_remote": True,
                "skills": ["First Aid"],
                "normalized": [
                    {"uri": ESCO_FIRST_AID_URI, "label": ESCO_FIRST_AID_LABEL, "conf": 1.00, "method": "canonical", "raw": "First Aid"}
                ],
                "contributes": True,
            },
        ]
        home_hours = 70
        remote_hours = 40
        contributing_total = 110

    _cert_log(v, "AGGREGATE", f"Aggregate contributing hours in {target['label']}: {contributing_total}h (threshold=100h).")

    return JsonResponse({
        "volunteer_id": v.id,
        "target_skill": target,
        "total_hours_contributing": contributing_total,
        "hours_by_platform": {"home": home_hours, "remote": remote_hours},
        "activities": activities,
    })


@csrf_exempt
@require_POST
def api_certificate_request(request):
    payload = json.loads(request.body or "{}")
    vid = payload.get("volunteer_id")
    v = get_object_or_404(Volunteer, pk=vid)

    ctx = json.loads(api_certificate_context(request, vid).content.decode("utf-8"))
    total = int(ctx.get("total_hours_contributing", 0))

    if total < 100:
        _cert_log(v, "ISSUE_DENY", f"Denied: only {total}h contributing hours (need 100h).")
        return JsonResponse({"status": "denied", "reason": f"Only {total}h contributing hours."}, status=400)

    today = timezone.now().date().isoformat()
    target = ctx["target_skill"]

    cert = {
        "@context": {
            "schema": "https://schema.org/",
            "vms": "https://vms.example.org/context#",
            "esco": "http://data.europa.eu/esco/skill/",
        },
        "@type": ["schema:EducationalOccupationalCredential", "vms:VolunteerCertificate"],
        "@id": f"https://vms.example.org/certificates/{v.id}/{today}",
        "schema:name": f"{target['label']} Volunteer Service Certificate",
        "schema:dateIssued": today,
        "schema:description": (
            f"Issued for {total}h of volunteering in the field '{target['label']}', "
            "aggregated across local and federated opportunities using ESCO-based skill normalization."
        ),
        "vms:volunteer": {"@type": "schema:Person", "schema:name": v.name, "schema:identifier": str(v.id)},
        "vms:targetSkill": {"@id": target["uri"], "schema:name": target["label"]},
        "vms:totalHours": total,
        "vms:evidence": ctx.get("activities", []),
    }

    CertificateIssue.objects.create(
        volunteer=v,
        target_esco_uri=target["uri"],
        total_hours=total,
        certificate_jsonld=cert,
    )

    _cert_log(v, "ISSUE", f"Issued certificate: {target['label']} for {total}h.")
    return JsonResponse({"status": "issued", "certificate": cert})


@require_GET
def api_certificate_logs(request, vid):
    v = get_object_or_404(Volunteer, pk=vid)
    logs = CertificateLog.objects.filter(volunteer=v).order_by("created_at")
    return JsonResponse({
        "logs": [
            {
                "type": l.type,
                "message": l.message,
                "timestamp": l.created_at.isoformat(timespec="seconds"),
            }
            for l in logs
        ]
    })
