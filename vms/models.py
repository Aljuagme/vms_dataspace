import random
from django.db import models
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone


class Organization(models.Model):

    id = models.AutoField(primary_key=True)

    name = models.CharField(max_length=255)
    url = models.URLField(blank=True, default="")

    short_description = models.CharField(max_length=180, blank=True, default="")
    country = models.CharField(max_length=2, blank=True, default="")  # e.g., "AT", "ES"
    focus_tags = models.JSONField(blank=True, default=list, encoder=DjangoJSONEncoder)

    platform_key = models.SlugField(max_length=80, unique=True, null=True, blank=True)  # "mima", "volgistics", ...
    platform_vendor = models.CharField(max_length=120, blank=True, default="")
    interop_profile = models.CharField(max_length=120, blank=True, default="")

    member_ds = models.BooleanField(default=False)
    is_dsga = models.BooleanField(default=False)

    contact_email = models.EmailField(blank=True, default="")
    connector_endpoint = models.URLField(blank=True, default="")
    certificate_thumbprint = models.CharField(max_length=128, blank=True, default="")

    self_description_jsonld = models.JSONField(blank=True, default=dict, encoder=DjangoJSONEncoder)


    mapping_catalogs_jsonld = models.JSONField(blank=True, default=dict, encoder=DjangoJSONEncoder)

    def __str__(self):
        return self.name

    def get_self_description_doc(self) -> dict:

        blob = self.self_description_jsonld or {}
        doc = blob.get("doc")

        if not (isinstance(doc, dict) and doc.get("@type") and doc.get("name")):
            doc = {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": self.name,
                "identifier": self.platform_key or str(self.id),
            }

        if self.url:
            doc["url"] = self.url

        if self.connector_endpoint:
            doc["connectorUrl"] = self.connector_endpoint

        if self.contact_email:
            doc["email"] = self.contact_email



        return doc

    def set_self_description_doc(self, doc: dict) -> None:
        blob = self.self_description_jsonld or {}
        blob["doc"] = doc
        self.self_description_jsonld = blob

    def to_jsonld(self) -> dict:

        pk = self.platform_key or str(self.id)
        doc = {
            "@context": {
                "schema": "https://schema.org/",
                "vms": "https://vms.example.org/context#",
            },
            "@type": ["schema:Organization", "vms:VMSProvider"],
            "@id": f"https://vms.example.org/orgs/{pk}",
            "schema:name": self.name,
            "schema:url": self.url or None,
            "schema:email": self.contact_email or None,
            "vms:memberOfFederation": bool(self.member_ds),
            "vms:connectorEndpoint": self.connector_endpoint or None,
            "vms:platformKey": self.platform_key or None,
            "vms:vendor": self.platform_vendor or None,
            "vms:interopProfile": self.interop_profile or None,
            "vms:tags": self.focus_tags or [],
            "schema:address": (
                {"@type": "schema:PostalAddress", "schema:addressCountry": self.country}
                if self.country else None
            ),
        }
        return {k: v for k, v in doc.items() if v is not None}

    def get_mapping_state(self, entity: str) -> dict:
        mc = self.mapping_catalogs_jsonld or {}
        return mc.get(entity) or {}

    def set_mapping_state(self, entity: str, state: dict) -> None:
        mc = self.mapping_catalogs_jsonld or {}
        mc[entity] = state
        self.mapping_catalogs_jsonld = mc


