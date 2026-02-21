
import re
import json
from typing import Any, Dict, List, Tuple, Optional
from difflib import SequenceMatcher
from pathlib import Path

from schema_mapping_common.data_structures import CandidateScore, CanonicalProperty, get_canonical_properties

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
ADDRESS_LINE_RE = re.compile(
    r"^\s*(?P<street>[^,]+?)\s*,\s*(?P<postcode>\d{4,6})\s+(?P<city>[^,]+?)\s*(?:,\s*(?P<country>[^,]+))?\s*$"
)
def parse_place_and_address(raw: str) -> Dict[str, Any]:

    s = str(raw or "").strip()
    place = {"@type": "schema:Place", "schema:address": {"@type": "schema:PostalAddress"}}
    if not s:
        return place

    if "(" in s and ")" in s and len(s) <= 120:
        place["schema:name"] = s
        return place

    parsed_addr = parse_postal_address(s)
    if "schema:postalCode" in parsed_addr or "schema:streetAddress" in parsed_addr:
        place["schema:address"].update(parsed_addr)
        return place

    place["schema:name"] = s
    place["schema:address"]["schema:streetAddress"] = s
    return place


def parse_postal_address(line: str, *, debug: bool = False) -> Dict[str, str]:
    s = str(line).strip()
    if not s:
        if debug:
            print("[LOCATION-PARSE] empty input")
        return {}

    m = ADDRESS_LINE_RE.match(s)
    if not m:
        if debug:
            print(f"[LOCATION-PARSE] no regex match -> fallback addressLocality={s!r}")
        return {"schema:streetAddress": s}

    street = (m.group("street") or "").strip()
    postcode = (m.group("postcode") or "").strip()
    city = (m.group("city") or "").strip()
    country = (m.group("country") or "").strip()

    out = {}
    if street:
        out["schema:streetAddress"] = street
    if postcode:
        out["schema:postalCode"] = postcode
    if city:
        out["schema:addressLocality"] = city
    if country:
        out["schema:addressCountry"] = country

    if debug:
        print("[LOCATION-PARSE] matched regex")
        print("  streetAddress =", street)
        print("  postalCode    =", postcode)
        print("  locality      =", city)
        print("  country       =", country)

    return out


FORBIDDEN_TOPLEVEL_KEYS = {"schema:contactPoint"}

CAMEL_BREAK_RE = re.compile(r"([a-z])([A-Z])")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
TIME_RANGE_RE = re.compile(r"\b(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\b")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{6,}\d)")

