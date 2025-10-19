# vms/models.py
import os
from itertools import cycle

from django.conf import settings
from django.db import models

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

EVENT_IMAGES_PATH = os.path.join(settings.BASE_DIR, "vms", "static", "vms", "images", "events")
_event_images = [
    f for f in os.listdir(EVENT_IMAGES_PATH)
    if f.lower().endswith((".jpg", ".jpeg", ".png"))
]
_image_cycle = cycle(_event_images)  # will loop endlessly

# --- Reusable small helpers -------------------------------------------------
def make_esco_uri(esco_id_or_uuid):
    # Accept either full URI or ESCO id and normalize to a data.europa.eu URI
    if str(esco_id_or_uuid).startswith("http"):
        return str(esco_id_or_uuid)
    return f"http://data.europa.eu/esco/skill/{esco_id_or_uuid}"

# --- Domain models ---------------------------------------------------------
class Organization(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    url = models.URLField(blank=True, default="")

    # Data space membership / governance
    member_ds = models.BooleanField(default=False)
    is_dsga = models.BooleanField(default=False)

    # Core onboarding metadata
    contact_email = models.EmailField(blank=True, default="")
    connector_endpoint = models.URLField(blank=True, default="")
    certificate_thumbprint = models.CharField(max_length=128, blank=True, default="")
    metadata_json = models.JSONField(blank=True, default=dict, encoder=DjangoJSONEncoder)

    # --- add local vocabularies ---
    local_volunteer_schema = {
        "name": ["schema:givenName", "schema:familyName"],
        "email_address": ["schema:email"],
        "hours_served": ["vms:totalHours"],
        "skills_list": ["schema:skills"],
        "org_membership": ["schema:memberOf"],
        "tshirt_size": ["(no mapping: dropped or additionalProperty)"],
        "birthDate": ["schema:birthDate"],
    }

    local_skill_mapping = {
        "CPR": "http://data.europa.eu/esco/skill/cpr-0001",
        "Emergency Response": "http://data.europa.eu/esco/skill/disaster-0033",
        "First Aid": "http://data.europa.eu/esco/skill/f7464f30-662b-4177-85a0-3df9693e9e58",
        "Team Leadership": "http://data.europa.eu/esco/skill/0022-team-leadership",
        "Environmental Care": "http://data.europa.eu/esco/skill/0044-environmental-care",
    }

    def __str__(self):
        return self.name

    def to_jsonld(self):
        return {
            "@type": "Organization",
            "@id": f"https://vms.example.org/orgs/{self.id}",
            "name": self.name,
            "url": self.url,
            "email": self.contact_email,
            "connectorEndpoint": self.connector_endpoint,
        }

    def catalog(self):
        return {
            "org": self.to_jsonld(),
            "events": [e.to_jsonld() for e in self.events.all()],
            "skills": [s.to_jsonld() for s in Skill.objects.filter(events__organization=self).distinct()]
        }




class Skill(models.Model):
    """
    Represents an ESCO skill (or local skill mapped to ESCO). Store canonical ESCO URI if available.
    """
    id = models.AutoField(primary_key=True)
    label = models.CharField(max_length=200)            # human label, e.g. "First Aid"
    esco_uri = models.URLField(blank=True, default="")  # e.g. http://data.europa.eu/esco/skill/...
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
    Core volunteer profile. This follows the thesis VolunteerRole/Volunteer suggestions:
    fields: affiliation, availability, hasSkills (links to ESCO), hoursPerWeek, certifications,
    volunteerStatus, language, location, privacy flags, etc.
    See Annex: VolunteerRole & vms:Volunteer in thesis. :contentReference[oaicite:3]{index=3}
    """

    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=250)
    password = models.CharField(max_length=128, default="admin")
    location = models.CharField(max_length=200, blank=True, default="")
    availability_preference = models.TextField(blank=True, default="")
    available_hours_per_week = models.IntegerField(blank=True, default=0)

    is_manager = models.BooleanField(default=False)
    organization = models.ForeignKey(
        "Organization", related_name="volunteers",
        on_delete=models.CASCADE, null=True, blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    # relationships
    skills = models.ManyToManyField(Skill, blank=True, related_name="volunteers")
    events = models.ManyToManyField("VolunteerEvent", blank=True, related_name="volunteers")

    def total_hours(self):
        return sum(e.duration_hours for e in self.events.all())

    def __str__(self):
        return f"{self.name} "


    def skills_list(self):
        return [s.label for s in self.skills.all()]

    def to_jsonld(self):
        """
        Emit a JSON-LD document following the vms:Volunteer.
        Uses schema:Person base, includes vms:totalHours and ESCO skills as @id links.
        See Listings 5.1/5.2 in thesis.}
        """
        ctx = {
            "@context": {
                "schema": "https://schema.org/",
                "esco": "http://data.europa.eu/esco/",
                "vms": "https://vms.example.org/context#"
            }
        }
        skills_jsonld = [ {"@id": s.esco_uri or s.uri()} for s in self.skills.all() ]
        profile = {
            **ctx,
            "@type": "vms:Volunteer",
            "@id": f"https://vms.example.org/volunteers/{self.id}",
            "schema:name": self.name,
            "schema:location": self.location,
            "schema:memberOf": self.organization,
            "vms:totalHours": {
                "@type": "schema:QuantitativeValue",
                "schema:value": self.total_hours(),
                "schema:unitText": "hours"
            },
            "schema:skills": skills_jsonld,
        }


        return profile


class VolunteerEvent(models.Model):
    """
    An event (schema:Event / vms:VolunteerEvent). Events can host VolunteerTasks.
    """
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=250)
    description = models.TextField(blank=True, default="")
    duration_hours = models.IntegerField(default=1)
    location = models.CharField(max_length=250, blank=True, default="")
    skills = models.ManyToManyField(Skill, blank=True, related_name="events")
    organization = models.ForeignKey(
        "Organization", related_name="events",
        on_delete=models.CASCADE, null=True, blank=True
    )
    isShared = models.BooleanField(default=True)
    isFinished = models.BooleanField(default=False)

    # NEW — dataspace metadata (for logs/UI/showcase)
    prioritize_local = models.BooleanField(default=False)
    shared_since = models.DateTimeField(null=True, blank=True)
    ds_endpoint = models.CharField(blank=True, default="")
    ds_asset_id = models.CharField(max_length=64, blank=True, default="")
    ds_contract_id = models.CharField(max_length=64, blank=True, default="")

    image = models.CharField(max_length=250, blank=True)

    def __str__(self):
        return f"{self.name}"

    @property
    def image_url(self):
        """Resolve to /static path automatically"""
        if self.image:
            return f"vms/images/events/{self.image}"
        return "vms/images/events/default.jpg"

    def to_jsonld(self):
        doc = {
            "@type": "vms:VolunteerEvent",
            "@id": f"https://vms.example.org/events/{self.id}",
            "schema:name": self.name
        }
        if self.location:
            doc["schema:location"] = {"@type": "Place", "name": self.location}
        if self.organization:
            doc["schema:organizer"] = {"@id": f"https://vms.example.org/orgs/{self.organization.id}"}
        return doc

    @property
    def registered_volunteers(self):
        return self.volunteers.count()

    @property
    def skills_needed(self):
        return [s.label for s in self.skills.all()]



    def save(self, *args, **kwargs):
        if not self.image:  # only assign if empty
            try:
                self.image = next(_image_cycle)
            except StopIteration:
                pass  # fallback: leave empty
        super().save(*args, **kwargs)




class Certificate(models.Model):
    """
    Government-issued or VMS-issued certificate, maps to schema:EducationalOccupationalCredential
    (Listing 5.5 in the thesis). :contentReference[oaicite:6]{index=6}
    """
    id = models.AutoField(primary_key=True)
    volunteer = models.ForeignKey(Volunteer, on_delete=models.CASCADE)
    issued_at = models.DateTimeField(auto_now_add=True)
    issuer = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.SET_NULL)
    items = models.JSONField(blank=True, default=list, encoder=DjangoJSONEncoder)  # canonical items included in cert
    proof_hash = models.CharField(max_length=128, blank=True, default="")  # mock or real proof
    skills = models.ManyToManyField(Skill, blank=True, related_name="certificates")

    def __str__(self):
        return f"Cert {self.id} for {self.volunteer.name}"

    # in models.py -> Certificate.to_jsonld (keep your existing, this is additive)
    def to_jsonld(self):
        doc = {
            "@context": {
                "schema": "https://schema.org/",
                "vms": "https://vms.example.org/context#"
            },
            "@type": "schema:EducationalOccupationalCredential",
            "@id": f"https://vms.example.org/certs/{self.id}",
            "schema:name": f"Volunteer Certificate {self.id}",
            "vms:issuedTo": {"@id": f"https://vms.example.org/volunteers/{self.volunteer.id}"},
            "schema:dateIssued": self.issued_at.date().isoformat(),
            "vms:items": self.items,
            "vms:proofHash": self.proof_hash,
        }
        if self.issuer:
            doc["schema:recognizedBy"] = {"@id": f"https://vms.example.org/orgs/{self.issuer.id}",
                                          "schema:name": self.issuer.name}
        skills = [{"@id": s.esco_uri or s.uri(), "schema:name": s.label} for s in self.skills.all()]
        if skills:
            doc["schema:skills"] = skills
        return doc


class LogEntry(models.Model):
    """
    Structured system log entries to show 'what happens under the hood'.
    Keep them readable and structured.
    """
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