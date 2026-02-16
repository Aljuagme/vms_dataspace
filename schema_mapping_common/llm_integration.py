import json
import os
import re
from typing import Any, List, Tuple, Optional

import requests
from .data_structures import CanonicalProperty

# -----------------------------------------------------------------------------
# Toggle
# -----------------------------------------------------------------------------
# If LOCAL=True -> call Ollama on localhost (your current behavior)
# If LOCAL=False -> call Groq API (hosted Llama 3.1)
LOCAL = False

# -----------------------------------------------------------------------------
# Local (Ollama) config
# -----------------------------------------------------------------------------
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# -----------------------------------------------------------------------------
# Remote (Groq) config (OpenAI-compatible)
# -----------------------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

# Keep this for your existing logging that prints MODEL
MODEL = OLLAMA_MODEL if LOCAL else GROQ_MODEL

LLM_SYSTEM = (
    "You are a careful ontology/schema mapping verifier. "
    "Your job is to choose the best target property among given candidates. "
    "Return STRICT JSON only."
)


def _strip_code_fences(s: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", s).strip()


def _build_user_prompt(
    *,
    field_name: str,
    example_value: Any,
    candidates: List[CanonicalProperty],
) -> dict:
    cand_list = [
        {
            "key": c.key,
            "label": c.label,
            "description": c.description,
            "expected_type": c.expected_type,
        }
        for c in candidates
    ]

    return {
        "task": "Select the best mapping target for a source field.",
        "source": {
            "field_name": field_name,
            "example_value": example_value,
        },
        "candidates": cand_list,
        "output_format": {
            "chosen_key": "string or null",
            "confidence": "number 0..1",
            "rationale": "short string",
        },
        "rules": [
            "Choose null if none fits.",
            "Prefer semantically correct mapping even if surface words overlap.",
            "Do not invent new keys.",
        ],
    }


def _parse_llm_json(content: str) -> Tuple[Optional[str], float, str]:
    content = _strip_code_fences(content)
    obj = json.loads(content)

    chosen = obj.get("chosen_key", None)
    conf = float(obj.get("confidence", 0.0))
    rat = str(obj.get("rationale", ""))[:200]

    if chosen is not None and not isinstance(chosen, str):
        chosen = None
    conf = max(0.0, min(1.0, conf))
    return chosen, conf, rat


def _ollama_call(*, payload: dict) -> str:
    r = requests.post(OLLAMA_URL, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    return data["message"]["content"]


def _groq_call(*, payload: dict) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is missing. Set GROQ_API_KEY env var or switch LOCAL=True."
        )

    url = f"{GROQ_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    r = requests.post(url, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


def ollama_select_candidate(
    *,
    field_name: str,
    example_value: Any,
    candidates: List[CanonicalProperty],
    model: str = None,
) -> Tuple[Optional[str], float, str]:
    """
    LLM-backed candidate selection.

    Compatibility note:
    - Function name kept as `ollama_select_candidate` to avoid changing the rest of your code.
    - Behavior depends on env var LOCAL:
        LOCAL=True  -> Ollama (localhost)
        LOCAL=False -> Groq API (hosted Llama 3.1)
    Returns: (chosen_key or None, confidence 0..1, rationale_short)
    """
    user_prompt = _build_user_prompt(
        field_name=field_name,
        example_value=example_value,
        candidates=candidates,
    )

    try:
        if LOCAL:
            use_model = model or OLLAMA_MODEL
            payload = {
                "model": use_model,
                "messages": [
                    {"role": "system", "content": LLM_SYSTEM},
                    {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
                ],
                "options": {"temperature": 0.0},
                "stream": False,
            }
            content = _ollama_call(payload=payload)
        else:
            use_model = model or GROQ_MODEL
            # OpenAI-compatible schema
            payload = {
                "model": use_model,
                "messages": [
                    {"role": "system", "content": LLM_SYSTEM},
                    {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
                ],
                "temperature": 0.0,
                "stream": False,
                # (Optional) you can add response_format if you want stricter JSON mode,
                # but keeping it simple + compatible:
                # "response_format": {"type": "json_object"},
            }
            content = _groq_call(payload=payload)

        return _parse_llm_json(content)

    except Exception as e:
        return None, 0.0, f"LLM error: {e}"
