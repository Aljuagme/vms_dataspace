"""
schema_mapping_pipeline.py
=========================
Unified mapping pipeline for BOTH entities (Volunteer + Opportunity).

Key idea:
- Mapping engine decides: source fields -> subgroup (schema:address / vms:availability / schema:contactPoint)
- Subgroup constructors (deterministic) decide: subgroup slot filling WITHOUT re-running similarity/LLM
"""

from __future__ import annotations

import json
import hashlib
import re
from typing import Any, Dict, List, Optional

from schema_mapping_common.data_structures import (
    MappingProposal,
    MappingRule,
    MappingCatalog,
    get_canonical_properties,
)

from schema_mapping_common.utilities import (
    load_json_payload,
    split_into_segments,
    extract_time_range,
    extract_weekdays,
    TIME_RE,
    EMAIL_RE,
    # subgroup helpers
    construct_postal_address_from_sources,
    construct_availability_from_sources,
    ensure_location_obj,
    merge_list_unique,
    parse_contact_point,
    merge_contact_points, finalize_and_order_canonical,
)

from schema_mapping_common.scoring import SemanticEncoder
from schema_mapping_common.mapping_engine import propose_mappings_generic, MappingEngineConfig


# ============================================================
# Deterministic IDs
# ============================================================

def deterministic_volunteer_id(payload: Dict[str, Any]) -> str:
    mail = str(payload.get("mail") or payload.get("email") or "").strip()
    if mail and EMAIL_RE.search(mail):
        slug = hashlib.sha1(mail.encode("utf-8")).hexdigest()[:10]
        return f"https://vms.example.org/people/{slug}"
    return "https://vms.example.org/people/unknown"


def deterministic_opportunity_id(payload: Dict[str, Any], org_id: str) -> str:
    title = str(payload.get("opp_title") or payload.get("title") or payload.get("name") or "opportunity").strip()
    base = f"{org_id}:{title}".encode("utf-8")
    slug = hashlib.sha1(base).hexdigest()[:12]
    return f"https://vms.example.org/opportunities/{slug}"


# ============================================================
# Small, entity-local transforms
# ============================================================

CAPACITY_IN_TEXT_RE = re.compile(
    r"\bmax(?:imum)?\s*(\d{1,4})\b|\bmax\.\s*(\d{1,4})\b|\b(\d{1,4})\s*(?:participants|people|volunteers|attendees)\b",
    re.IGNORECASE,
)

def extract_capacity(text: str) -> Optional[int]:
    m = CAPACITY_IN_TEXT_RE.search(str(text))
    if not m:
        return None
    for g in m.groups():
        if g and g.isdigit():
            return int(g)
    return None


def normalize_skill_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    return []


def try_parse_locality_from_text(text: str) -> Optional[str]:
    m = re.search(r"\bin\s+([A-ZÄÖÜ][a-zA-ZÄÖÜäöüß\-]+)\b", str(text))
    return m.group(1) if m else None


def extract_required_skills_from_anchored_segment(segment: str) -> List[str]:
    s = str(segment).strip()
    low = s.lower()
    anchors = ["qualifications:", "requirements:", "skills:", "required:"]
    if not any(a in low for a in anchors):
        return []
    if ":" in s:
        s = s.split(":", 1)[1].strip()
    parts = re.split(r"[;,|\n]+", s)
    out: List[str] = []
    for p in parts:
        p = p.strip(" .:-").strip()
        if not p or len(p) > 80:
            continue
        out.append(p)
    seen = set()
    uniq: List[str] = []
    for x in out:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    return uniq[:10]


# ============================================================
# Catalog building (onboarding output)
# ============================================================

def _proposal_best_score(p: MappingProposal) -> float:
    if p.ranked:
        return float(p.ranked[0].combined)
    return 0.0


def build_volunteer_catalog(org_id: str, proposals: List[MappingProposal]) -> MappingCatalog:
    """
    Build mapping catalog for Volunteer.

    Key idea:
    - Aggregate all sources that mapped to schema:address into a SINGLE rule.
    - Aggregate all sources that mapped to vms:availability into a SINGLE rule.
    - For the rest, keep 1→1 mapping (pick best source if duplicates exist).
    """
    by_target: Dict[str, List[MappingProposal]] = {}
    for p in proposals:
        if p.best_target is None:
            continue
        if p.status in ("REJECTED", "COMPOSITE"):
            continue
        by_target.setdefault(p.best_target.key, []).append(p)

    rules: List[MappingRule] = []

    if "schema:address" in by_target:
        srcs = [p.source_path for p in by_target["schema:address"]]
        rules.append(MappingRule(sources=srcs, target_key="schema:address", transform="postal_from_sources"))

    if "vms:availability" in by_target:
        srcs = [p.source_path for p in by_target["vms:availability"]]
        rules.append(MappingRule(sources=srcs, target_key="vms:availability", transform="availability_from_sources"))

    for target_key, plist in by_target.items():
        if target_key in ("schema:address", "vms:availability"):
            continue
        best_p = max(plist, key=_proposal_best_score)

        transform = "identity"
        if target_key == "schema:skills":
            transform = "normalize_skill_list"

        rules.append(MappingRule(sources=[best_p.source_path], target_key=target_key, transform=transform))

    return MappingCatalog(org_id=org_id, entity="Volunteer", rules=rules)


