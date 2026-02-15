
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable, Tuple

from schema_mapping_common.data_structures import CanonicalProperty, MappingProposal, CandidateScore
from schema_mapping_common.utilities import flatten_payload, decide_mapping
from schema_mapping_common.scoring import SemanticEncoder, rank_candidates
from schema_mapping_common.llm_integration import ollama_select_candidate


CompositeDetector = Callable[[str, Any], bool]
Segmenter = Callable[[str], List[str]]


@dataclass(frozen=True)
class MappingEngineConfig:
    k: int = 5
    tau: float = 0.30
    margin: float = 0.08
    llm_min_conf_accept: float = 0.80

    # Composite behaviour
    enable_composite: bool = False
    composite_min_len: int = 70
    print_width: int = 90


def _default_is_composite(source_path: str, example: Any, *, min_len: int = 70) -> bool:

    if not isinstance(example, str):
        return False
    t = example.strip()
    if len(t) < min_len:
        return False

    low = t.lower()
    anchors = [
        "qualifications:", "availability:", "time:", "commitment:",
        "requirements:", "skills:", "contact:", "email:", "phone:", "hours:", "location:"
    ]
    anchor_hits = sum(1 for a in anchors if a in low)

    sentence_hits = (t.count(".") + t.count("!") + t.count("?")) >= 1
    return anchor_hits >= 2 or sentence_hits


def _default_split_into_segments(text: str) -> List[str]:

    raw = str(text).strip()
    if not raw:
        return []

    parts: List[str] = []
    buf = ""
    for ch in raw:
        buf += ch
        if ch in ".!?":
            seg = buf.strip()
            if seg:
                parts.append(seg)
            buf = ""
    tail = buf.strip()
    if tail:
        parts.append(tail)

    out: List[str] = []
    seen = set()
    for p in parts:
        k = p.lower().strip()
        if k and k not in seen:
            seen.add(k)
            out.append(p.strip())
    return out


def _print_header(entity: str, encoder: SemanticEncoder, cfg: MappingEngineConfig) -> None:
    w = cfg.print_width
    print("\n" + "=" * w)
    print(f"SCHEMA MAPPING PROPOSAL FOR ENTITY: {entity}")
    print(f"Semantic encoder: {encoder.model_name}")
    print(f"tau={cfg.tau:.2f} | margin={cfg.margin:.2f} | k={cfg.k}")
    print(f"LLM verifier: Ollama/{getattr(__import__('schema_mapping_common.llm_integration', fromlist=['MODEL']), 'MODEL', 'model')} "
          f"(only for AMBIGUOUS; accept if conf>={cfg.llm_min_conf_accept:.2f})")
    if cfg.enable_composite:
        print("Composite: enabled (will decompose long text blocks)")
    else:
        print("Composite: disabled")
    print("=" * w)


def _print_ranked(source_path: str, example: Any, ranked: List[CandidateScore], cfg: MappingEngineConfig, *, max_rows: int) -> None:
    w = cfg.print_width
    print("\n" + "-" * w)
    print(f"Source field: {source_path}")
    print(f"Example value: {repr(example)[:260]}")
    print("Top candidates:")
    for i, sc in enumerate(ranked[:max_rows], start=1):
        print(
            f"  {i}. {sc.candidate.key} ({sc.candidate.label}) | "
            f"sem={sc.semantic:.3f} lex={sc.lexical:.3f} boost={sc.boost:.2f} comb={sc.combined:.3f}"
        )


def _maybe_llm_override(
    *,
    status: str,
    source_path: str,
    example: Any,
    ranked: List[CandidateScore],
    best_target: Optional[CanonicalProperty],
    cfg: MappingEngineConfig,
) -> Tuple[str, Optional[CanonicalProperty], str]:

    if status != "AMBIGUOUS":
        return status, best_target, ""

    top_props = [sc.candidate for sc in ranked[:3]]
    chosen_key, conf, rat = ollama_select_candidate(
        field_name=source_path,
        example_value=example,
        candidates=top_props,
    )

    if chosen_key and conf >= cfg.llm_min_conf_accept:
        best = next((c for c in top_props if c.key == chosen_key), best_target)
        return "ACCEPTED", best, f"LLM override (conf={conf:.2f}): {rat}"

    return "AMBIGUOUS", best_target, f"LLM conf={conf:.2f} ({rat})"


