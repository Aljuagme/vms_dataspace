# schema_mapping_common/esco_client.py
from __future__ import annotations

import requests
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class EscoSkillHit:
    uri: str
    title: str
    score: float = 0.0  # API score if available, else 0


class EscoClient:
    """
    Minimal ESCO API client (online retrieval mode).

    ESCO web services provide skill concepts identified by URIs.
    Docs: ESCO Web Services API + REST docs (HAL JSON).
    """

    def __init__(
        self,
        base_url: str = "https://ec.europa.eu/esco/api",
        *,
        timeout_s: int = 30,
        selected_version: Optional[str] = None,  # e.g., "v1.2.0"
        user_agent: str = "vms-dataspace-prototype/1.0",
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.selected_version = selected_version
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.selected_version:
            params = dict(params)
            params["selectedVersion"] = self.selected_version
        url = f"{self.base_url}/{path.lstrip('/')}"
        r = requests.get(url, params=params, headers=self.headers, timeout=self.timeout_s)
        r.raise_for_status()
        return r.json()

    def search_skills(self, text: str, *, limit: int = 8, lang: str = "en") -> List[EscoSkillHit]:
        """
        Search ESCO skills by free text.

        ESCO returns HAL JSON. We extract candidate URIs + titles from common fields:
        - _embedded results arrays (varies by endpoint)
        - _links entries containing 'uri' and 'title'
        """
        q = (text or "").strip()
        if not q:
            return []

        # Common ESCO search patterns:
        # - /search?type=skill&text=... (widely used in ESCO examples)
        # If ESCO changes the shape, the parser still tries to extract uri/title from links.
        data = self._get("search", params={"type": "skill", "text": q, "limit": limit, "language": lang})

        hits: List[EscoSkillHit] = []

        def add_hit(uri: Optional[str], title: Optional[str], score: float = 0.0) -> None:
            if not uri or not title:
                return
            hits.append(EscoSkillHit(uri=str(uri), title=str(title), score=float(score or 0.0)))

        # 1) Try embedded results
        embedded = data.get("_embedded") or {}
        for key, arr in embedded.items():
            if not isinstance(arr, list):
                continue
            for item in arr:
                if not isinstance(item, dict):
                    continue
                title = item.get("title") or item.get("preferredLabel") or item.get("label")
                links = item.get("_links") or {}
                self_link = links.get("self") or {}
                uri = self_link.get("uri") or item.get("uri")
                score = item.get("score") or 0.0
                add_hit(uri, title, score)

        # 2) Fallback: scan links for uri/title
        if not hits:
            links = data.get("_links") or {}
            for _, v in links.items():
                if isinstance(v, list):
                    for x in v:
                        if isinstance(x, dict) and x.get("uri") and x.get("title"):
                            add_hit(x.get("uri"), x.get("title"), 0.0)
                elif isinstance(v, dict) and v.get("uri") and v.get("title"):
                    add_hit(v.get("uri"), v.get("title"), 0.0)

        # Dedup by uri, keep best score
        by_uri: Dict[str, EscoSkillHit] = {}
        for h in hits:
            cur = by_uri.get(h.uri)
            if cur is None or h.score > cur.score:
                by_uri[h.uri] = h

        out = list(by_uri.values())
        out.sort(key=lambda x: x.score, reverse=True)
        return out[:limit]