def build_opportunity_catalog(org_id: str, proposals: List[MappingProposal], org_name: str) -> MappingCatalog:
    rules: List[MappingRule] = []

    rules.append(
        MappingRule(
            sources=[],
            target_key="schema:organizer",
            transform="constant",
            constant={"@type": "schema:Organization", "schema:name": org_name},
        )
    )
    rules.append(
        MappingRule(
            sources=[],
            target_key="vms:visibility",
            transform="constant_if_missing",
            constant="CrossPlatform",
        )
    )

    for p in proposals:
        if p.status in ("REJECTED", "COMPOSITE"):
            continue
        if p.best_target is None:
            continue
        rules.append(MappingRule(sources=[p.source_path], target_key=p.best_target.key, transform="identity_or_composite"))

    return MappingCatalog(org_id=org_id, entity="Opportunity", rules=rules)


# ============================================================
# Catalog application (runtime output)
# ============================================================

def _get_by_dotted_path(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def apply_volunteer_catalog(payload: Dict[str, Any], catalog: MappingCatalog) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "@context": {"schema": "https://schema.org/", "vms": "https://example.org/vms#", "esco": "https://data.europa.eu/esco/skill/"},
        "@type": ["schema:Person", "vms:Volunteer"],
        "@id": deterministic_volunteer_id(payload),
    }

    for rule in catalog.rules:
        tgt = rule.target_key

        if rule.transform == "identity":
            if not rule.sources:
                continue
            val = _get_by_dotted_path(payload, rule.sources[0])
            if val in (None, "", [], {}, ()):
                continue
            out[tgt] = val
            continue

        if rule.transform == "normalize_skill_list":
            if not rule.sources:
                continue
            val = _get_by_dotted_path(payload, rule.sources[0])
            out["schema:skills"] = normalize_skill_list(val)
            continue

        if rule.transform == "postal_from_sources":
            # IMPORTANT: never lose info -> fallback keeps chunks under streetAddress
            out["schema:address"] = construct_postal_address_from_sources(payload, rule.sources)
            continue

        if rule.transform == "availability_from_sources":
            out["vms:availability"] = construct_availability_from_sources(payload, rule.sources)
            continue

    # Name synthesis
    given = str(out.get("schema:givenName") or "").strip()
    family = str(out.get("schema:familyName") or "").strip()
    if given or family:
        out["schema:name"] = (given + " " + family).strip()

    # If availability still missing but we have explicit time, create it
    if "vms:availability" not in out:
        st = payload.get("availability_start_time")
        if isinstance(st, str) and TIME_RE.match(st.strip()):
            out["vms:availability"] = construct_availability_from_sources(
                payload,
                ["availability_days", "availability_start_time", "availability_end_time"],
            )

    out = finalize_and_order_canonical(out, entity="Volunteer")

    return out


