from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Callable

from schema_mapping_common.utilities import normalize_text, split_into_segments
from schema_mapping_common.scoring import SemanticEncoder
from schema_mapping_common.llm_integration import ollama_select_candidate


@dataclass(frozen=True)
class SkillCandidate:
    uri: str
    label: str
    score: float


@dataclass(frozen=True)
class SkillDecision:
    phrase: str
    chosen_uri: Optional[str]
    chosen_label: Optional[str]
    confidence: float
    method: str
    note: str = ""


@dataclass(frozen=True)
class SkillCandidateScore:
    uri: str
    label: str
    semantic: float
    lexical: float
    boost: float
    combined: float


@dataclass(frozen=True)
class SkillEngineConfig:
    k: int = 8
    tau: float = 0.55
    margin: float = 0.08
    llm_min_conf_accept: float = 0.80
    print_width: int = 90
    max_print_rows: int = 5
    enable_printing: bool = True


def _print_skill_header(cfg: SkillEngineConfig, *, encoder_name: str, lang: str, mode: str) -> None:
    if not cfg.enable_printing:
        return
    w = cfg.print_width
    print("\n" + "=" * w)
    print("SKILL NORMALIZATION (ESCO) — PROPOSAL / AUDIT LOG")
    print(f"Retriever mode: {mode} | language={lang}")
    print(f"Semantic encoder: {encoder_name}")
    print(f"tau={cfg.tau:.2f} | margin={cfg.margin:.2f} | k={cfg.k}")
    print(
        f"LLM verifier: Ollama/{getattr(__import__('schema_mapping_common.llm_integration', fromlist=['MODEL']), 'MODEL', 'model')}"
        f" (only for AMBIGUOUS; accept if conf>={cfg.llm_min_conf_accept:.2f})"
    )
    print("=" * w)


def _print_ranked_phrase(phrase: str, ranked: List[SkillCandidateScore], cfg: SkillEngineConfig) -> None:
    if not cfg.enable_printing:
        return
    w = cfg.print_width
    print("\n" + "-" * w)
    print(f"Skill phrase: {phrase}")
    print("Top candidates:")
    for i, sc in enumerate(ranked[: cfg.max_print_rows], start=1):
        print(
            f"  {i}. {sc.label} | "
            f"sem={sc.semantic:.3f} lex={sc.lexical:.3f} boost={sc.boost:.2f} comb={sc.combined:.3f} | {sc.uri}"
        )


def _print_decision(decision: "SkillDecision", cfg: SkillEngineConfig) -> None:
    if not cfg.enable_printing:
        return
    w = cfg.print_width
    if decision.method == "ACCEPT":
        print(f"Decision: ACCEPT → {decision.chosen_label} (conf={decision.confidence:.2f})  [{decision.note}]")
    elif decision.method == "REJECT":
        print(f"Decision: REJECT (conf={decision.confidence:.2f})  [{decision.note}]")
    else:
        print(f"Decision: AMBIGUOUS → LLM (conf={decision.confidence:.2f})  [{decision.note}]")
    print("-" * w)

_AND_OR_SPLIT_RE = re.compile(
    r"""
    (?:\s*[;,]\s*)                              # separators ; ,
    |(?:\s*/\s*)                                # slash
    |(?:\s+\&\s+)                               # &
    |(?:\s+\band\b\s+)                          # and
    |(?:\s+\bor\b\s+)                           # or
    |(?:\s+\band\/or\b\s+)                      # and/or
    |(?:\s+\by\b\s+)                            # Spanish: y
    |(?:\s+\bo\b\s+)                            # Spanish: o
    |(?:\s+\bund\b\s+)                          # German: und
    |(?:\s+\boder\b\s+)                         # German: oder
    """,
    re.IGNORECASE | re.VERBOSE,
)

_EITHER_PREFIX_RE = re.compile(r"^\s*(either|either:)\s+", re.IGNORECASE)

_LANGUAGE_PREFIX_RE = re.compile(
    r"^\s*(?:to\s+)?"
    r"(speak|write|read|understand|communicate|communicate\s+in|use|knowledge\s+of|fluent\s+in|proficient\s+in)\s+",
    re.IGNORECASE,
)

_LANGUAGE_FILLERS_RE = re.compile(r"^\s*(?:either|in|the|a|an)\s+", re.IGNORECASE)


