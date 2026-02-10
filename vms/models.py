# vms/models.py
import os
from itertools import cycle

from django.conf import settings
from django.db import models
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone


# --- demo images (keep your existing logic) -------------------------------
EVENT_IMAGES_PATH = os.path.join(settings.BASE_DIR, "vms", "static", "vms", "images", "events")
_event_images = []
if os.path.isdir(EVENT_IMAGES_PATH):
    _event_images = [
        f for f in os.listdir(EVENT_IMAGES_PATH)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ]
_image_cycle = cycle(_event_images)  # will loop endlessly if non-empty


# --- small helpers --------------------------------------------------------
def make_esco_uri(esco_id_or_uuid: str) -> str:
    if str(esco_id_or_uuid).startswith("http"):
        return str(esco_id_or_uuid)
    return f"http://data.europa.eu/esco/skill/{esco_id_or_uuid}"


# --- Domain models --------------------------------------------------------
class Organization(models.Model):
    """
    Prototype: Organization == Provider (same model).
    This represents a participant VMS platform / org node in the federation.
    """

    id = models.AutoField(primary_key=True)

    # Identity
    name = models.CharField(max_length=255)
    url = models.URLField(blank=True, default="")

    # Portal/UX fields (landing page cards)
    short_description = models.CharField(max_length=180, blank=True, default="")
    country = models.CharField(max_length=2, blank=True, default="")  # e.g., "AT", "ES"
    focus_tags = models.JSONField(blank=True, default=list, encoder=DjangoJSONEncoder)  # ["Health", "Environment"]

    # Platform keys / profile
    # Keep optional to avoid dev migration pain; seed will set it.
    platform_key = models.SlugField(max_length=80, unique=True, null=True, blank=True)  # "mima", "volgistics", ...
    platform_vendor = models.CharField(max_length=120, blank=True, default="")
    interop_profile = models.CharField(max_length=120, blank=True, default="")

    # Governance / membership flags
    member_ds = models.BooleanField(default=False)
    is_dsga = models.BooleanField(default=False)

    # Core onboarding metadata
    contact_email = models.EmailField(blank=True, default="")
    connector_endpoint = models.URLField(blank=True, default="")  # can act as discovery/interop entrypoint
    certificate_thumbprint = models.CharField(max_length=128, blank=True, default="")
    metadata_json = models.JSONField(blank=True, default=dict, encoder=DjangoJSONEncoder)

    def __str__(self):
        return self.name

    def to_jsonld(self):
        # Simple JSON-LD identity
        return {
            "@context": {"schema": "https://schema.org/", "vms": "https://vms.example.org/context#"},
            "@type": ["schema:Organization", "vms:VMSProvider"],
            "@id": f"https://vms.example.org/orgs/{self.platform_key or self.id}",
            "schema:name": self.name,
            "schema:url": self.url,
            "schema:email": self.contact_email,
            "vms:memberOfFederation": self.member_ds,
            "vms:connectorEndpoint": self.connector_endpoint,
            "vms:platformKey": self.platform_key,
            "vms:vendor": self.platform_vendor,
            "vms:interopProfile": self.interop_profile,
            "vms:tags": self.focus_tags,
            "schema:address": {"@type": "schema:PostalAddress", "schema:addressCountry": self.country} if self.country else None,
            "vms:metadata": self.metadata_json,
        }

    def portal_card(self):
        return {
            "name": self.name,
            "short_description": self.short_description,
            "country": self.country,
            "focus_tags": self.focus_tags,
            "platform_vendor": self.platform_vendor,
            "interop_profile": self.interop_profile,
            "connector_endpoint": self.connector_endpoint,
        }


class Skill(models.Model):
    """
    Represents an ESCO skill (or local skill mapped to ESCO).
    """
    id = models.AutoField(primary_key=True)
    label = models.CharField(max_length=200)
    esco_uri = models.URLField(blank=True, default="")
    description = models.TextField(blank=True, default="")

    def __str__(self):
        return self.label

    def uri(self):
        return self.esco_uri or f"https://vms.example.org/skills/{self.id}"

    def to_jsonld(self):
        if self.esco_uri:
            return {"@id": self.esco_uri}
        return {"@id": self.uri(), "name": self.label, "description": self.description}


