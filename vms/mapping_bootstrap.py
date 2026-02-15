from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from django.utils import timezone

from schema_mapping_common.data_structures import get_canonical_properties
from schema_mapping_common.mapping_engine import MappingEngineConfig, propose_mappings_generic
from schema_mapping_common.scoring import SemanticEncoder
from schema_mapping_common.schema_mapping_pipeline import build_opportunity_catalog
from schema_mapping_common.utilities import split_into_segments

BLOCKED_BOOTSTRAP_KEYS = {"description"}


def has_active_catalog(org, entity: str) -> bool:
    st = org.get_mapping_state(entity)
    return st.get("status") == "active" and bool(st.get("catalog"))


def _bootstrap_payload_for_catalog(sample_local_payload: dict) -> dict:

    out = dict(sample_local_payload or {})
    for k, v in list(out.items()):
        if v is None:
            continue
        s = str(v).strip()

        if 0 < len(s) < 3:
            out[k] = f"{k}: {s}"
    return out


def ensure_draft_opportunity_catalog_for_review(
    org,
    sample_local_payload: dict,
) -> Tuple[bool, Dict[str, Any]]:

    entity = "Opportunity"
    existing = org.get_mapping_state(entity)

    if existing.get("status") == "active" and existing.get("catalog"):
        return False, {"status": "active_already"}

    encoder = SemanticEncoder("sentence-transformers/all-MiniLM-L6-v2")
    cfg = MappingEngineConfig(enable_composite=False)  # IMPORTANT: disabled for bootstrap

    bootstrap_payload = _bootstrap_payload_for_catalog(sample_local_payload)

    proposals = propose_mappings_generic(
        encoder=encoder,
        entity=entity,
        local_payload=bootstrap_payload,
        candidates=get_canonical_properties(entity),
        segmenter=split_into_segments,
        cfg=cfg,
    )

    def _llm_used(p) -> bool:
        return "LLM override" in (p.note or "")

    def _llm_conf(p):
        m = re.search(r"conf=([0-9.]+)", p.note or "")
        return float(m.group(1)) if m else None

    def _topk(p, k=5):
        out = []
        ranked = (p.ranked or [])[:k]
        for cs in ranked:
            out.append({
                "key": cs.candidate.key,
                "label": cs.candidate.label,
                "sem": float(cs.semantic),
                "lex": float(cs.lexical),
                "boost": float(cs.boost),
                "comb": float(cs.combined),
            })
        return out

    rejected_sources = [p.source_path for p in proposals if (p.status or "") == "REJECTED"]

    ui_rows = []
    for p in proposals:
        blocked = p.source_path in BLOCKED_BOOTSTRAP_KEYS
        ui_decision = "COMPOSITE" if blocked else (p.status or "")

        ui_rows.append({
            "source_path": p.source_path,
            "example_value": p.example,
            "decision": ui_decision,  # real decision (or COMPOSITE override)
            "best_target": (p.best_target.key if p.best_target else None),
            "blocked": blocked,
            "skip_reason": (
                "Skipping composite for CREATION OF MAPPING CATALOG"
                if blocked else ""
            ),
            "used_llm": _llm_used(p),
            "llm_conf": _llm_conf(p),
            "note": p.note or "",
            "top_candidates": _topk(p, k=5),
        })


    proposals_for_catalog = [p for p in proposals if (p.status or "") != "REJECTED"]

    catalog = build_opportunity_catalog(
        org_id=str(org.platform_key or org.id),
        proposals=proposals_for_catalog,
        org_name=org.name,
        atomic_only=True,
        blocked_sources=list(BLOCKED_BOOTSTRAP_KEYS),
    )

    catalog_dict = catalog.to_dict()
    catalog_dict["rejected_sources"] = rejected_sources

    draft_state = {
        "status": "draft",
        "created_at": timezone.now().isoformat(),
        "catalog": catalog_dict,
        "proposals": ui_rows,
        "rejected_sources": rejected_sources,
    }
    org.set_mapping_state(entity, draft_state)
    org.save(update_fields=["mapping_catalogs_jsonld"])

    canonical_options = [cp.key for cp in get_canonical_properties(entity)]
    review_payload = {
        "entity": entity,
        "org_id": org.id,
        "org_name": org.name,
        "status": "draft_created",
        "canonical_options": canonical_options,
        "proposals": ui_rows,
        "draft_catalog": draft_state["catalog"],
        "engine_info": {
            "encoder": encoder.model_name,
            "tau": 0.30,
            "margin": 0.08,
            "k": 5,
            "llm": "Ollama/llama3.1:8b",
            "composite": "disabled",
        },
    }
    return True, review_payload


def save_opportunity_catalog_from_review(org, keep_rules: List[Dict[str, str]]) -> None:

    entity = "Opportunity"
    state = org.get_mapping_state(entity)

    if not state or not state.get("catalog"):
        raise ValueError("No draft catalog to save.")

    cat = state["catalog"]
    rules = []

    for r in cat.get("rules", []):
        if r.get("transform") in ("constant", "constant_if_missing"):
            rules.append(r)

    for rr in keep_rules:
        rules.append({
            "sources": [rr["source_path"]],
            "target_key": rr["target_key"],
            "transform": "identity_or_composite",
        })

    cat["rules"] = rules

    if "rejected_sources" not in cat:
        cat["rejected_sources"] = state.get("rejected_sources") or []

    state["catalog"] = cat
    state["status"] = "active"
    state["updated_at"] = timezone.now().isoformat()

    org.set_mapping_state(entity, state)
    org.save(update_fields=["mapping_catalogs_jsonld"])
