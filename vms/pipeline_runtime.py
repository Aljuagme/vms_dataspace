from __future__ import annotations

import io
from contextlib import redirect_stdout
from typing import Any, Dict, Tuple, Set
from schema_mapping_common.utilities import split_into_segments

from schema_mapping_common.data_structures import MappingCatalog, MappingRule, get_canonical_properties
from schema_mapping_common.mapping_engine import MappingEngineConfig, propose_mappings_generic
from schema_mapping_common.scoring import SemanticEncoder
from schema_mapping_common.schema_mapping_pipeline import (
    build_opportunity_catalog,
    apply_opportunity_catalog,
)

from schema_mapping_common.skill_pipeline import normalize_skills_in_canonical_jsonld_runtime


def _catalog_from_dict(d: dict) -> MappingCatalog:
    rules = []
    for r in d.get("rules", []):
        rules.append(MappingRule(
            sources=r.get("sources") or [],
            target_key=r.get("target_key"),
            transform=r.get("transform", "identity_or_composite"),
            constant=r.get("constant"),
            slot_sources=r.get("slot_sources"),
        ))
    return MappingCatalog(
        org_id=d.get("org_id", "org"),
        entity=d.get("entity", "Opportunity"),
        rules=rules
    )


def _mapped_sources_from_catalog_dict(catalog_dict: dict) -> Set[str]:

    out: Set[str] = set()
    for r in catalog_dict.get("rules", []):
        if r.get("transform") in ("constant", "constant_if_missing"):
            continue
        for s in (r.get("sources") or []):
            s = str(s)
            out.add(s)
            if "::" in s:
                out.add(s.split("::", 1)[0])
    return out


def _merge_canonical(base: dict, partial: dict) -> dict:
    merged = dict(base)

    for k, v in (partial or {}).items():
        if k == "schema:organizer" and isinstance(merged.get(k), dict) and isinstance(v, dict):
            org = dict(merged[k])

            from schema_mapping_common.utilities import merge_contact_points  # adjust import if needed

            cp_base = org.get("schema:contactPoint")
            cp_part = v.get("schema:contactPoint")
            if isinstance(cp_part, dict):
                org["schema:contactPoint"] = merge_contact_points(
                    cp_base if isinstance(cp_base, dict) else None,
                    cp_part
                )

            for ok, ov in v.items():
                if ok == "schema:contactPoint":
                    continue
                if org.get(ok) in (None, "", [], {}):
                    org[ok] = ov

            merged[k] = org
            continue

        if k not in merged or merged.get(k) in (None, "", [], {}):
            merged[k] = v

    return merged


def run_opportunity_pipeline_missing_fields_only(
    *,
    local_payload: Dict[str, Any],
    org_name: str,
    active_catalog_dict: dict,
    normalize_skills: bool = True,
) -> Tuple[dict, dict]:


    # 1) Apply catalog to all fields (deterministic)
    base_catalog = _catalog_from_dict(active_catalog_dict)
    buf0 = io.StringIO()
    with redirect_stdout(buf0):
        base_out = apply_opportunity_catalog(local_payload, base_catalog, org_name=org_name, debug=True)
    apply_log = buf0.getvalue()

    # 2) Filter payload to only fields not mapped by catalog
    mapped_sources = _mapped_sources_from_catalog_dict(active_catalog_dict)
    missing_payload = {k: v for k, v in local_payload.items() if k not in mapped_sources}

    rejected = set(active_catalog_dict.get("rejected_sources") or [])
    if rejected:
        missing_payload = {k: v for k, v in missing_payload.items() if k not in rejected}

    schema_log = ""
    partial_out = {}

    if missing_payload:
        encoder = SemanticEncoder("sentence-transformers/all-MiniLM-L6-v2")
        cfg = MappingEngineConfig(enable_composite=True)

        buf = io.StringIO()
        with redirect_stdout(buf):
            proposals = propose_mappings_generic(
                encoder=encoder,
                entity="Opportunity",
                local_payload=missing_payload,
                candidates=get_canonical_properties("Opportunity"),
                segmenter=split_into_segments,
                cfg=cfg,
            )

            proposals_for_missing = [p for p in proposals if (p.status or "") != "REJECTED"]

            missing_catalog = build_opportunity_catalog(
                org_id=str(active_catalog_dict.get("org_id") or "org"),
                proposals=proposals_for_missing,
                org_name=org_name,
                atomic_only=False,
            )
            partial_out = apply_opportunity_catalog(missing_payload, missing_catalog, org_name=org_name, debug=True)

        schema_log = buf.getvalue()

    # 3) Merge
    final_doc = _merge_canonical(base_out, partial_out)

    # 4) Skills only if present
    skill_log = ""
    if normalize_skills:
        req = final_doc.get("vms:requiresSkill")
        has_skills = isinstance(req, list) and len(req) > 0
        if has_skills:
            sbuf = io.StringIO()
            with redirect_stdout(sbuf):
                enriched, _decisions = normalize_skills_in_canonical_jsonld_runtime(
                    final_doc,
                    enable_printing=True,
                )
            skill_log = sbuf.getvalue()
            final_doc = enriched

    return (
        {"canonical_jsonld": final_doc},
        {"schema_log": schema_log, "skill_log": skill_log, "apply_log": apply_log},
    )