class VolunteerEvent(models.Model):

    id = models.AutoField(primary_key=True)

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="events",
    )

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    location = models.CharField(max_length=255, blank=True, default="")
    duration_hours = models.IntegerField(default=1)
    max_attendee_capacity = models.IntegerField(default=0)
    tshirt_size = models.CharField(max_length=10, blank=True, default="")

    image_url = models.CharField(max_length=255, blank=True, default="")

    DEMORG_EVENT_IMAGES = [
        "vms/images/events/beach.jpg",
        "vms/images/events/explanation_volunteer.jpg",
        "vms/images/events/fire_brigade.jpg",
        "vms/images/events/food_cook.jpg",
        "vms/images/events/food_well.jpg",
        "vms/images/events/hands_lake.jpg",
        "vms/images/events/karate.jpg",
        "vms/images/events/kitchen.jpg",
        "vms/images/events/water_river.jpg",
    ]

    def assign_random_image_if_missing(self):
        if not self.image_url:
            self.image_url = random.choice(self.DEMORG_EVENT_IMAGES)

    def save(self, *args, **kwargs):
        if self.organization and self.organization.platform_key == "demorg":
            self.assign_random_image_if_missing()
        super().save(*args, **kwargs)

    skills = models.JSONField(blank=True, default=list, encoder=DjangoJSONEncoder)

    isShared = models.BooleanField(default=False)
    isFinished = models.BooleanField(default=False)

    is_federated_cache = models.BooleanField(default=False)
    source_entity_type = models.CharField(max_length=40, blank=True, default="OPPORTUNITY")
    source_local_id = models.CharField(max_length=120, blank=True, default="")

    shared_since = models.DateTimeField(null=True, blank=True)
    ds_endpoint = models.URLField(blank=True, default="")
    ds_asset_id = models.CharField(max_length=128, blank=True, default="")

    canonical_jsonld = models.JSONField(blank=True, default=dict, encoder=DjangoJSONEncoder)

    def to_jsonld_stub(self) -> dict:

        org_key = self.organization.platform_key or str(self.organization_id)
        ev_id = self.source_local_id or str(self.id)

        doc = {
            "@context": {
                "schema": "https://schema.org/",
                "vms": "https://vms.example.org/context#",
                "esco": "http://data.europa.eu/esco/skill/",
            },
            "@type": ["schema:Event", "vms:Opportunity"],
            "@id": f"https://vms.example.org/{org_key}/opportunities/{ev_id}",
            "schema:name": self.name,
            "schema:description": self.description or "",
            "schema:location": (
                {"@type": "schema:Place", "schema:name": self.location}
                if self.location else None
            ),
            "vms:durationHours": int(self.duration_hours or 1),
            "vms:visibility": "public" if self.isShared else "private",
            "vms:requiresSkill": [
                {"@type": "schema:DefinedTerm", "schema:name": s}
                for s in (self.skills or [])
                if s
            ],
            "schema:organizer": {
                "@type": "schema:Organization",
                "@id": f"https://vms.example.org/orgs/{org_key}",
                "schema:name": self.organization.name,
                "schema:url": self.organization.url or None,
            },
        }
        # strip None values (keeps JSON-LD clean)
        return {k: v for k, v in doc.items() if v is not None}


    def __str__(self):
        return f"{self.organization.platform_key}:{self.name}"

    def is_visible_in_portal(self) -> bool:
        return bool(self.isShared) and not bool(self.isFinished)


class Volunteer(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=250)
    email = models.EmailField(blank=True, default="")
    telephone = models.CharField(max_length=250, blank=True, default="")
    password = models.CharField(max_length=128, default="admin")

    location = models.CharField(max_length=200, blank=True, default="")
    availability_preference = models.TextField(blank=True, default="")
    skills = models.JSONField(blank=True, default=list, encoder=DjangoJSONEncoder)

    is_manager = models.BooleanField(default=False)
    organization = models.ForeignKey(
        "Organization", related_name="volunteers",
        on_delete=models.CASCADE, null=True, blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    events = models.ManyToManyField("VolunteerEvent", blank=True, related_name="volunteers")

    def total_hours(self):
        return sum(int(e.duration_hours if e.isFinished else 0) for e in self.events.all())


class CertificateLog(models.Model):
    volunteer = models.ForeignKey("Volunteer", on_delete=models.CASCADE, related_name="certificate_logs")
    step = models.CharField(max_length=40, default="INFO")   # DISCOVERY, CONTRACT, CALL, NORMALIZE, AGGREGATE, ISSUE
    actor = models.CharField(max_length=40, default="DEMORG")# DEMORG, DISCOVERY, CONNECTOR, VOLGISTICS
    endpoint = models.CharField(max_length=255, blank=True, default="")
    message = models.TextField(default="")
    payload = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]


class CertificateIssue(models.Model):

    id = models.AutoField(primary_key=True)
    volunteer = models.ForeignKey("Volunteer", on_delete=models.CASCADE, related_name="certificates")
    target_esco_uri = models.CharField(max_length=255, default="")
    total_hours = models.IntegerField(default=0)
    certificate_jsonld = models.JSONField(blank=True, default=dict, encoder=DjangoJSONEncoder)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]


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
    action = models.CharField(max_length=200)       # e.g., "OnboardingRequestReceived"
    details = models.TextField(blank=True)          # human-readable details or JSON string

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"[{self.timestamp.isoformat()}] {self.level} {self.action}"