POSTAL_RE = re.compile(r"\b\d{4,6}\b")  # 4040, 10115, 28013, etc.
STREET_WORD_RE = re.compile(r"\b(straße|strasse|street|st\.|road|rd\.|avenue|ave\.|platz|plaza|calle|carrer|via)\b", re.I)
URL_RE = re.compile(r"https?://|www\.", re.I)

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
    base = Path(__file__).resolve().parent
    path = base / rel_path
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_text(
    s: str,
    *,
    keep_colon: bool = True,
) -> str:

    s = str(s).strip()

    s = CAMEL_BREAK_RE.sub(r"\1 \2", s)

    s = s.lower()

    allowed = r"[^a-z0-9\s:]+" if keep_colon else r"[^a-z0-9\s]+"
    s = re.sub(allowed, " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def tokenize(s: str) -> List[str]:
    return [t for t in normalize_text(s).split() if t]


def flatten_payload(payload: Dict[str, Any], prefix: str = "") -> List[Tuple[str, Any]]:

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
    if isinstance(example, (list, tuple, set)):
        ex = ", ".join(map(str, list(example)[:5]))
    else:
        ex = str(example)
    ex = ex[:260]
    return f"field:{path} example:{ex}"


def lexical_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def decide_mapping(
    ranked: List[CandidateScore],
    tau: float,
    margin: float,
) -> Tuple[str, Optional[CanonicalProperty], str]:

    if not ranked:
        return "REJECTED", None, "no candidates"

    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None

    if best.combined < tau:
        return "REJECTED", None, f"below tau={tau:.2f}"

    if second is None or (best.combined - second.combined) >= margin:
        return "ACCEPTED", best.candidate, f"margin >= {margin:.2f}"

    return "AMBIGUOUS", best.candidate, "LLM activated:"


def split_into_segments(text: str) -> List[str]:
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
    if normalize_text(token) in {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}:
        return rf"\b{t}s?\b"
    return rf"\b{t}\b"


def extract_weekdays(text: str) -> List[str]:
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

    m = TIME_RANGE_RE.search(str(text))
    if not m:
        return None, None
    s, e = m.group(1), m.group(2)

    def norm(t: str) -> str:
        h, mm = t.split(":")
        return f"{int(h):02d}:{mm}"

    return norm(s), norm(e)

POSTCODE_ANY_RE = re.compile(r"\b(\d{4,6})\b")
COUNTRY_PAREN_RE = re.compile(r"\(([A-Z]{2})\)")


def normalize_country(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    v = value.strip()
    if len(v) == 2 and v.isalpha():
        return v.upper()

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
    seen = set(str(x) for x in dst)
    out = list(dst)
    for x in src:
        k = str(x)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def ensure_location_obj(existing: Any) -> Dict[str, Any]:
    if isinstance(existing, dict):
        existing.setdefault("@type", "schema:Place")
        addr = existing.get("schema:address")
        if not isinstance(addr, dict):
            existing["schema:address"] = {"@type": "schema:PostalAddress"}
        else:
            addr.setdefault("@type", "schema:PostalAddress")
        return existing

    return {
        "@type": "schema:Place",
        "schema:address": {"@type": "schema:PostalAddress"},
    }


def parse_contact_point(text: str, *, debug: bool = False, source: str = "") -> Dict[str, Any]:
    s = str(text).strip()

    prefix = "[CP]"
    if source:
        prefix += f"[{source}]"

    if debug:
        print(f"{prefix} raw={text!r} normalized={s!r}")

    email = None
    phone = None

    m = EMAIL_RE.search(s)
    if m:
        email = m.group(0)
        if debug:
            print(f"{prefix} EMAIL_RE matched -> {email!r}")
    elif debug:
        print(f"{prefix} EMAIL_RE no match")

    p = PHONE_RE.search(s)
    if p:
        phone = p.group(1).strip()
        if debug:
            print(f"{prefix} PHONE_RE matched -> {phone!r}")
    elif debug:
        print(f"{prefix} PHONE_RE no match")

    work = s
    if email:
        work = work.replace(email, " ")
    if phone:
        work = work.replace(phone, " ")

    if debug:
        print(f"{prefix} after removing email/phone -> {work!r}")

    work2 = re.sub(
        r"\b(contact|email|e-mail|mail|phone|tel|telephone|mobile|móvil)\b\s*:?",
        " ",
        work,
        flags=re.IGNORECASE,
    )
    work2 = re.sub(r"\s+", " ", work2).strip()

    if debug:
        print(f"{prefix} after removing labels -> {work2!r}")

    head = work2.split(",", 1)[0].strip()
    if debug:
        print(f"{prefix} head candidate (pre-name-heuristic) -> {head!r}")

    name = None
    name_match = re.search(
        r"\b([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+(?:[-\s][A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+){1,3})\b",
        head,
    )
    if name_match:
        candidate = name_match.group(1).strip()
        if not re.search(r"\b(email|phone|tel|telephone|contact)\b", candidate, re.IGNORECASE):
            name = candidate
            if debug:
                print(f"{prefix} name heuristic MATCH -> {name!r}")
        elif debug:
            print(f"{prefix} name heuristic produced label-like candidate -> {candidate!r} (ignored)")
    elif debug:
        print(f"{prefix} name heuristic NO MATCH")

    if not name:
        cleaned = re.sub(r"[;:\-–—\.]+", " ", head).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if cleaned and len(cleaned) <= 60 and not re.search(r"\b(email|phone|tel|telephone|contact)\b", cleaned, re.IGNORECASE):
            name = cleaned
            if debug:
                print(f"{prefix} fallback name -> {name!r}")
        elif debug:
            print(f"{prefix} fallback name not used (cleaned={cleaned!r})")

    cp: Dict[str, Any] = {"@type": "schema:ContactPoint"}
    if name:
        cp["schema:name"] = name
    if email:
        cp["schema:email"] = email
    if phone:
        cp["schema:telephone"] = phone

    if debug:
        print(f"{prefix} result -> {cp}")

    return cp


def merge_contact_points(existing: Optional[Dict[str, Any]], incoming: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(existing, dict):
        existing = {"@type": "schema:ContactPoint"}
    existing.setdefault("@type", "schema:ContactPoint")

    for k in ("schema:name", "schema:email", "schema:telephone"):
        if existing.get(k) in (None, "", [], {}, ()):
            if incoming.get(k) not in (None, "", [], {}, ()):
                existing[k] = incoming[k]
    return existing


def construct_postal_address_from_sources(payload: Dict[str, Any], sources: List[str]) -> Dict[str, Any]:
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

    if "schema:addressCountry" not in addr:
        for t in chunks:
            c = normalize_country(t)
            if isinstance(c, str) and len(c) == 2 and c.isalpha():
                addr["schema:addressCountry"] = c
                break

    if "schema:addressLocality" not in addr:
        for src, t in keyed_chunks:
            nk = _norm_key(src)
            if "city" in nk or "locality" in nk or "town" in nk or "municipality" in nk:
                city = re.sub(r"\s*\([A-Z]{2}\)\s*$", "", t).strip()
                if city:
                    addr["schema:addressLocality"] = city
                    break

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
    out: Dict[str, Any] = {"@type": "vms:VolunteerAvailability"}

    for src in sources:
        v = payload.get(src)
        if v in (None, "", [], {}, ()):
            continue
        nk = _norm_key(src)

        if ("day" in nk or "weekday" in nk) and "vms:daysOfWeek" not in out:
            if isinstance(v, (list, tuple, set)):
                out["vms:daysOfWeek"] = [str(x).strip() for x in v if str(x).strip()]
            elif isinstance(v, str):
                out["vms:daysOfWeek"] = extract_weekdays(v)

        if ("start" in nk and "time" in nk) and "vms:startTime" not in out:
            if isinstance(v, str) and TIME_RE.match(v.strip()):
                out["vms:startTime"] = v.strip()

        if ("end" in nk and "time" in nk) and "vms:endTime" not in out:
            if isinstance(v, str) and TIME_RE.match(v.strip()):
                out["vms:endTime"] = v.strip()

    return out

def _default_for_expected_type(expected_type: str) -> Any:
    t = (expected_type or "").lower()

    if "list" in t:
        return []
    if t in ("idlist",):
        return []
    if t in ("textlist",):
        return []

    if t in ("object", "postaladdress", "contactpoint", "organization"):
        return None  # keep null unless you want {}. (I recommend null for "no data")

    if t in ("text", "string", "date", "time", "integer", "number", "uri"):
        return None

    return None


def finalize_and_order_canonical(out: Dict[str, Any], *, entity: str) -> Dict[str, Any]:

    from schema_mapping_common.data_structures import get_canonical_properties

    for p in get_canonical_properties(entity):
        out.setdefault(p.key, _default_for_expected_type(p.expected_type))

    for k in FORBIDDEN_TOPLEVEL_KEYS:
        if k in out:
            out.pop(k, None)

    if entity == "Volunteer":
        order = ORDER_VOLUNTEER
    elif entity == "Opportunity":
        order = ORDER_OPPORTUNITY
    else:
        order = ["@context", "@type", "@id"]

    ordered: Dict[str, Any] = {}
    for k in order:
        if k in out:
            ordered[k] = out.get(k)

    for k, v in out.items():
        if k not in ordered:
            ordered[k] = v

    return ordered


def looks_like_address(s: str) -> bool:
    t = s.strip()
    digits = sum(ch.isdigit() for ch in t)
    has_postal = bool(POSTAL_RE.search(t))
    has_street_word = bool(STREET_WORD_RE.search(t))
    has_commas = t.count(",") >= 1
    # address-ish if: street word OR (postal + digits) OR (commas + digits)
    return has_street_word or (has_postal and digits >= 3) or (has_commas and digits >= 3)


def looks_like_contact(s: str) -> bool:
    # reuse your EMAIL_RE / PHONE_RE if already imported in scoring.py
    return bool(EMAIL_RE.search(s) or PHONE_RE.search(s) or URL_RE.search(s))