class Volunteer(models.Model):
    """
    Internal/demo volunteer representation (Demorg local user).
    External providers’ volunteers should go into LocalResource payloads.
    """
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=250)
    password = models.CharField(max_length=128, default="admin")  # prototype-only
    location = models.CharField(max_length=200, blank=True, default="")
    availability_preference = models.TextField(blank=True, default="")
    available_hours_per_week = models.IntegerField(blank=True, default=0)

    is_manager = models.BooleanField(default=False)

    organization = models.ForeignKey(
        Organization, related_name="volunteers",
        on_delete=models.CASCADE, null=True, blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    skills = models.ManyToManyField(Skill, blank=True, related_name="volunteers")
    events = models.ManyToManyField("VolunteerEvent", blank=True, related_name="volunteers")



    def total_hours(self):
        return sum(e.duration_hours for e in self.events.all())

    def __str__(self):
        return f"{self.name}"

    def skills_list(self):
        return [s.label for s in self.skills.all()]

    def to_jsonld(self):
        ctx = {
            "@context": {
                "schema": "https://schema.org/",
                "esco": "http://data.europa.eu/esco/",
                "vms": "https://vms.example.org/context#"
            }
        }
        skills_jsonld = [{"@type": "schema:DefinedTerm", "@id": s.esco_uri or s.uri(), "schema:name": s.label,
                          "schema:inDefinedTermSet": "https://ec.europa.eu/esco"} for s in self.skills.all()]

        doc = {
            **ctx,
            "@type": ["schema:Person", "vms:Volunteer"],
            "@id": f"https://vms.example.org/people/{self.id}",
            "schema:name": self.name,
            "schema:location": self.location,
            "schema:memberOf": {"@id": f"https://vms.example.org/orgs/{self.organization.platform_key or self.organization.id}"} if self.organization else None,
            "vms:availability": {
                "@type": "vms:VolunteerAvailability",
                "vms:daysOfWeek": ["Saturday", "Sunday"],
                "vms:startTime": "09:00",
                "vms:endTime": "18:00",
            } if self.availability_preference else None,
            "schema:skills": skills_jsonld,
        }
        return doc


class VolunteerEvent(models.Model):
    """
    Internal/demo event representation (Demorg local).
    External providers’ opportunities should go into CanonicalResource + LocalResource payloads.
    """
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=250)
    description = models.TextField(blank=True, default="")
    duration_hours = models.IntegerField(default=1)
    location = models.CharField(max_length=250, blank=True, default="")
    skills = models.ManyToManyField(Skill, blank=True, related_name="events")

    organization = models.ForeignKey(
        Organization, related_name="events",
        on_delete=models.CASCADE, null=True, blank=True
    )

    isShared = models.BooleanField(default=True)
    isFinished = models.BooleanField(default=False)

    prioritize_local = models.BooleanField(default=False)
    shared_since = models.DateTimeField(null=True, blank=True)
    ds_endpoint = models.CharField(blank=True, default="")
    ds_asset_id = models.CharField(max_length=64, blank=True, default="")
    ds_contract_id = models.CharField(max_length=64, blank=True, default="")

    # cache marker + traceability (for federated cache)
    is_federated_cache = models.BooleanField(default=False)
    source_entity_type = models.CharField(max_length=20, blank=True, default="")  # "OPPORTUNITY"
    source_local_id = models.CharField(max_length=128, blank=True, default="")  # provider's local id

    # canonical JSON-LD cache
    canonical_jsonld = models.JSONField(blank=True, default=dict, encoder=DjangoJSONEncoder)

    image = models.CharField(max_length=250, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "is_federated_cache", "source_entity_type", "source_local_id"],
                name="uniq_federated_cache_event"
            )
        ]

    @property
    def image_url(self):
        if self.image:
            return f"vms/images/events/{self.image}"
        return "vms/images/events/default.jpg"

    def to_jsonld(self):
        if self.canonical_jsonld:
            return self.canonical_jsonld

        doc = {
            "@context": {"schema": "https://schema.org/", "vms": "https://vms.example.org/context#"},
            "@type": ["schema:Event", "vms:Opportunity"],
            "@id": f"https://vms.example.org/opportunities/{self.id}",
            "schema:name": self.name,
        }
        if self.description:
            doc["schema:description"] = self.description
        if self.location:
            doc["schema:location"] = {"@type": "schema:PostalAddress", "schema:addressLocality": self.location}
        if self.organization:
            doc["schema:organizer"] = {"@type": "schema:Organization", "schema:name": self.organization.name}
        return doc

    def save(self, *args, **kwargs):
        if not self.image and _event_images:
            try:
                self.image = next(_image_cycle)
            except StopIteration:
                pass
        super().save(*args, **kwargs)