def _clean_piece(s: str) -> str:
    s = s.strip(" \t\r\n-–—·•.()[]{}:;")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def decompose_skill_phrase(phrase: str) -> List[str]:
    p = (phrase or "").strip()
    if not p:
        return []

    p2 = _LANGUAGE_PREFIX_RE.sub("", p)
    p2 = _EITHER_PREFIX_RE.sub("", p2)
    p2 = _LANGUAGE_FILLERS_RE.sub("", p2).strip()

    if len(p2) >= 2:
        p = p2

    parts = [x for x in _AND_OR_SPLIT_RE.split(p) if x and x.strip()]
    if not parts:
        parts = [p]

    out: List[str] = []
    for part in parts:
        s = _clean_piece(part)
        if not s:
            continue
        if len(s) < 2 or len(s) > 80:
            continue
        out.append(s)

    if len(out) > 6:
        return [_clean_piece(phrase)]

    return out


def extract_skill_phrases(canonical: Dict[str, Any]) -> List[str]:

    raw: List[str] = []

    def add_many(v: Any) -> None:
        if isinstance(v, list):
            for x in v:
                if isinstance(x, dict):
                    phrase = x.get("vms:sourcePhrase") or x.get("schema:name") or x.get("name")
                    if isinstance(phrase, str) and phrase.strip():
                        raw.append(phrase.strip())
                    continue
                s = str(x).strip()
                if s:
                    raw.append(s)
        elif isinstance(v, dict):
            phrase = v.get("vms:sourcePhrase") or v.get("schema:name") or v.get("name")
            if isinstance(phrase, str) and phrase.strip():
                raw.append(phrase.strip())
        elif isinstance(v, str) and v.strip():
            raw.append(v.strip())

    add_many(canonical.get("schema:skills"))
    add_many(canonical.get("vms:requiresSkill"))

    desc = canonical.get("schema:description")
    if isinstance(desc, str) and desc.strip():
        for seg in split_into_segments(desc):
            low = normalize_text(seg)
            if any(low.startswith(a) for a in ["skills:", "requirements:", "qualifications:", "required:"]):
                tail = seg.split(":", 1)[1].strip() if ":" in seg else seg.strip()
                for item in [x.strip() for x in tail.replace("\n", ";").split(";") if x.strip()]:
                    raw.append(item)

    out: List[str] = []
    seen = set()
    for s in raw:
        s2 = str(s).strip()
        if not s2:
            continue
        key = normalize_text(s2, keep_colon=False)
        if key and key not in seen:
            seen.add(key)
            out.append(s2)
    return out


Retriever = Callable[[str, int], List[SkillCandidateScore]]  # (phrase, k) -> candidates


def _language_tokens(s: str) -> List[str]:
    langs = ["english", "spanish", "german", "french", "italian", "portuguese", "catalan", "deutsch", "español", "inglés"]
    low = normalize_text(s, keep_colon=False)
    return [l for l in langs if l in low]


def _compute_boost(phrase: str, label: str) -> float:
    p = normalize_text(phrase, keep_colon=False)
    l = normalize_text(label, keep_colon=False)

    boost = 0.0

    ptoks = _language_tokens(p)
    if ptoks:
        for t in ptoks:
            if t in l:
                boost += 0.10
                break

    if "first aid" in p and "first aid" in l:
        boost += 0.10

    return min(boost, 0.20)


def make_esco_api_retriever(esco_client, encoder: SemanticEncoder, *, lang: str = "en") -> Retriever:

    from schema_mapping_common.utilities import lexical_similarity, normalize_text

    def _r(phrase: str, k: int) -> List[SkillCandidateScore]:
        hits = esco_client.search_skills(phrase, limit=max(25, k), lang=lang)
        if not hits:
            return []

        qv = encoder.embed([phrase])[0]

        ranked: List[SkillCandidateScore] = []
        for h in hits:
            lv = encoder.embed([h.title])[0]
            sem = float(encoder.cosine(qv, lv))

            a_norm = normalize_text(phrase, keep_colon=False)
            b_norm = normalize_text(h.title, keep_colon=False)

            lex = float(
                max(
                    lexical_similarity(a_norm, b_norm),
                    lexical_similarity(phrase, h.title),
                )
            )

            boost = float(_compute_boost(phrase, h.title))

            comb = 0.75 * sem + 0.20 * lex + 0.05 * boost

            ranked.append(
                SkillCandidateScore(
                    uri=h.uri,
                    label=h.title,
                    semantic=sem,
                    lexical=lex,
                    boost=boost,
                    combined=float(comb),
                )
            )

        ranked.sort(key=lambda x: x.combined, reverse=True)
        return ranked[:k]

    return _r



