# portal/views.py

import json
import re

from django.shortcuts import render, get_object_or_404
from django.http import Http404

from vms.models import Organization, VolunteerEvent, Volunteer
from vms.remote_feeds import remote_opportunities_jsonld

from schema_mapping_common.esco_client import EscoClient
from schema_mapping_common.scoring import SemanticEncoder
from schema_mapping_common.skill_normalization import make_esco_api_retriever
from schema_mapping_common.utilities import normalize_text


_ESCO_UUID_RE = re.compile(r"/(esco/)?skill/([0-9a-fA-F-]{32,36})")


def _esco_uri_to_compact(uri: str) -> str:
    s = str(uri or "").strip()
    if not s:
        return s
    m = _ESCO_UUID_RE.search(s)
    if m:
        return f"esco:{m.group(2)}"
    return s


def _extract_skill_terms_from_doc(doc: dict) -> tuple[set[str], set[str]]:

    labels: set[str] = set()
    ids: set[str] = set()

    rs = doc.get("vms:requiresSkill") or doc.get("requiresSkill") or []
    if not isinstance(rs, list):
        rs = [rs]

    for item in rs:
        if isinstance(item, dict):
            lbl = item.get("schema:name") or item.get("name") or item.get("label")
            if isinstance(lbl, str) and lbl.strip():
                labels.add(normalize_text(lbl, keep_colon=False))
            _id = item.get("@id") or item.get("id") or item.get("uri")
            if isinstance(_id, str) and _id.strip():
                ids.add(_id.strip())
                ids.add(_esco_uri_to_compact(_id.strip()))
        else:
            s = str(item).strip()
            if s:
                labels.add(normalize_text(s, keep_colon=False))

    return labels, ids


def _topk_esco_candidates_for_query(query: str, *, k: int = 5, lang: str = "en") -> list[dict]:

    q = (query or "").strip()
    if not q:
        return []

    encoder = SemanticEncoder("sentence-transformers/all-MiniLM-L6-v2")
    esco = EscoClient(selected_version="v1.2.0")
    retriever = make_esco_api_retriever(esco, encoder, lang=lang)

    ranked = retriever(q, k)
    out: list[dict] = []
    for sc in ranked[:k]:
        out.append({
            "uri": sc.uri,
            "uri_compact": _esco_uri_to_compact(sc.uri),
            "label": sc.label,
            "combined": float(sc.combined),
        })
    return out


def _jsonld_to_card(doc: dict) -> dict:

    def _get(d, *keys):
        for k in keys:
            if isinstance(d, dict) and k in d and d.get(k) not in (None, "", [], {}):
                return d.get(k)
        return None

    name = _get(doc, "schema:name", "name") or "(no name)"
    description = _get(doc, "schema:description", "description") or ""

    # Dates
    start_date = _get(doc, "schema:startDate", "startDate")
    end_date = _get(doc, "schema:endDate", "endDate")

    # Location
    loc = _get(doc, "schema:location", "location") or {}
    location_text = None
    address_text = None
    if isinstance(loc, dict):
        location_text = _get(loc, "schema:name", "name")
        addr = _get(loc, "schema:address", "address")
        if isinstance(addr, dict):
            street = _get(addr, "schema:streetAddress", "streetAddress")
            city = _get(addr, "schema:addressLocality", "addressLocality")
            postal = _get(addr, "schema:postalCode", "postalCode")
            country = _get(addr, "schema:addressCountry", "addressCountry")
            parts = [p for p in [street, postal, city, country] if p]
            if parts:
                address_text = ", ".join(parts)

        if not location_text and address_text:
            location_text = address_text

    elif isinstance(loc, str):
        location_text = loc

    # Organizer + contact point
    organizer = _get(doc, "schema:organizer", "organizer") or {}
    organizer_name = _get(organizer, "schema:name", "name")
    contact = _get(organizer, "schema:contactPoint", "contactPoint") or {}
    contact_name = _get(contact, "schema:name", "name")
    contact_email = _get(contact, "schema:email", "email")
    contact_phone = _get(contact, "schema:telephone", "telephone")

    # Capacity
    max_cap = _get(doc, "schema:maximumAttendeeCapacity", "maximumAttendeeCapacity")

    # Commitment
    commitment = _get(doc, "vms:commitment", "commitment") or {}
    time_blocks = _get(commitment, "vms:timeBlocks", "timeBlocks") or []
    days_of_week = _get(commitment, "vms:daysOfWeek", "daysOfWeek") or []
    if len(days_of_week) == 0:
        days_of_week = _get(doc, "vms:daysOfWeek", "daysOfWeek") or []

    # Duration
    duration = _get(doc, "vms:durationHours", "durationHours") or 1

    # Skills
    skills_labels = []
    skills = _get(doc, "vms:requiresSkill", "requiresSkill") or []
    if isinstance(skills, list):
        for s in skills:
            if isinstance(s, dict):
                label = _get(s, "schema:name", "name", "label")
                if label:
                    skills_labels.append(label)
            else:
                skills_labels.append(str(s))

    jsonld_str = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))

    return {
        "id": doc.get("@id", ""),
        "name": name,
        "description": description,
        "start_date": start_date,
        "end_date": end_date,
        "location": location_text or "Remote / not specified",
        "address_text": address_text,
        "duration_hours": duration,
        "max_capacity": max_cap,
        "organizer_name": organizer_name,
        "contact_name": contact_name,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "time_blocks": time_blocks if isinstance(time_blocks, list) else [time_blocks],
        "days_of_week": days_of_week if isinstance(days_of_week, list) else [days_of_week],
        "skills_labels": skills_labels,
        "jsonld_obj": doc,
        "jsonld_str": jsonld_str,
    }