class Certificate(models.Model):
    id = models.AutoField(primary_key=True)
    volunteer = models.ForeignKey(Volunteer, on_delete=models.CASCADE)
    issued_at = models.DateTimeField(auto_now_add=True)
    issuer = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.SET_NULL)
    items = models.JSONField(blank=True, default=list, encoder=DjangoJSONEncoder)
    proof_hash = models.CharField(max_length=128, blank=True, default="")
    skills = models.ManyToManyField(Skill, blank=True, related_name="certificates")

    def __str__(self):
        return f"Cert {self.id} for {self.volunteer.name}"

    def to_jsonld(self):
        doc = {
            "@context": {"schema": "https://schema.org/", "vms": "https://vms.example.org/context#"},
            "@type": "schema:EducationalOccupationalCredential",
            "@id": f"https://vms.example.org/certs/{self.id}",
            "schema:name": f"Volunteer Certificate {self.id}",
            "vms:issuedTo": {"@id": f"https://vms.example.org/people/{self.volunteer.id}"},
            "schema:dateIssued": self.issued_at.date().isoformat(),
            "vms:items": self.items,
            "vms:proofHash": self.proof_hash,
        }
        if self.issuer:
            doc["schema:recognizedBy"] = {"@id": f"https://vms.example.org/orgs/{self.issuer.platform_key or self.issuer.id}",
                                          "schema:name": self.issuer.name}
        skills = [{"@id": s.esco_uri or s.uri(), "schema:name": s.label} for s in self.skills.all()]
        if skills:
            doc["schema:skills"] = skills
        return doc


class LogEntry(models.Model):
    LEVEL_CHOICES = [
        ("INFO", "INFO"),
        ("WARN", "WARN"),
        ("ERROR", "ERROR"),
        ("DEBUG", "DEBUG"),
    ]
    id = models.AutoField(primary_key=True)
    timestamp = models.DateTimeField(default=timezone.now)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default="INFO")
    action = models.CharField(max_length=200)
    details = models.TextField(blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"[{self.timestamp.isoformat()}] {self.level} {self.action}"


# --- Heterogeneous local payloads -----------------------------------------
class LocalResource(models.Model):
    """
    Stores raw objects coming from each Organization in their *local* schema.
    """
    ENTITY_CHOICES = [
        ("VOLUNTEER", "Volunteer"),
        ("OPPORTUNITY", "Opportunity"),
        ("EVENT", "Event"),
    ]

    id = models.AutoField(primary_key=True)

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="local_resources"
    )

    entity_type = models.CharField(max_length=20, choices=ENTITY_CHOICES)
    local_id = models.CharField(max_length=128)

    payload = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    retrieved_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("organization", "entity_type", "local_id")]
        ordering = ["-retrieved_at"]

    def __str__(self):
        key = self.organization.platform_key or str(self.organization.id)
        return f"{key}:{self.entity_type}:{self.local_id}"


class CanonicalResource(models.Model):
    """
    Stores canonical JSON-LD resources (what Demorg sees in federated results).
    """
    ENTITY_CHOICES = LocalResource.ENTITY_CHOICES

    id = models.AutoField(primary_key=True)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="canonical_resources"
    )
    entity_type = models.CharField(max_length=20, choices=ENTITY_CHOICES)

    local_resource = models.OneToOneField(
        LocalResource, on_delete=models.CASCADE,
        null=True, blank=True, related_name="canonical"
    )

    canonical_id = models.CharField(max_length=255, blank=True, default="")
    canonical_jsonld = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        key = self.organization.platform_key or str(self.organization.id)
        return f"canonical:{key}:{self.entity_type}:{self.id}"


class MappingCatalog(models.Model):
    ENTITY_CHOICES = [
        ("VOLUNTEER", "Volunteer"),
        ("OPPORTUNITY", "Opportunity"),
    ]

    id = models.AutoField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="mapping_catalogs")
    entity_type = models.CharField(max_length=20, choices=ENTITY_CHOICES)

    catalog_json = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    validated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("organization", "entity_type")]

    def __str__(self):
        key = self.organization.platform_key or str(self.organization.id)
        return f"MappingCatalog({key},{self.entity_type})"
