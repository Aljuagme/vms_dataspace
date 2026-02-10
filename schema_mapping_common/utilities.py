"""
utilities.py
============
Shared utility functions for schema mapping.
"""

import re
import json
from typing import Any, Dict, List, Tuple, Optional
from difflib import SequenceMatcher
from pathlib import Path

from schema_mapping_common.data_structures import CandidateScore, CanonicalProperty, get_canonical_properties

# ================================================
# Order
# ================================================
ORDER_VOLUNTEER: List[str] = [
    "@context",
    "@type",
    "@id",
    "schema:givenName",
    "schema:familyName",
    "schema:email",
    "schema:telephone",
    "schema:address",
    "vms:availability",
    "schema:skills",
]

ORDER_OPPORTUNITY: List[str] = [
    "@context",
    "@type",
    "@id",
    "schema:name",
    "schema:description",
    "schema:startDate",
    "schema:endDate",
    "vms:startTime",
    "vms:endTime",
    "schema:location",
    "schema:organizer",
    "schema:maximumAttendeeCapacity",
    "vms:daysOfWeek",
    "vms:requiresSkill",
    "vms:visibility",
]

# IMPORTANT: schema:contactPoint is NOT top-level in your thesis, it's inside schema:organizer.
FORBIDDEN_TOPLEVEL_KEYS = {"schema:contactPoint"}

# ================================================
# Constants
# ================================================
CAMEL_BREAK_RE = re.compile(r"([a-z])([A-Z])")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
TIME_RANGE_RE = re.compile(r"\b(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\b")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{6,}\d)")

WEEKDAYS = {
    "monday": "Monday", "tuesday": "Tuesday", "wednesday": "Wednesday", "thursday": "Thursday",
    "friday": "Friday", "saturday": "Saturday", "sunday": "Sunday",
    "montag": "Monday", "dienstag": "Tuesday", "mittwoch": "Wednesday", "donnerstag": "Thursday",
    "freitag": "Friday", "samstag": "Saturday", "sonntag": "Sunday",
    "lunes": "Monday", "martes": "Tuesday", "miércoles": "Wednesday", "miercoles": "Wednesday",
    "jueves": "Thursday", "viernes": "Friday", "sábado": "Saturday", "sabado": "Saturday",
    "domingo": "Sunday",
}

WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

ANCHOR_VARIANTS = {
    "skills": ["qualifications:", "requirements:", "skills:", "required:", "you need:", "must have:", "nice to have:"],
    "availability": ["availability:", "days:", "day:", "schedule:", "when:", "weekday:"],
    "time": ["time:", "hours:", "hour:", "shift:", "shifts:"],
    "contact": ["contact:", "email:", "phone:", "telephone:", "tel:"],
    "location": ["location:", "where:", "address:"],
}

ANCHOR_RE = re.compile(
    r"(Qualifications:|Availability:|Time:|Commitment:|Requirements:|Skills:|Contact:|Hours:|Location:)",
    re.I
)


