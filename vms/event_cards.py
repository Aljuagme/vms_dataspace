from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class EventCard:
    uid: str
    db_id: Optional[int] = None
    remote_id: Optional[str] = None
    is_remote: bool = False

    org_key: str = ""
    org_name: str = ""

    name: str = "(no name)"
    description: str = ""
    location: str = "Remote / not specified"
    duration_hours: int = 1
    image_url: str = "vms/images/event_default.jpg"

    isShared: bool = True
    isFinished: bool = False

    registered_volunteers: int = 0
    is_registered: bool = False
    can_register: bool = False
    skill_status: Dict[str, str] = field(default_factory=dict)  # label -> has/missing
    missing_skills: List[str] = field(default_factory=list)

    ds_endpoint: str = ""
    jsonld_obj: Optional[dict] = None
    tshirt_size: str = ""



def _normalize_skill_list(raw: Any) -> List[str]:

    if raw is None:
        return []

    if hasattr(raw, "all") and callable(raw.all):
        items = list(raw.all())
        out = []
        for s in items:
            label = getattr(s, "label", None) or str(s)
            label = str(label).strip()
            if label:
                out.append(label)
        return out

    if isinstance(raw, list):
        if not raw:
            return []
        if isinstance(raw[0], dict):
            out = []
            for x in raw:
                if not isinstance(x, dict):
                    continue
                label = (x.get("label") or x.get("text") or x.get("schema:name") or "").strip()
                if label:
                    out.append(label)
            return out
        return [str(x).strip() for x in raw if str(x).strip()]

    s = str(raw).strip()
    return [s] if s else []


def _skill_label_set(raw: Any) -> Set[str]:
    return {s.lower().strip() for s in _normalize_skill_list(raw) if s.strip()}


def card_from_db_event(ev) -> EventCard:
    org = ev.organization
    org_key = org.platform_key or str(org.id)

    try:
        reg_count = ev.volunteers.count()
    except Exception:
        reg_count = 0

    return EventCard(
        uid=f"db:{ev.id}",
        db_id=ev.id,
        is_remote=False,
        org_key=org_key,
        org_name=org.name,
        name=ev.name,
        description=ev.description or "",
        location=ev.location or "Remote / not specified",
        duration_hours=int(ev.duration_hours or 1),
        image_url=getattr(ev, "image_url", None) or "vms/images/event_default.jpg",
        tshirt_size=getattr(ev, "tshirt_size", "") or "",
        isShared=bool(ev.isShared),
        isFinished=bool(ev.isFinished),
        registered_volunteers=reg_count,
        ds_endpoint=getattr(ev, "ds_endpoint", "") or "",
        jsonld_obj=None,
    )


def card_from_jsonld(doc: dict, provider_key: str, provider_name: str) -> EventCard:
    name = doc.get("schema:name") or "(no name)"
    description = doc.get("schema:description") or ""

    loc = doc.get("schema:location") or {}
    location_text = None
    if isinstance(loc, dict):
        location_text = loc.get("schema:name")
        addr = loc.get("schema:address")
        if not location_text and isinstance(addr, dict):
            location_text = addr.get("schema:addressLocality") or addr.get("schema:streetAddress")
    elif isinstance(loc, str):
        location_text = loc

    skills_labels = []
    for s in (doc.get("vms:requiresSkill") or []):
        if isinstance(s, dict) and s.get("schema:name"):
            skills_labels.append(s["schema:name"])

    skill_status = {lbl: "missing" for lbl in skills_labels}

    rid = doc.get("@id", "")
    uid = f"remote:{provider_key}:{rid}" if rid else f"remote:{provider_key}:{name}"

    return EventCard(
        uid=uid,
        remote_id=rid,
        is_remote=True,
        org_key=provider_key,
        org_name=provider_name,
        name=name,
        description=description,
        location=location_text or "Remote / not specified",
        duration_hours=int(doc.get("vms:durationHours") or 1),
        image_url="vms/images/event_default.jpg",
        isShared=True,
        isFinished=False,
        registered_volunteers=0,
        is_registered=False,
        can_register=False,
        skill_status=skill_status,
        missing_skills=list(skill_status.keys()),
        jsonld_obj=doc,
    )


def annotate_card(card: EventCard, volunteer, registered_db_ids: Set[int]) -> EventCard:

    if card.is_remote or not card.db_id:
        card.is_registered = False
        card.can_register = False
        return card

    card.is_registered = bool(card.db_id and card.db_id in registered_db_ids)

    event_skill_labels = _normalize_skill_list(getattr(volunteer.events.model.objects.get(id=card.db_id), "skills", [])) \
        if card.db_id else []

    volunteer_skill_set = _skill_label_set(getattr(volunteer, "skills", None))

    skill_status = {}
    missing = []
    for label in event_skill_labels:
        if label.strip().lower() in volunteer_skill_set:
            skill_status[label] = "has"
        else:
            skill_status[label] = "missing"
            missing.append(label)

    card.skill_status = skill_status
    card.missing_skills = missing
    card.can_register = len(missing) == 0

    return card
