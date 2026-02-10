# vms/interop/services.py
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from django.conf import settings
from django.db import transaction

from vms.models import (
    Organization,
    LocalResource,
    CanonicalResource,
    VolunteerEvent,
)

# IMPORTANT:
# Your pipeline code currently imports "schema_mapping_common.*".
# That package MUST exist in your project (see changes section below).
from schema_mapping_common.scoring import SemanticEncoder
from schema_mapping_common.data_structures import MappingCatalog, MappingRule, get_canonical_properties
from schema_mapping_common.mapping_engine import propose_mappings_generic, MappingEngineConfig
from schema_mapping_common.utilities import split_into_segments

from schema_mapping_common.schema_mapping_pipeline import (
    build_opportunity_catalog,
    build_volunteer_catalog,
    apply_opportunity_catalog,
    apply_volunteer_catalog,
)

from schema_mapping_common.esco_client import EscoClient
from schema_mapping_common.skill_normalization import (
    make_esco_api_retriever,
    normalize_skills_in_canonical_jsonld,
    SkillEngineConfig,
)

# ---------------------------------------------------------------------
# Singletons (loaded once per process)
# ---------------------------------------------------------------------

_ENCODER: Optional[SemanticEncoder] = None
_ESCO: Optional[EscoClient] = None
_SKILL_RETRIEVER = None


