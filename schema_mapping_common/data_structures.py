"""
data_structures.py
==================
Shared data structures for schema mapping.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class CanonicalProperty:
    key: str
    label: str
    description: str
    expected_type: str
    entity: str

    def signature(self) -> str:
        return f"{self.key} {self.label} {self.description} type:{self.expected_type}"


@dataclass
class CandidateScore:
    candidate: CanonicalProperty
    semantic: float
    lexical: float
    boost: float
    combined: float


@dataclass
class MappingProposal:
    source_path: str
    example: Any
    best_target: Optional[CanonicalProperty]
    status: str  # ACCEPTED | AMBIGUOUS | REJECTED | COMPOSITE
    ranked: List[CandidateScore]
    note: str = ""


@dataclass
class MappingRule:
    sources: List[str]
    target_key: str
    transform: str = "identity"
    constant: Optional[Any] = None
    slot_sources: Optional[Dict[str, List[str]]] = None


@dataclass
class MappingCatalog:
    org_id: str
    entity: str
    rules: List[MappingRule] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "org_id": self.org_id,
            "entity": self.entity,
            "rules": [r.__dict__ for r in self.rules],
        }


# Registry for all canonical properties
CANONICAL_PROPERTIES_REGISTRY: Dict[str, List[CanonicalProperty]] = {
    "Volunteer": [
        CanonicalProperty("schema:givenName", "Given name", "First name of the volunteer", "Text", "Volunteer"),
        CanonicalProperty("schema:familyName", "Family name", "Last name of the volunteer", "Text", "Volunteer"),
        CanonicalProperty("schema:email", "Email", "Contact email address", "Text", "Volunteer"),
        CanonicalProperty("schema:telephone", "Telephone", "Contact phone number", "Text", "Volunteer"),
        CanonicalProperty("schema:address", "Address", "Postal address of the volunteer", "PostalAddress", "Volunteer"),
        CanonicalProperty("schema:skills", "Skills", "Skills the volunteer can offer", "TextList", "Volunteer"),
        CanonicalProperty("vms:availability", "Availability", "Volunteer availability constraints", "Object", "Volunteer"),
    ],
    "Opportunity": [
        CanonicalProperty("schema:name", "Name", "Opportunity title", "Text", "Opportunity"),
        CanonicalProperty("schema:description", "Description", "Opportunity description / duties", "Text", "Opportunity"),
        CanonicalProperty("schema:startDate", "Start date", "Start date of the opportunity", "Date", "Opportunity"),
        CanonicalProperty("schema:endDate", "End date", "End date of the opportunity", "Date", "Opportunity"),
        CanonicalProperty("vms:startTime", "Start time", "Daily start time (hh:mm)", "Time", "Opportunity"),
        CanonicalProperty("vms:endTime", "End time", "Daily end time (hh:mm)", "Time", "Opportunity"),
        CanonicalProperty("schema:location", "Address", "Where the opportunity happens", "PostalAddress", "Opportunity"),
        CanonicalProperty("schema:organizer", "Organizer", "Organization offering the opportunity", "Organization", "Opportunity"),
        CanonicalProperty("schema:contactPoint", "Contact point", "Contact info for organizer (name/email/telephone)", "ContactPoint", "Opportunity"),
        CanonicalProperty("schema:maximumAttendeeCapacity", "Capacity", "Maximum attendee capacity", "Integer", "Opportunity"),
        CanonicalProperty("vms:daysOfWeek", "Days of week", "Days when the opportunity happens", "TextList", "Opportunity"),
        CanonicalProperty("vms:requiresSkill", "Requires skill", "Skills required to participate", "TextList", "Opportunity"),
        CanonicalProperty("vms:visibility", "Visibility", "Sharing visibility (e.g., CrossPlatform)", "Text", "Opportunity"),
    ]
}

# Helper functions to maintain backward compatibility
def get_canonical_properties(entity: str) -> List[CanonicalProperty]:
    """Get canonical properties for a specific entity."""
    return CANONICAL_PROPERTIES_REGISTRY.get(entity, [])

# Backward compatibility aliases
CANONICAL_PROPERTIES_VOLUNTEER = CANONICAL_PROPERTIES_REGISTRY["Volunteer"]
CANONICAL_PROPERTIES_OPPORTUNITY = CANONICAL_PROPERTIES_REGISTRY["Opportunity"]