def portal_directory(request):
    providers = Organization.objects.filter(member_ds=True).order_by("platform_key")
    remote = remote_opportunities_jsonld()


    volunteer = None
    my_org_key = None
    vid = request.session.get("volunteer_id")
    if vid:
        try:
            volunteer = Volunteer.objects.select_related("organization").get(id=vid)
            my_org_key = volunteer.organization.platform_key if volunteer.organization else None
        except Volunteer.DoesNotExist:
            volunteer = None
            my_org_key = None

    skill_query = (request.GET.get("skill") or "").strip()
    skill_candidates = _topk_esco_candidates_for_query(skill_query, k=20, lang="en") if skill_query else []

    cand_label_keys = {normalize_text(c["label"], keep_colon=False) for c in skill_candidates}
    cand_id_keys = {c["uri"] for c in skill_candidates} | {c["uri_compact"] for c in skill_candidates}

    rows = []
    matched_total = 0

    for org in providers:
        pk = org.platform_key or ""
        docs = []

        if pk in ("mima", "volgistics"):
            docs = remote.get(pk, [])

        elif pk == "demorg":
            qs = VolunteerEvent.objects.filter(
                organization=org,
                isShared=True,
                isFinished=False
            ).order_by("id")

            for ev in qs:
                doc = (
                    ev.canonical_jsonld
                    if isinstance(ev.canonical_jsonld, dict) and ev.canonical_jsonld
                    else ev.to_jsonld_stub()
                )
                doc["_db_id"] = ev.id
                docs.append(doc)

        if skill_query and skill_candidates:
            filtered = []
            for d in docs:
                doc_labels, doc_ids = _extract_skill_terms_from_doc(d)
                if doc_ids.intersection(cand_id_keys) or doc_labels.intersection(cand_label_keys):
                    filtered.append(d)
            docs = filtered

        cards = []
        for d in docs:
            c = _jsonld_to_card(d)
            if "_db_id" in d:
                c["db_id"] = d["_db_id"]
            cards.append(c)

        matched_total += len(cards)
        rows.append((org, cards))

    return render(request, "portal/directory.html", {
        "providers": providers,
        "rows": rows,
        "skill_query": skill_query,
        "skill_candidates": skill_candidates,
        "matched_total": matched_total,

        "volunteer": volunteer,
        "my_org_key": my_org_key,
    })


def provider_detail(request, platform_key: str):
    provider = get_object_or_404(Organization, platform_key=platform_key)
    provider_jsonld = provider.get_self_description_doc()
    return render(request, "portal/provider_detail.html", {
        "provider": provider,
        "provider_jsonld": provider_jsonld,
    })


def opportunity_detail(request, provider_key: str, opportunity_id: str):
    """
    Show the JSON-LD of a federated opportunity (remote or local)
    """
    provider = get_object_or_404(Organization, platform_key=provider_key)
    doc = None

    if provider_key in ("mima", "volgistics"):
        remote = remote_opportunities_jsonld()
        for d in remote.get(provider_key, []):
            if d.get("@id") == opportunity_id:
                doc = d
                break

    elif provider_key == "demorg":
        qs = VolunteerEvent.objects.filter(
            organization=provider,
            isShared=True,
            isFinished=False
        ).order_by("id")

        for ev in qs:
            d = (
                ev.canonical_jsonld
                if isinstance(ev.canonical_jsonld, dict) and ev.canonical_jsonld
                else ev.to_jsonld_stub()
            )
            if d.get("@id") == opportunity_id:
                doc = d
                break

    if not doc:
        raise Http404("Opportunity not found")

    return render(request, "portal/opportunity_detail.html", {
        "provider": provider,
        "opportunity_id": opportunity_id,
        "opportunity_jsonld": doc,
    })
