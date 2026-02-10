import json
from schema_mapping_common.esco_client import EscoClient
from schema_mapping_common.skill_normalization import (
    make_esco_api_retriever,
    normalize_skills_in_canonical_jsonld,
    SkillEngineConfig,
)
from schema_mapping_common.scoring import SemanticEncoder

canonical = json.load(open("../output_opportunity.json", "r", encoding="utf-8"))

encoder = SemanticEncoder("sentence-transformers/all-MiniLM-L6-v2")

esco = EscoClient(selected_version="v1.2.0")
retriever = make_esco_api_retriever(esco, encoder, lang="en")

cfg = SkillEngineConfig(k=8, tau=0.35, margin=0.08, llm_min_conf_accept=0.80, enable_printing=True)

enriched, decisions = normalize_skills_in_canonical_jsonld(
    canonical,
    retriever=retriever,
    cfg=cfg,
    encoder_name=encoder.model_name,
    lang="en",
    mode="esco_api+local_rerank",
)

print(json.dumps(enriched, indent=2, ensure_ascii=False))
