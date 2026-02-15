from __future__ import annotations

import re

from typing import Any, Dict, Tuple, List

from schema_mapping_common.esco_client import EscoClient
from schema_mapping_common.skill_normalization import (
    make_esco_api_retriever,
    normalize_skills_in_canonical_jsonld,
    SkillEngineConfig,
)
from schema_mapping_common.scoring import SemanticEncoder


def _esco_uri_to_curie(esco_id: str) -> str:
    if not isinstance(esco_id, str):
        return str(esco_id)
    m = re.search(r"/esco/skill/([0-9a-fA-F-]{32,36})", esco_id)
    if m:
        return f"esco:{m.group(1)}"
    return esco_id


def _project_esco_skill_to_requires_skill(
    doc: Dict[str, Any],
    *,
    keep_text_backup: bool = True,
    backup_key: str = "vms:requiresSkillText",
    keep_esco_debug: bool = True,
) -> Dict[str, Any]:
    out = dict(doc)

    rs = out.get("vms:requiresSkill")
    if keep_text_backup and isinstance(rs, list):
        original_phrases = [x for x in rs if isinstance(x, str) and x.strip()]
        if original_phrases:
            out[backup_key] = original_phrases

    esco_list = out.get("vms:escoSkill")
    if not isinstance(esco_list, list) or not esco_list:
        return out

    defined_terms: List[dict] = []
    for item in esco_list:
        if not isinstance(item, dict):
            continue
        uri = item.get("@id") or item.get("id") or item.get("uri")
        label = item.get("schema:name") or item.get("label") or item.get("name")
        if not uri or not label:
            continue
        defined_terms.append(
            {
                "@type": "schema:DefinedTerm",
                "@id": _esco_uri_to_curie(str(uri)),
                "schema:name": str(label),
            }
        )

    if defined_terms:
        out["vms:requiresSkill"] = defined_terms

    if not keep_esco_debug:
        out.pop("vms:escoSkill", None)

    return out


def _to_esco_compact_id(value: str) -> str:

    s = str(value).strip()

    if "/esco/skill/" in s:
        uuid = s.rsplit("/esco/skill/", 1)[-1]
    elif "data.europa.eu/esco" in s and "/skill/" in s:
        uuid = s.rsplit("/skill/", 1)[-1]
    else:
        uuid = ""

    if uuid:
        uuid = uuid.split("?", 1)[0].split("#", 1)[0].strip()
        if uuid:
            return f"esco:{uuid}"

    return s


def _project_requires_skill_only(canonical: Dict[str, Any]) -> Dict[str, Any]:
    esco_list = canonical.get("vms:escoSkill", [])
    terms: List[Dict[str, Any]] = []

    if isinstance(esco_list, list):
        for item in esco_list:
            if not isinstance(item, dict):
                continue
            esco_id = item.get("@id") or item.get("id") or item.get("uri")
            name = item.get("schema:name") or item.get("name")
            if not esco_id or not name:
                continue
            terms.append(
                {
                    "@type": "schema:DefinedTerm",
                    "@id": _to_esco_compact_id(str(esco_id)),
                    "schema:name": str(name),
                }
            )

    canonical["vms:requiresSkill"] = terms

    canonical.pop("vms:escoSkill", None)
    canonical.pop("vms:requiresSkillText", None)

    return canonical


def normalize_skills_in_canonical_jsonld_runtime(
    canonical_jsonld: Dict[str, Any],
    *,
    lang: str = "en",
    esco_version: str = "v1.2.0",
    encoder_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    mode: str = "esco_api+local_rerank",
    enable_printing: bool = True,
    k: int = 8,
    tau: float = 0.35,
    margin: float = 0.08,
    llm_min_conf_accept: float = 0.80,
) -> Tuple[Dict[str, Any], List[dict]]:

    encoder = SemanticEncoder(encoder_name)
    esco = EscoClient(selected_version=esco_version)
    retriever = make_esco_api_retriever(esco, encoder, lang=lang)

    cfg = SkillEngineConfig(
        k=k,
        tau=tau,
        margin=margin,
        llm_min_conf_accept=llm_min_conf_accept,
        enable_printing=enable_printing,
    )

    enriched, decisions = normalize_skills_in_canonical_jsonld(
        canonical_jsonld,
        retriever=retriever,
        cfg=cfg,
        encoder_name=encoder.model_name,
        lang=lang,
        mode=mode,
    )

    enriched = _project_requires_skill_only(enriched)
    return enriched, decisions


if __name__ == "__main__":
    import json
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser()
    ap.add_argument("--infile", required=True, help="Input canonical JSON-LD file")
    ap.add_argument("--lang", default="en")
    args = ap.parse_args()

    doc = json.loads(Path(args.infile).read_text(encoding="utf-8"))
    enriched, _ = normalize_skills_in_canonical_jsonld_runtime(doc, lang=args.lang, enable_printing=True)
    print(json.dumps(enriched, indent=2, ensure_ascii=False))