def propose_mappings_generic(
    encoder: SemanticEncoder,
    *,
    entity: str,
    local_payload: Dict[str, Any],
    candidates: List[CanonicalProperty],
    cfg: Optional[MappingEngineConfig] = None,
    composite_detector: Optional[CompositeDetector] = None,
    segmenter: Optional[Segmenter] = None,
) -> List[MappingProposal]:


    IGNORED_SOURCE_FIELDS = set()

    cfg = cfg or MappingEngineConfig()
    composite_detector = composite_detector or (lambda p, e: _default_is_composite(p, e, min_len=cfg.composite_min_len))
    segmenter = segmenter or _default_split_into_segments

    _print_header(entity, encoder, cfg)

    proposals: List[MappingProposal] = []

    for source_path, example in flatten_payload(local_payload):
        base_key = source_path.split(".", 1)[0]  # handles "tshirt_size" and "tshirt_size.foo"
        if base_key in IGNORED_SOURCE_FIELDS:
            continue

        if cfg.enable_composite and composite_detector(source_path, example):
            proposals.append(
                MappingProposal(
                    source_path=source_path,
                    example=example,
                    best_target=None,
                    status="COMPOSITE",
                    ranked=[],
                    note="decompose into segments; aggregate results (no 1→1)",
                )
            )

            w = cfg.print_width
            print("\n" + "-" * w)
            print(f"Source field: {source_path}")
            print(f"Example value: {repr(example)[:260]}")
            print("Decision: COMPOSITE (decomposing into segments; not mapped 1→1)")

            segments = segmenter(str(example))
            print("\n[Composite decomposition]")
            for idx, seg in enumerate(segments, start=1):
                seg_path = f"{source_path}::seg{idx}"

                ranked = rank_candidates(
                    encoder,
                    candidates,
                    source_path=seg_path,
                    example=seg,
                    k=cfg.k,
                )

                status, best, note = decide_mapping(ranked, tau=cfg.tau, margin=cfg.margin)

                if status == "AMBIGUOUS":
                    status2, best2, llm_note = _maybe_llm_override(
                        status=status,
                        source_path=seg_path,
                        example=seg,
                        ranked=ranked,
                        best_target=best,
                        cfg=cfg,
                    )
                    status, best = status2, best2
                    note = f"{note}; {llm_note}".strip("; ")

                _print_ranked(seg_path, seg, ranked, cfg, max_rows=min(5, cfg.k))

                if status == "REJECTED":
                    print(f"Decision: REJECTED ({note})")
                elif best:
                    print(f"Decision: {status} -> {best.key} ({note})")
                    proposals.append(
                        MappingProposal(
                            source_path=seg_path,
                            example=seg,
                            best_target=best,
                            status=status,
                            ranked=ranked,
                            note=f"from composite:{source_path} | {note}",
                        )
                    )
                else:
                    print(f"Decision: {status} -> None ({note})")

            continue

        ranked = rank_candidates(
            encoder,
            candidates,
            source_path=source_path,
            example=example,
            k=cfg.k,
        )

        status, best, note = decide_mapping(ranked, tau=cfg.tau, margin=cfg.margin)

        if status == "AMBIGUOUS":
            status2, best2, llm_note = _maybe_llm_override(
                status=status,
                source_path=source_path,
                example=example,
                ranked=ranked,
                best_target=best,
                cfg=cfg,
            )
            status, best = status2, best2
            note = f"{note}; {llm_note}".strip("; ")

        _print_ranked(source_path, example, ranked, cfg, max_rows=min(6, cfg.k))

        if status == "REJECTED":
            proposals.append(MappingProposal(source_path, example, None, status, ranked, note=note))
            print(f"Decision: REJECTED ({note})")
        else:
            proposals.append(MappingProposal(source_path, example, best, status, ranked, note=note))
            print(f"Decision: {status} -> {best.key if best else 'None'} ({note})")

    return proposals