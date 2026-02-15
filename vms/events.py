
from __future__ import annotations

from typing import Any, Dict, List, Set

def _normalize_skill_list(raw: Any) -> List[Dict[str, str]]:

    if raw is None:
        return []

    if hasattr(raw, "all") and callable(raw.all):
        items = list(raw.all())
        out: List[Dict[str, str]] = []
        for s in items:
            label = getattr(s, "label", None) or str(s)
            esco = getattr(s, "esco_uri", None)
            d = {"label": str(label)}
            if esco:
                d["esco"] = str(esco)
            out.append(d)
        return out

    if isinstance(raw, list):
        if not raw:
            return []

        if isinstance(raw[0], dict):
            out: List[Dict[str, str]] = []
            for x in raw:
                if not isinstance(x, dict):
                    continue

                label = (x.get("label") or x.get("text") or "").strip()

                if not label:
                    label = (x.get("schema:name") or x.get("name") or x.get("label") or "").strip()

                if not label:
                    continue

                d = {"label": label}

                esco = x.get("esco") or x.get("@id") or x.get("id") or x.get("uri")
                if esco:
                    d["esco"] = str(esco)

                out.append(d)
            return out

        return [{"label": str(x).strip()} for x in raw if str(x).strip()]

    s = str(raw).strip()
    return [{"label": s}] if s else []


def _skill_label_set(raw: Any) -> Set[str]:
    norm = _normalize_skill_list(raw)
    return {d["label"].strip().lower() for d in norm if d.get("label")}


def _skills_from_canonical_jsonld(doc: dict) -> list[str]:
    if not isinstance(doc, dict):
        return []

    rs = doc.get("vms:requiresSkill") or doc.get("requiresSkill") or []
    if not rs:
        return []

    if not isinstance(rs, list):
        rs = [rs]

    out: List[str] = []
    for item in rs:
        if isinstance(item, dict):
            lbl = item.get("schema:name") or item.get("name") or item.get("label")
            if lbl:
                out.append(str(lbl).strip())
        else:
            s = str(item).strip()
            if s:
                out.append(s)

    seen = set()
    uniq: List[str] = []
    for s in out:
        if s not in seen:
            uniq.append(s)
            seen.add(s)
    return uniq


def annotate_event(event, volunteer, registered_ids):

    if isinstance(event, dict):
        event["is_registered"] = False
        event["registered_volunteers"] = 0
        event["can_register"] = False
        event["skill_status"] = {}
        event["missing_skills"] = []
        event["skills_labels"] = []
        event["is_federated"] = False
        return event

    event.is_registered = event.id in registered_ids

    volunteer_skills_attr = getattr(volunteer, "skills", None)
    volunteer_skill_set = _skill_label_set(volunteer_skills_attr)

    event_skill_labels: List[str] = []

    if getattr(event, "is_federated_cache", False) and isinstance(getattr(event, "canonical_jsonld", None), dict):
        canon_labels = _skills_from_canonical_jsonld(event.canonical_jsonld)
        if canon_labels:
            event_skill_labels = canon_labels

    if not event_skill_labels:
        event_skill_dicts = _normalize_skill_list(getattr(event, "skills", []))
        event_skill_labels = [d["label"] for d in event_skill_dicts if d.get("label")]

    skill_status: Dict[str, str] = {}
    missing_skills: List[str] = []

    for label in event_skill_labels:
        key = str(label)
        if key.strip().lower() in volunteer_skill_set:
            skill_status[key] = "has"
        else:
            skill_status[key] = "missing"
            missing_skills.append(key)

    event.skill_status = skill_status
    event.missing_skills = missing_skills
    event.can_register = len(missing_skills) == 0

    event.is_federated = bool(
        volunteer.organization and event.organization and event.organization != volunteer.organization
    )

    event.skills_labels = event_skill_labels

    event.tshirt_size = getattr(event, "tshirt_size", "")

    return event