def _get_encoder() -> SemanticEncoder:
    global _ENCODER
    if _ENCODER is None:
        model_name = getattr(settings, "INTEROP_ENCODER_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        _ENCODER = SemanticEncoder(model_name)
    return _ENCODER


def _get_esco() -> EscoClient:
    global _ESCO
    if _ESCO is None:
        # If you want version pinning, set INTEROP_ESCO_VERSION = "v1.2.0"
        _ESCO = EscoClient(selected_version=getattr(settings, "INTEROP_ESCO_VERSION", None))
    return _ESCO


def _get_skill_retriever(lang: str = "en"):
    global _SKILL_RETRIEVER
    if _SKILL_RETRIEVER is None:
        encoder = _get_encoder()
        esco = _get_esco()
        _SKILL_RETRIEVER = make_esco_api_retriever(esco, encoder, lang=lang)
    return _SKILL_RETRIEVER


# ---------------------------------------------------------------------
# Config builders (NO mutation of frozen dataclasses)
# ---------------------------------------------------------------------

def _mapping_cfg(entity: str) -> MappingEngineConfig:
    """
    Build MappingEngineConfig from Django settings (without mutating frozen dataclass).
    """
    base = MappingEngineConfig()

    # Allow per-entity overrides if you want later; for now keep it simple.
    k = getattr(settings, "INTEROP_MAPPING_K", base.k)
    tau = getattr(settings, "INTEROP_MAPPING_TAU", base.tau)
    margin = getattr(settings, "INTEROP_MAPPING_MARGIN", base.margin)
    llm_min = getattr(settings, "INTEROP_MAPPING_LLM_MIN_CONF", base.llm_min_conf_accept)
    width = getattr(settings, "INTEROP_PRINT_WIDTH", base.print_width)

    enable_composite = bool(getattr(settings, "INTEROP_ENABLE_COMPOSITE", entity == "Opportunity"))
    composite_min_len = getattr(settings, "INTEROP_COMPOSITE_MIN_LEN", base.composite_min_len)

    return MappingEngineConfig(
        k=int(k),
        tau=float(tau),
        margin=float(margin),
        llm_min_conf_accept=float(llm_min),
        enable_composite=bool(enable_composite),
        composite_min_len=int(composite_min_len),
        print_width=int(width),
    )


def _skill_cfg() -> SkillEngineConfig:
    base = SkillEngineConfig()
    return SkillEngineConfig(
        k=int(getattr(settings, "INTEROP_SKILL_K", base.k)),
        tau=float(getattr(settings, "INTEROP_SKILL_TAU", base.tau)),
        margin=float(getattr(settings, "INTEROP_SKILL_MARGIN", base.margin)),
        llm_min_conf_accept=float(getattr(settings, "INTEROP_SKILL_LLM_MIN_CONF", base.llm_min_conf_accept)),
        print_width=int(getattr(settings, "INTEROP_PRINT_WIDTH", base.print_width)),
        max_print_rows=int(getattr(settings, "INTEROP_SKILL_MAX_PRINT_ROWS", base.max_print_rows)),
        enable_printing=bool(getattr(settings, "INTEROP_SKILL_PRINTING", base.enable_printing)),
    )


# ---------------------------------------------------------------------
# Catalog persistence helpers (stored in Organization.metadata_json)
# ---------------------------------------------------------------------

def _catalog_key(entity: str) -> str:
    # entity is "Volunteer" or "Opportunity"
    return f"mapping_catalog::{entity}"


def _save_catalog(org: Organization, catalog: MappingCatalog) -> None:
    meta = dict(org.metadata_json or {})
    meta[_catalog_key(catalog.entity)] = catalog.to_dict()
    org.metadata_json = meta
    org.save(update_fields=["metadata_json"])


def _load_catalog(org: Organization, entity: str) -> Optional[MappingCatalog]:
    meta = org.metadata_json or {}
    raw = meta.get(_catalog_key(entity))
    if not raw:
        return None

    # Rebuild MappingCatalog + MappingRule objects
    rules = []
    for r in raw.get("rules", []):
        rules.append(
            MappingRule(
                sources=list(r.get("sources") or []),
                target_key=str(r.get("target_key")),
                transform=str(r.get("transform") or "identity"),
                constant=r.get("constant", None),
                slot_sources=r.get("slot_sources", None),
            )
        )
    return MappingCatalog(org_id=str(raw.get("org_id")), entity=str(raw.get("entity")), rules=rules)


# ---------------------------------------------------------------------
# JOIN NETWORK: Schema pipeline runs (build catalogs)
# ---------------------------------------------------------------------

@transaction.atomic
def onboard_organization_schema_mapping(org_id: int, *, entity_types: Iterable[str] = ("OPPORTUNITY",)) -> Dict[str, Any]:
    """
    Called when an org joins the federation.

    - Uses LocalResource samples to propose mappings (retrieve/verify)
    - Builds MappingCatalog
    - Persists into Organization.metadata_json
    """
    org = Organization.objects.select_for_update().get(id=org_id)

    encoder = _get_encoder()
    out: Dict[str, Any] = {"org_id": org_id, "built": []}

    # Map app entity types -> pipeline entities
    for et in entity_types:
        if et not in ("OPPORTUNITY", "VOLUNTEER"):
            continue

        pipeline_entity = "Opportunity" if et == "OPPORTUNITY" else "Volunteer"

        sample = (
            LocalResource.objects.filter(organization=org, entity_type=et)
            .order_by("-retrieved_at")
            .first()
        )
        if not sample:
            out["built"].append({"entity": pipeline_entity, "status": "skipped", "reason": f"no LocalResource({et})"})
            continue

        local_payload = sample.payload
        candidates = get_canonical_properties(pipeline_entity)
        cfg = _mapping_cfg(pipeline_entity)

        proposals = propose_mappings_generic(
            encoder,
            entity=pipeline_entity,
            local_payload=local_payload,
            candidates=candidates,
            cfg=cfg,
            segmenter=split_into_segments,
        )

        if pipeline_entity == "Opportunity":
            catalog = build_opportunity_catalog(str(org.platform_key or org.id), proposals, org_name=org.name)
        else:
            catalog = build_volunteer_catalog(str(org.platform_key or org.id), proposals)

        _save_catalog(org, catalog)

        out["built"].append(
            {
                "entity": pipeline_entity,
                "status": "ok",
                "catalog_rules": len(catalog.rules),
                "sample_local_resource_id": sample.id,
            }
        )

    return out


# ---------------------------------------------------------------------
# CREATE EVENT: schema + skill pipelines run
# ---------------------------------------------------------------------

@transaction.atomic
def on_local_event_created_run_pipelines(event_id: int, *, normalize_skills: bool = True) -> Dict[str, Any]:
    """
    Called when a local VolunteerEvent is created and exposed.

    What it does:
    1) Ensures there is a LocalResource(OPPORTUNITY) for this event (local schema snapshot)
    2) Applies existing catalog (or builds one if missing) -> CanonicalResource
    3) Optionally skill-normalizes the canonical JSON-LD (ESCO)
    """
    event = VolunteerEvent.objects.select_for_update().select_related("organization").get(id=event_id)
    org = event.organization
    if not org:
        return {"status": "error", "reason": "event has no organization"}

    # 1) create/update a LocalResource snapshot for this local event
    # NOTE: This is DemOrg's LOCAL schema snapshot. Keep it consistent and DO NOT invent fields.
    local_payload = {
        "opportunity": {
            "uuid": f"local:{event.id}",
            "labels": {"en": event.name},
            "description": event.description or "",  # comes from event form; not invented
            "schedule": {
                # you don't store dates/times on VolunteerEvent, so keep it empty unless you add fields later
                "date": None,
                "from": None,
                "to": None,
            },
            "where": {
                "address": {"city": event.location or ""},
            },
            "requirements": {
                "competences": [{"text": s.label} for s in event.skills.all()],
            },
            "visibility": {"federated": bool(event.isShared)},
        }
    }

    lr, _ = LocalResource.objects.update_or_create(
        organization=org,
        entity_type="OPPORTUNITY",
        local_id=f"local:{event.id}",
        defaults={"payload": local_payload},
    )

    # 2) Apply catalog -> canonical
    catalog = _load_catalog(org, "Opportunity")
    if catalog is None:
        # If org has no catalog yet (e.g., dev seeding), build from this payload as minimal fallback
        encoder = _get_encoder()
        candidates = get_canonical_properties("Opportunity")
        cfg = _mapping_cfg("Opportunity")
        proposals = propose_mappings_generic(
            encoder,
            entity="Opportunity",
            local_payload=local_payload,
            candidates=candidates,
            cfg=cfg,
            segmenter=split_into_segments,
        )
        catalog = build_opportunity_catalog(str(org.platform_key or org.id), proposals, org_name=org.name)
        _save_catalog(org, catalog)

    canonical = apply_opportunity_catalog(local_payload, catalog, org_name=org.name)

    # 3) Optional: skill normalization on canonical JSON-LD
    decisions = []
    if normalize_skills:
        retriever = _get_skill_retriever(lang=getattr(settings, "INTEROP_SKILL_LANG", "en"))
        cfg = _skill_cfg()
        canonical, decisions = normalize_skills_in_canonical_jsonld(
            canonical,
            retriever=retriever,
            cfg=cfg,
            encoder_name=_get_encoder().model_name,
            lang=getattr(settings, "INTEROP_SKILL_LANG", "en"),
            mode="esco_api+local_rerank",
        )

    cr, _ = CanonicalResource.objects.update_or_create(
        organization=org,
        entity_type="OPPORTUNITY",
        local_resource=lr,
        defaults={
            "canonical_id": str(canonical.get("@id") or ""),
            "canonical_jsonld": canonical,
        },
    )

    return {
        "status": "ok",
        "local_resource_id": lr.id,
        "canonical_resource_id": cr.id,
        "skills_normalized": bool(normalize_skills),
        "skill_decisions": [asdict(d) for d in decisions],
    }


# ---------------------------------------------------------------------
# FEDERATED QUERY: skill pipeline runs for query enrichment
# ---------------------------------------------------------------------

def normalize_query_skill_phrases(phrases: List[str], *, lang: str = "en") -> List[Dict[str, Any]]:
    """
    Use the same ESCO skill pipeline to normalize query phrases.
    Returns a list of ESCO-like objects suitable to compare/filter against canonical docs.
    """
    phrases = [p.strip() for p in (phrases or []) if p and p.strip()]
    if not phrases:
        return []

    retriever = _get_skill_retriever(lang=lang)
    cfg = _skill_cfg()

    # We re-use normalize_skills_in_canonical_jsonld by wrapping phrases into a "fake canonical"
    fake = {"@type": "vms:SkillQuery", "vms:requiresSkill": phrases}
    enriched, _decisions = normalize_skills_in_canonical_jsonld(
        fake,
        retriever=retriever,
        cfg=cfg,
        encoder_name=_get_encoder().model_name,
        lang=lang,
        mode="esco_api+local_rerank",
    )
    # The function adds vms:escoSkill
    return list(enriched.get("vms:escoSkill") or [])
