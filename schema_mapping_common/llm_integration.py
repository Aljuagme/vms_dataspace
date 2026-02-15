
import json
import re

import requests
from typing import Any, List, Tuple, Optional
from .data_structures import CanonicalProperty

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.1:8b"
LLM_SYSTEM = (
    "You are a careful ontology/schema mapping verifier. "
    "Your job is to choose the best target property among given candidates. "
    "Return STRICT JSON only."
)


def ollama_select_candidate(
        *,
        field_name: str,
        example_value: Any,
        candidates: List[CanonicalProperty],
        model: str = MODEL,
) -> Tuple[Optional[str], float, str]:
    """
    Ask LLaMA (via Ollama) to pick the best candidate key.
    Returns: (chosen_key or None, confidence 0..1, rationale_short)
    """
    cand_list = [
        {
            "key": c.key,
            "label": c.label,
            "description": c.description,
            "expected_type": c.expected_type
        }
        for c in candidates
    ]

    user_prompt = {
        "task": "Select the best mapping target for a source field.",
        "source": {
            "field_name": field_name,
            "example_value": example_value,
        },
        "candidates": cand_list,
        "output_format": {
            "chosen_key": "string or null",
            "confidence": "number 0..1",
            "rationale": "short string"
        },
        "rules": [
            "Choose null if none fits.",
            "Prefer semantically correct mapping even if surface words overlap.",
            "Do not invent new keys."
        ]
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": LLM_SYSTEM},
            {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
        ],
        "options": {"temperature": 0.0},
        "stream": False,
    }

    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        content = data["message"]["content"]
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()
        obj = json.loads(content)

        chosen = obj.get("chosen_key", None)
        conf = float(obj.get("confidence", 0.0))
        rat = str(obj.get("rationale", ""))[:200]

        if chosen is not None and not isinstance(chosen, str):
            chosen = None
        conf = max(0.0, min(1.0, conf))
        return chosen, conf, rat
    except Exception as e:
        return None, 0.0, f"LLM error: {e}"