def load_json_payload(rel_path: str) -> Dict[str, Any]:
    """Load JSON payload from a relative path."""
    base = Path(__file__).resolve().parent
    path = base / rel_path
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_text(
    s: str,
    *,
    keep_colon: bool = True,
) -> str:
    """
    Normalize text for comparison/search.
    - split_camel: inserts spaces in camelCase / PascalCase strings
    - keep_colon: keep ':' useful for anchors like 'skills:'.
    """
    s = str(s).strip()

    s = CAMEL_BREAK_RE.sub(r"\1 \2", s)

    s = s.lower()

    allowed = r"[^a-z0-9\s:]+" if keep_colon else r"[^a-z0-9\s]+"
    s = re.sub(allowed, " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def tokenize(s: str) -> List[str]:
    """Tokenize text into words."""
    return [t for t in normalize_text(s).split() if t]


def flatten_payload(payload: Dict[str, Any], prefix: str = "") -> List[Tuple[str, Any]]:
    """
    Recursive flattening:
    - dict: expands keys (a.b.c)
    - list/tuple/set: kept as list value under the current path
    - primitives: emitted as-is
    """
    out: List[Tuple[str, Any]] = []

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                p = f"{path}.{k}" if path else str(k)
                walk(v, p)
        elif isinstance(obj, (list, tuple, set)):
            out.append((path, list(obj)))
        else:
            out.append((path, obj))

    walk(payload, prefix)
    return out


def source_context(path: str, example: Any) -> str:
    """Build a context string for embedding similarity."""
    if isinstance(example, (list, tuple, set)):
        ex = ", ".join(map(str, list(example)[:5]))
    else:
        ex = str(example)
    ex = ex[:260]
    return f"field:{path} example:{ex}"


def lexical_similarity(a: str, b: str) -> float:
    """Calculate lexical similarity between two strings."""
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def decide_mapping(
    ranked: List[CandidateScore],
    tau: float,
    margin: float,
) -> Tuple[str, Optional[CanonicalProperty], str]:
    """
    Decide mapping status based on scores.
    Returns: (status, best_target, note)
    """
    if not ranked:
        return "REJECTED", None, "no candidates"

    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None

    if best.combined < tau:
        return "REJECTED", None, f"below tau={tau:.2f}"

    if second is None or (best.combined - second.combined) >= margin:
        return "ACCEPTED", best.candidate, f"margin >= {margin:.2f}"

    return "AMBIGUOUS", best.candidate, "needs admin / LLM"


def split_into_segments(text: str) -> List[str]:
    """
    Anchor-aware, sentence-ish segmentation without duplicating anchors.
    - First split by punctuation to keep segments manageable.
    - If a sentence contains anchors, cut at anchor positions.
    """
    raw = str(text).strip()
    if not raw:
        return []

    sentences = re.split(r"(?<=[.!?])\s+", raw)

    segments: List[str] = []
    for sent in sentences:
        s = sent.strip()
        if not s:
            continue

        matches = list(ANCHOR_RE.finditer(s))
        if matches:
            cuts = [m.start() for m in matches] + [len(s)]
            for i in range(len(matches)):
                part = s[cuts[i]:cuts[i + 1]].strip()
                if part:
                    segments.append(part)
        else:
            segments.append(s)

    out: List[str] = []
    seen = set()
    for seg in segments:
        k = seg.lower()
        if k not in seen:
            seen.add(k)
            out.append(seg)
    return out


def _weekday_regex(token: str) -> str:
    t = re.escape(normalize_text(token))
    # allow plural "Mondays" for English weekday tokens
    if normalize_text(token) in {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}:
        return rf"\b{t}s?\b"
    return rf"\b{t}\b"


def extract_weekdays(text: str) -> List[str]:
    """
    Extract weekdays from free text, preserving order of appearance.
    Also supports weekday ranges like "monday to friday" / "martes a viernes" / "montag bis freitag".
    """
    t = normalize_text(text)

    found_positions: List[Tuple[int, str]] = []
    for token, norm in WEEKDAYS.items():
        m = re.search(_weekday_regex(token), t)
        if m:
            found_positions.append((m.start(), norm))
    found_positions.sort(key=lambda x: x[0])

    found = [n for _, n in found_positions]
    if not found:
        return []

    range_match = re.search(
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo|"
        r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b"
        r"\s*(?:to|until|till|a|hasta|bis|–|-)\s*"
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo|"
        r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b",
        t
    )

    if range_match:
        a_raw, b_raw = range_match.group(1), range_match.group(2)
        a = WEEKDAYS.get(normalize_text(a_raw), None)
        b = WEEKDAYS.get(normalize_text(b_raw), None)
        if a in WEEKDAY_ORDER and b in WEEKDAY_ORDER:
            ia, ib = WEEKDAY_ORDER.index(a), WEEKDAY_ORDER.index(b)
            if ia <= ib:
                return WEEKDAY_ORDER[ia:ib + 1]
            return WEEKDAY_ORDER[ia:] + WEEKDAY_ORDER[:ib + 1]

    out: List[str] = []
    for d in found:
        if d not in out:
            out.append(d)
    return out


def extract_time_range(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract "HH:MM - HH:MM" (or "HH:MM–HH:MM") from text.
    Returns (start, end) normalized to zero-padded HH:MM.
    """
    m = TIME_RANGE_RE.search(str(text))
    if not m:
        return None, None
    s, e = m.group(1), m.group(2)

    def norm(t: str) -> str:
        h, mm = t.split(":")
        return f"{int(h):02d}:{mm}"

    return norm(s), norm(e)


# ============================================================
# Subgroup helpers (structure heterogeneity)
# ============================================================

POSTCODE_ANY_RE = re.compile(r"\b(\d{4,6})\b")
COUNTRY_PAREN_RE = re.compile(r"\(([A-Z]{2})\)")


def normalize_country(value: Any) -> Any:
    """Normalize a country value to a 2-letter code when obvious, otherwise return as-is."""
    if not isinstance(value, str):
        return value
    v = value.strip()
    if len(v) == 2 and v.isalpha():
        return v.upper()

    # Small, language-agnostic-ish mapping for common country names (optional but useful)
    low = v.lower()
    mapping = {
        "austria": "AT", "österreich": "AT", "osterreich": "AT",
        "spain": "ES", "españa": "ES", "espana": "ES",
        "germany": "DE", "deutschland": "DE",
    }
    return mapping.get(low, v)


def _norm_key(k: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(k).lower())


def merge_list_unique(dst: List[Any], src: List[Any]) -> List[Any]:
    """Merge lists while preserving uniqueness."""
    seen = set(str(x) for x in dst)
    out = list(dst)
    for x in src:
        k = str(x)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def ensure_location_obj(existing: Any) -> Dict[str, Any]:
    """Ensure schema:location is represented as a PostalAddress object."""
    if isinstance(existing, dict):
        existing.setdefault("@type", "schema:PostalAddress")
        return existing
    return {"@type": "schema:PostalAddress"}


def parse_contact_point(text: str) -> Dict[str, Any]:
    """Parse a contact string into a schema:ContactPoint (generic, deterministic)."""
    s = str(text).strip()

    email = None
    phone = None

    m = EMAIL_RE.search(s)
    if m:
        email = m.group(0)

    p = PHONE_RE.search(s)
    if p:
        phone = p.group(1).strip()

    # Remove extracted email/phone from the working string
    work = s
    if email:
        work = work.replace(email, " ")
    if phone:
        work = work.replace(phone, " ")

    # Remove common labels (generic; do NOT hardcode platform field names)
    work = re.sub(
        r"\b(contact|email|e-mail|mail|phone|tel|telephone|mobile|móvil)\b\s*:?",
        " ",
        work,
        flags=re.IGNORECASE,
    )
    work = re.sub(r"\s+", " ", work).strip()

    # If string contains a comma, it is often "Name, role"
    head = work.split(",", 1)[0].strip()

    # Try to find a plausible person name: 2-4 capitalized tokens, allow accents/hyphens
    name = None
    name_match = re.search(
        r"\b([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+(?:[-\s][A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+){1,3})\b",
        head,
    )
    if name_match:
        candidate = name_match.group(1).strip()
        # Avoid garbage labels becoming a name
        if not re.search(r"\b(email|phone|tel|telephone|contact)\b", candidate, re.IGNORECASE):
            name = candidate

    # Fallback: use the cleaned head if it doesn't look like a label soup
    if not name:
        cleaned = re.sub(r"[;:\-–—\.]+", " ", head).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if cleaned and len(cleaned) <= 60 and not re.search(r"\b(email|phone|tel|telephone|contact)\b", cleaned, re.IGNORECASE):
            name = cleaned

    cp: Dict[str, Any] = {"@type": "schema:ContactPoint"}
    if name:
        cp["schema:name"] = name
    if email:
        cp["schema:email"] = email
    if phone:
        cp["schema:telephone"] = phone
    return cp


def merge_contact_points(existing: Optional[Dict[str, Any]], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two schema:ContactPoint objects without overwriting good data."""
    if not isinstance(existing, dict):
        existing = {"@type": "schema:ContactPoint"}
    existing.setdefault("@type", "schema:ContactPoint")

    for k in ("schema:name", "schema:email", "schema:telephone"):
        if existing.get(k) in (None, "", [], {}, ()):
            if incoming.get(k) not in (None, "", [], {}, ()):
                existing[k] = incoming[k]
    return existing


def construct_postal_address_from_sources(payload: Dict[str, Any], sources: List[str]) -> Dict[str, Any]:
    """
    Construct schema:PostalAddress from multiple source fields that mapped to schema:address.

    Strategy (deterministic):
      - Collect all chunks (flatten lists).
      - Try to detect postal code (4-6 digits) and country code ("(ES)" etc.) from ANY chunk.
      - Use key hints only in a generic way (contains 'city', 'country', 'street', 'address', ...).
      - If we still can't place some parts, keep them in schema:streetAddress so we never lose information.
    """
    addr: Dict[str, Any] = {"@type": "schema:PostalAddress"}

    chunks: List[str] = []
    keyed_chunks: List[Tuple[str, str]] = []

    def add_chunk(src: str, x: Any) -> None:
        if x in (None, "", [], {}, ()):
            return
        if isinstance(x, str):
            t = x.strip()
        else:
            t = str(x).strip()
        if t:
            chunks.append(t)
            keyed_chunks.append((src, t))

    for src in sources:
        v = payload.get(src)
        if v in (None, "", [], {}, ()):
            continue
        if isinstance(v, (list, tuple, set)):
            for item in v:
                add_chunk(src, item)
        else:
            add_chunk(src, v)

    if not chunks:
        return addr

    # postalCode + country from chunks
    for src, t in keyed_chunks:
        if "schema:postalCode" not in addr:
            m = POSTCODE_ANY_RE.search(t)
            if m:
                addr["schema:postalCode"] = m.group(1)

        if "schema:addressCountry" not in addr:
            cm = COUNTRY_PAREN_RE.search(t)
            if cm:
                addr["schema:addressCountry"] = cm.group(1)

        if "schema:addressCountry" not in addr and "country" in _norm_key(src):
            addr["schema:addressCountry"] = normalize_country(t)

    # also accept obvious country names as standalone chunks
    if "schema:addressCountry" not in addr:
        for t in chunks:
            c = normalize_country(t)
            if isinstance(c, str) and len(c) == 2 and c.isalpha():
                addr["schema:addressCountry"] = c
                break

    # locality from key hints first
    if "schema:addressLocality" not in addr:
        for src, t in keyed_chunks:
            nk = _norm_key(src)
            if "city" in nk or "locality" in nk or "town" in nk or "municipality" in nk:
                city = re.sub(r"\s*\([A-Z]{2}\)\s*$", "", t).strip()
                if city:
                    addr["schema:addressLocality"] = city
                    break

    # heuristic locality fallback: choose a non-numeric, non-country chunk
    if "schema:addressLocality" not in addr:
        country = addr.get("schema:addressCountry")
        for t in chunks:
            if POSTCODE_ANY_RE.fullmatch(t.strip()):
                continue
            if isinstance(country, str) and t.strip().upper() == country.upper():
                continue
            if len(t.strip()) < 3:
                continue
            addr["schema:addressLocality"] = t.strip()
            break

    # streetAddress: prefer street/address keys; else keep ALL chunks to avoid loss
    street_parts: List[str] = []
    for src, t in keyed_chunks:
        nk = _norm_key(src)
        if "street" in nk or "address" in nk:
            street_parts.append(t)

    if street_parts:
        addr["schema:streetAddress"] = ", ".join(street_parts).strip()
    else:
        addr["schema:streetAddress"] = ", ".join(chunks).strip()

    if "schema:addressCountry" in addr:
        addr["schema:addressCountry"] = normalize_country(addr["schema:addressCountry"])

    return addr


def construct_availability_from_sources(payload: Dict[str, Any], sources: List[str]) -> Dict[str, Any]:
    """Construct vms:VolunteerAvailability from multiple source fields that mapped to vms:availability."""
    out: Dict[str, Any] = {"@type": "vms:VolunteerAvailability"}

    for src in sources:
        v = payload.get(src)
        if v in (None, "", [], {}, ()):
            continue
        nk = _norm_key(src)

        # days
        if ("day" in nk or "weekday" in nk) and "vms:daysOfWeek" not in out:
            if isinstance(v, (list, tuple, set)):
                out["vms:daysOfWeek"] = [str(x).strip() for x in v if str(x).strip()]
            elif isinstance(v, str):
                out["vms:daysOfWeek"] = extract_weekdays(v)

        # start time
        if ("start" in nk and "time" in nk) and "vms:startTime" not in out:
            if isinstance(v, str) and TIME_RE.match(v.strip()):
                out["vms:startTime"] = v.strip()

        # end time
        if ("end" in nk and "time" in nk) and "vms:endTime" not in out:
            if isinstance(v, str) and TIME_RE.match(v.strip()):
                out["vms:endTime"] = v.strip()

    return out

def _default_for_expected_type(expected_type: str) -> Any:
    t = (expected_type or "").lower()

    # Lists
    if "list" in t:
        return []
    if t in ("idlist",):
        return []
    if t in ("textlist",):
        return []

    # Objects / nested
    if t in ("object", "postaladdress", "contactpoint", "organization"):
        return None  # keep null unless you want {}. (I recommend null for "no data")

    # Scalars
    if t in ("text", "string", "date", "time", "integer", "number", "uri"):
        return None

    # Fallback
    return None


def finalize_and_order_canonical(out: Dict[str, Any], *, entity: str) -> Dict[str, Any]:
    """
    - Ensure all canonical properties exist (typed defaults)
    - Ensure forbidden top-level keys are not present (e.g., schema:contactPoint)
    - Return a NEW dict with stable ordering matching the thesis
    """
    from schema_mapping_common.data_structures import get_canonical_properties

    # 1) Fill missing canonical properties
    for p in get_canonical_properties(entity):
        out.setdefault(p.key, _default_for_expected_type(p.expected_type))

    # 2) Remove forbidden top-level keys (contactPoint must be nested)
    for k in FORBIDDEN_TOPLEVEL_KEYS:
        if k in out:
            out.pop(k, None)

    # 3) Build ordered output
    if entity == "Volunteer":
        order = ORDER_VOLUNTEER
    elif entity == "Opportunity":
        order = ORDER_OPPORTUNITY
    else:
        order = ["@context", "@type", "@id"]  # fallback

    ordered: Dict[str, Any] = {}
    for k in order:
        if k in out:
            ordered[k] = out.get(k)

    # 4) Append remaining keys not in the order list (keeps backward compatibility)
    for k, v in out.items():
        if k not in ordered:
            ordered[k] = v

    return ordered