def apply_opportunity_catalog(payload: Dict[str, Any], catalog: MappingCatalog, org_name: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "@context": {"schema": "https://schema.org/", "vms": "https://example.org/vms#", "esco": "https://data.europa.eu/esco/skill/"},
        "@type": ["schema:Event", "vms:Opportunity"],
        "@id": deterministic_opportunity_id(payload, catalog.org_id),
    }

    def get_source_value(source_path: str) -> Any:
        if "::seg" not in source_path:
            return _get_by_dotted_path(payload, source_path)

        base, seg = source_path.split("::", 1)
        base_val = _get_by_dotted_path(payload, base)
        if not isinstance(base_val, str):
            return None

        segments = split_into_segments(base_val)
        m = re.match(r"seg(\d+)", seg)
        if not m:
            return None
        idx = int(m.group(1)) - 1
        return segments[idx] if 0 <= idx < len(segments) else None

    for rule in catalog.rules:
        if rule.transform == "constant":
            out[rule.target_key] = rule.constant
            continue

        if rule.transform == "constant_if_missing":
            if rule.target_key not in out:
                out[rule.target_key] = rule.constant
            continue

        if rule.transform != "identity_or_composite" or not rule.sources:
            continue

        val = get_source_value(rule.sources[0])
        if val in (None, "", [], {}, ()):
            continue

        tgt = rule.target_key

        if tgt == "schema:name":
            out.setdefault("schema:name", str(val).strip())
            continue

        if tgt == "schema:description":
            existing = out.get("schema:description", "")
            chunk = str(val).strip()
            if chunk:
                out["schema:description"] = (existing + "\n" + chunk).strip() if existing else chunk
            continue

        if tgt in ("schema:startDate", "schema:endDate"):
            out.setdefault(tgt, str(val).strip())
            continue

        if tgt in ("vms:startTime", "vms:endTime"):
            if isinstance(val, str):
                s, e = extract_time_range(val)
                if s and "vms:startTime" not in out:
                    out["vms:startTime"] = s
                if e and "vms:endTime" not in out:
                    out["vms:endTime"] = e
                if not (s and e):
                    out.setdefault(tgt, val.strip())
            else:
                out.setdefault(tgt, val)
            continue

        if tgt == "schema:maximumAttendeeCapacity":
            if isinstance(val, int):
                out[tgt] = val
            elif isinstance(val, str):
                cap = extract_capacity(val)
                if cap is not None:
                    out[tgt] = cap
            continue

        if tgt == "schema:location":
            loc_obj = ensure_location_obj(out.get("schema:location"))
            if isinstance(val, str):
                locality = val.strip()
                if len(locality) > 25:
                    maybe = try_parse_locality_from_text(locality)
                    if maybe:
                        locality = maybe
                loc_obj.setdefault("schema:addressLocality", locality)
                out["schema:location"] = loc_obj
            continue

        if tgt == "vms:daysOfWeek":
            existing = out.get("vms:daysOfWeek", [])
            if not isinstance(existing, list):
                existing = []
            add: List[str] = []
            if isinstance(val, str):
                add = extract_weekdays(val)
            elif isinstance(val, (list, tuple, set)):
                add = [str(x).strip() for x in val if str(x).strip()]
            out["vms:daysOfWeek"] = merge_list_unique(existing, add)
            continue

        if tgt == "vms:requiresSkill":
            existing = out.get("vms:requiresSkill", [])
            if not isinstance(existing, list):
                existing = []
            add: List[str] = []
            if isinstance(val, (list, tuple, set)):
                add = [str(x).strip() for x in val if str(x).strip()]
            elif isinstance(val, str):
                add = extract_required_skills_from_anchored_segment(val)
                if not add:
                    # fallback: treat as a plain list-like string
                    add = normalize_skill_list(val)
            out["vms:requiresSkill"] = merge_list_unique(existing, add)
            continue

        if tgt == "schema:contactPoint":
            # IMPORTANT: do not overwrite; merge info across segments
            organizer = out.get("schema:organizer")
            if not isinstance(organizer, dict):
                organizer = {"@type": "schema:Organization", "schema:name": org_name}

            existing_cp = organizer.get("schema:contactPoint") if isinstance(organizer, dict) else None
            incoming = parse_contact_point(str(val))

            organizer["schema:contactPoint"] = merge_contact_points(existing_cp if isinstance(existing_cp, dict) else None, incoming)
            out["schema:organizer"] = organizer
            continue

        if tgt == "vms:visibility":
            if isinstance(val, str) and val.strip():
                out["vms:visibility"] = val.strip()
            continue

        out.setdefault(tgt, val)

    out.setdefault("schema:organizer", {"@type": "schema:Organization", "schema:name": org_name})
    out["schema:location"] = ensure_location_obj(out.get("schema:location"))
    out.setdefault("vms:requiresSkill", [])
    out.setdefault("vms:daysOfWeek", [])

    out = finalize_and_order_canonical(out, entity="Opportunity")
    return out


# ============================================================
# Main entry point
# ============================================================

def start_everything(
    entity: str,
    *,
    payload_path: Optional[str] = None,
    org_id: str = "org-001",
    org_name: str = "Dummy",
    width: int = 78,
) -> Dict[str, Any]:
    if entity not in ("Volunteer", "Opportunity"):
        raise ValueError(f"Entity must be 'Volunteer' or 'Opportunity', got '{entity}'")

    if payload_path is None:
        payload_path = f"payloads/{entity.lower()}.json"

    payload = load_json_payload(payload_path)

    print("\n" + "=" * width)
    print(f"LOCAL INPUT JSON ({entity})")
    print("=" * width)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("=" * width)

    encoder = SemanticEncoder("sentence-transformers/all-MiniLM-L6-v2")

    cfg = MappingEngineConfig(
        k=5,
        tau=0.30,
        margin=0.08,
        llm_min_conf_accept=0.80,
        enable_composite=(entity == "Opportunity"),
        composite_min_len=70,
        print_width=width,
    )

    candidates = get_canonical_properties(entity)

    proposals = propose_mappings_generic(
        encoder,
        entity=entity,
        local_payload=payload,
        candidates=candidates,
        cfg=cfg,
        segmenter=split_into_segments,
    )

    if entity == "Volunteer":
        catalog = build_volunteer_catalog(org_id, proposals)
        canonical = apply_volunteer_catalog(payload, catalog)
    else:
        catalog = build_opportunity_catalog(org_id, proposals, org_name)
        canonical = apply_opportunity_catalog(payload, catalog, org_name)

    print("\n" + "=" * width)
    print(f"FINAL MAPPED JSON-LD (CANONICAL {entity})")
    print("=" * width)
    print(json.dumps(canonical, indent=2, ensure_ascii=False))

    return canonical


if __name__ == "__main__":
    start_everything("Volunteer")
    # start_everything("Opportunity")