def make_local_embedding_retriever(
    encoder: SemanticEncoder,
    *,
    esco_index: List[Tuple[str, str]],
) -> Retriever:

    labels = [lbl for _, lbl in esco_index]
    label_vecs = encoder.embed(labels)

    def _r(phrase: str, k: int) -> List[SkillCandidate]:
        qv = encoder.embed([phrase])[0]
        scored: List[SkillCandidate] = []
        for (uri, lbl), lv in zip(esco_index, label_vecs):
            sim = encoder.cosine(qv, lv)
            scored.append(SkillCandidate(uri=uri, label=lbl, score=float(sim)))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:k]

    return _r


def decide_skill(
    phrase: str,
    candidates: List[SkillCandidateScore],
    *,
    cfg: SkillEngineConfig,
) -> SkillDecision:

    _print_ranked_phrase(phrase, candidates, cfg)

    if not candidates:
        d = SkillDecision(phrase, None, None, 0.0, "REJECT", note="no candidates")
        _print_decision(d, cfg)
        return d

    c1 = candidates[0]
    c2 = candidates[1] if len(candidates) > 1 else None

    if c1.combined < cfg.tau:
        d = SkillDecision(phrase, None, None, float(c1.combined), "REJECT", note=f"below tau={cfg.tau:.2f}")
        _print_decision(d, cfg)
        return d

    if c2 is None or (c1.combined - c2.combined) >= cfg.margin:
        conf = max(0.0, min(1.0, float(c1.combined)))
        d = SkillDecision(phrase, c1.uri, c1.label, conf, "ACCEPT", note=f"margin >= {cfg.margin:.2f}")
        _print_decision(d, cfg)
        return d

    from schema_mapping_common.data_structures import CanonicalProperty

    top = candidates[:3]
    props = [
        CanonicalProperty(
            key=t.uri,
            label=t.label,
            description="ESCO skill concept",
            expected_type="URI",
            entity="Skill",
        )
        for t in top
    ]

    chosen_key, llm_conf, rat = ollama_select_candidate(
        field_name=f"skill_phrase:{phrase}",
        example_value=phrase,
        candidates=props,
    )

    if chosen_key and llm_conf >= cfg.llm_min_conf_accept:
        chosen = next((t for t in top if t.uri == chosen_key), None)
        if chosen:
            d = SkillDecision(
                phrase,
                chosen.uri,
                chosen.label,
                float(llm_conf),
                "LLM",
                note=f"LLM chose: {chosen.label} | rationale: {rat}",
            )
            _print_decision(d, cfg)
            return d

    d = SkillDecision(
        phrase,
        c1.uri,
        c1.label,
        float(llm_conf),
        "LLM",
        note=f"LLM low-conf → keep top-1 ({c1.label}) | rationale: {rat}",
    )
    _print_decision(d, cfg)
    return d


def normalize_skills_in_canonical_jsonld(
    canonical: Dict[str, Any],
    *,
    retriever: Retriever,
    cfg: SkillEngineConfig,
    encoder_name: str = "unknown",
    lang: str = "en",
    mode: str = "esco_api+local_rerank",
) -> Tuple[Dict[str, Any], List[SkillDecision]]:

    _print_skill_header(cfg, encoder_name=encoder_name, lang=lang, mode=mode)

    phrases = extract_skill_phrases(canonical)
    exploded: List[str] = []
    seen = set()
    for p in phrases:
        for atom in decompose_skill_phrase(p):
            key = normalize_text(atom, keep_colon=False)
            if key and key not in seen:
                seen.add(key)
                exploded.append(atom)

    decisions: List[SkillDecision] = []
    normalized: List[Dict[str, Any]] = []

    for p in exploded:
        cands = retriever(p, cfg.k)
        d = decide_skill(p, cands, cfg=cfg)
        decisions.append(d)

        if d.chosen_uri and d.chosen_label:
            normalized.append(
                {
                    "@id": d.chosen_uri,
                    "schema:name": d.chosen_label,
                    "vms:confidence": round(float(d.confidence), 3),
                    "vms:sourcePhrase": d.phrase,
                }
            )

    out = dict(canonical)
    if normalized:
        out["vms:escoSkill"] = normalized

    return out, decisions
