
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from schema_mapping_common.data_structures import CanonicalProperty, CandidateScore
from schema_mapping_common.utilities import (
    # shared utils
    source_context,
    normalize_text,
    tokenize,
    lexical_similarity,
    # regex/constants
    EMAIL_RE,
    PHONE_RE,
    DATE_RE,
    TIME_RE,
    TIME_RANGE_RE,
    WEEKDAYS,
    ANCHOR_VARIANTS, looks_like_address, looks_like_contact,
)

class SemanticEncoder:

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None  # lazy

    def _ensure_loaded(self):
        if self.model is None:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(self.model_name)

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed texts into vectors."""
        self._ensure_loaded()
        vecs = self.model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vecs]

    @staticmethod
    def cosine(a: List[float], b: List[float]) -> float:
        """Cosine similarity (assuming normalized embeddings)."""
        return float(sum(x * y for x, y in zip(a, b)))



# ----------------------------
# Scoring config
# ----------------------------

@dataclass(frozen=True)
class ScoringWeights:
    """
    Combined score:
      combined = sem_w * semantic + lex_w * lexical + boost_w * boost + boost
    where the extra '+ boost' makes boosts act as stabilizers.
    """
    sem_w: float = 0.80
    lex_w: float = 0.20
    boost_w: float = 0.5


@dataclass(frozen=True)
class BoostConfig:

    # name-semantic boost threshold
    name_sim_threshold: float = 0.35
    name_boost_value: float = 0.10

    # token overlap
    token_overlap_cap: float = 0.10
    token_overlap_step: float = 0.05

    # type cues
    email_boost: float = 0.20
    phone_boost: float = 0.10
    date_boost: float = 0.20
    time_boost: float = 0.20
    time_range_boost: float = 0.20
    weekday_boost: float = 0.20
    list_boost: float = 0.10
    int_boost: float = 0.20

    anchor_strong: float = 0.10
    anchor_time: float = 0.2
    anchor_skills: float = 0.5
    anchor_location: float = 0.2
    anchor_penalty_desc: float = -0.1


def _contains_weekday(text: str) -> bool:
    t = normalize_text(text)
    for token in WEEKDAYS.keys():
        if token in {"monday","tuesday","wednesday","thursday","friday","saturday","sunday"}:
            pat = rf"\b{re.escape(token)}s?\b"
        else:
            pat = rf"\b{re.escape(token)}\b"
        if re.search(pat, t):
            return True
    return False


def _starts_with_any(normalized_text: str, prefixes: Sequence[str]) -> bool:
    return any(normalized_text.startswith(p) for p in prefixes)


def type_boost(example: Any, candidate: CanonicalProperty, cfg: BoostConfig) -> float:

    boost = 0.0

    if isinstance(example, int) and candidate.expected_type == "Integer":
        boost += cfg.int_boost

    if isinstance(example, str):
        ex = example.strip()

        # address-like cue
        if looks_like_address(ex):
            if candidate.key in ("schema:location", "schema:address"):
                boost += 0.05  # tune
            if candidate.key == "schema:contactPoint" and not looks_like_contact(ex):
                boost -= 0.1  # tune

        # Email
        if EMAIL_RE.search(ex):
            if candidate.key == "schema:email" or candidate.expected_type in ("Email",):
                boost += cfg.email_boost

        # Phone
        if PHONE_RE.search(ex):
            if candidate.key in ("schema:telephone", "schema:contactPoint") or candidate.expected_type in ("Phone",):
                boost += cfg.phone_boost

        # Date
        if DATE_RE.match(ex) and candidate.expected_type == "Date":
            boost += cfg.date_boost

        # Time
        if TIME_RE.match(ex) and candidate.expected_type == "Time":
            boost += cfg.time_boost

        if TIME_RANGE_RE.search(ex) and candidate.key in ("vms:startTime", "vms:endTime", "vms:timeSlots"):
            boost += cfg.time_range_boost

        if candidate.key == "vms:daysOfWeek" and _contains_weekday(ex):
            boost += cfg.weekday_boost

        if candidate.key in ("schema:location", "schema:address") and len(ex) >= 3:
            boost += 0.05

    if isinstance(example, (list, tuple, set)) and candidate.expected_type in ("TextList", "IdList"):
        boost += cfg.list_boost

    return boost


def field_token_overlap_boost(source_path: str, candidate: CanonicalProperty, cfg: BoostConfig) -> float:
    field = source_path.split(".")[-1]
    ft = set(tokenize(field))
    ct = set(tokenize(candidate.key + " " + candidate.label + " " + candidate.description))
    if not ft or not ct:
        return 0.0
    overlap = ft.intersection(ct)
    if not overlap:
        return 0.0
    return min(cfg.token_overlap_cap, cfg.token_overlap_step * len(overlap))


def name_semantic_boost(
    encoder: SemanticEncoder,
    source_path: str,
    candidate: CanonicalProperty,
    cfg: BoostConfig,
) -> float:

    field_name = source_path.split(".")[-1]
    texts = [f"name:{field_name}", candidate.signature()]
    vecs = encoder.embed(texts)
    sim = encoder.cosine(vecs[0], vecs[1])
    return cfg.name_boost_value if sim >= cfg.name_sim_threshold else 0.0


def anchor_boost(example: Any, candidate: CanonicalProperty, cfg: BoostConfig) -> float:

    if not isinstance(example, str):
        return 0.0

    s = normalize_text(example)

    if _starts_with_any(s, ANCHOR_VARIANTS["skills"]):
        if candidate.key in ("vms:requiresSkill", "schema:skills"):
            return cfg.anchor_skills
        if candidate.key == "schema:description":
            return cfg.anchor_penalty_desc

    if _starts_with_any(s, ANCHOR_VARIANTS["availability"]):
        if candidate.key == "vms:daysOfWeek":
            return cfg.anchor_strong
        if candidate.key in ("vms:startTime", "vms:endTime", "vms:availability"):
            return 0.05

    if _starts_with_any(s, ANCHOR_VARIANTS["time"]):
        if candidate.key in ("vms:startTime", "vms:endTime", "vms:timeSlots"):
            return cfg.anchor_time

    if _starts_with_any(s, ANCHOR_VARIANTS["contact"]):
        if candidate.key in ("schema:contactPoint", "schema:email", "schema:telephone"):
            return cfg.anchor_strong

    if _starts_with_any(s, ANCHOR_VARIANTS["location"]):
        if candidate.key in ("schema:location", "schema:address"):
            return cfg.anchor_location

    return 0.0


def score_candidate(
    encoder: SemanticEncoder,
    ctx_vec: List[float],
    cand_vec: List[float],
    *,
    source_path: str,
    example: Any,
    candidate: CanonicalProperty,
    weights: ScoringWeights,
    boosts_cfg: BoostConfig,
) -> CandidateScore:
    sem = encoder.cosine(ctx_vec, cand_vec)

    leaf = source_path.split(".")[-1]
    lex = max(
        lexical_similarity(source_path, candidate.key),
        lexical_similarity(leaf, candidate.key),
        lexical_similarity(leaf, candidate.label),
        lexical_similarity(leaf, candidate.description),
    )

    b = (
        type_boost(example, candidate, boosts_cfg)
        + anchor_boost(example, candidate, boosts_cfg)
        + field_token_overlap_boost(source_path, candidate, boosts_cfg)
        + name_semantic_boost(encoder, source_path, candidate, boosts_cfg)
    )
    b = max(-0.15, min(0.35, b))  # clamp
    combined = weights.sem_w * sem + weights.lex_w * lex + b

    return CandidateScore(
        candidate=candidate,
        semantic=sem,
        lexical=lex,
        boost=b,
        combined=combined,
    )


def rank_candidates(
    encoder: SemanticEncoder,
    candidates: List[CanonicalProperty],
    *,
    source_path: str,
    example: Any,
    k: int = 6,
    weights: Optional[ScoringWeights] = None,
    boosts_cfg: Optional[BoostConfig] = None,
) -> List[CandidateScore]:

    weights = weights or ScoringWeights()
    boosts_cfg = boosts_cfg or BoostConfig()

    ctx = source_context(source_path, example)
    texts = [ctx] + [c.signature() for c in candidates]
    vecs = encoder.embed(texts)

    ctx_vec = vecs[0]
    cand_vecs = vecs[1:]

    scored: List[CandidateScore] = []
    for c, v in zip(candidates, cand_vecs):
        scored.append(
            score_candidate(
                encoder,
                ctx_vec,
                v,
                source_path=source_path,
                example=example,
                candidate=c,
                weights=weights,
                boosts_cfg=boosts_cfg,
            )
        )

    scored.sort(key=lambda x: x.combined, reverse=True)
    return scored[:k]