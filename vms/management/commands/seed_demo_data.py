# vms/management/commands/seed_demo_data.py
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone

from vms.models import Organization, VolunteerEvent, Volunteer


class Command(BaseCommand):
    help = "Seed demo data (superuser, orgs with self-descriptions, Demorg events, demo volunteer)."

    def handle(self, *args, **options):
        now = timezone.now()

        volgistics_sd = {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Volgistics",
            "identifier": "NL-KVK-12345678",
            "description": "Volunteer matching platform. We focus on natural disaster aid",
            "dateModified": "2026-01-11T14:30:00Z",
        }

        mima_sd = {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Mima",
            "identifier": "NL-KVK-87654321",
            "description": "Austrian-based community center. We host on-site volunteers. Mobile app available",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "Altenberger Straße 69",
                "addressLocality": "Linz",
                "postalCode": "4040",
                "addressCountry": "AT",
            },
            "dateModified": "2026-01-11T15:45:00Z",
        }

        demorg_sd = {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Demorg",
            "identifier": "ES-CIF-X1234567Z",
            "description": "Demo Volunteer Platform to show semantic interoperability in my master's thesis",
            "address": {"@type": "PostalAddress", "addressLocality": "Palma", "addressCountry": "ES"},
            "dateModified": "2026-02-12T00:00:00Z",
        }

        # --- 0) superuser
        User = get_user_model()
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@example.com", "admin")
            self.stdout.write(self.style.SUCCESS("✅ Superuser created: admin / admin"))
        else:
            self.stdout.write("ℹ️ Superuser already exists: admin")

        # --- 1) orgs
        mima, _ = Organization.objects.get_or_create(
            platform_key="mima",
            defaults=dict(
                name="Mima",
                url="https://mima.example.org",
                short_description="Austrian community center exposing opportunities as JSON-LD.",
                country="AT",
                focus_tags=["Health", "Community"],
                platform_vendor="Mima",
                interop_profile="JSON-LD API (canonical)",
                member_ds=True,
                contact_email="interop@mima.example.org",
                connector_endpoint="https://mima.example.org/api/discovery",
                self_description_jsonld={"ui": {"ui_color": "#4F46E5"}, "doc": mima_sd},
            ),
        )
        if (mima.self_description_jsonld or {}).get("doc") is None:
            mima.self_description_jsonld = {"ui": {"ui_color": "#4F46E5"}, "doc": mima_sd}
            mima.save(update_fields=["self_description_jsonld"])

        volgistics, _ = Organization.objects.get_or_create(
            platform_key="volgistics",
            defaults=dict(
                name="Volgistics",
                url="https://volgistics.example.org",
                short_description="Commercial VMS exposing opportunities as JSON-LD.",
                country="US",
                focus_tags=["Emergency response", "Logistics"],
                platform_vendor="Volgistics",
                interop_profile="JSON-LD API (canonical)",
                member_ds=True,
                contact_email="interop@volgistics.example.org",
                connector_endpoint="https://volgistics.example.org/api/discovery",
                self_description_jsonld={"ui": {"ui_color": "#0EA5E9"}, "doc": volgistics_sd},
            ),
        )
        if (volgistics.self_description_jsonld or {}).get("doc") is None:
            volgistics.self_description_jsonld = {"ui": {"ui_color": "#0EA5E9"}, "doc": volgistics_sd}
            volgistics.save(update_fields=["self_description_jsonld"])

        demorg, _ = Organization.objects.get_or_create(
            platform_key="demorg",
            defaults=dict(
                name="Demorg",
                url="https://demorg.example.org",
                short_description="Local provider with DB events; canonical JSON-LD generated via mapping pipeline.",
                country="ES",
                focus_tags=["Environment", "Health"],
                platform_vendor="Custom",
                interop_profile="Local DB -> pipeline -> canonical JSON-LD",
                member_ds=False,
                contact_email="it@demorg.example.org",
                connector_endpoint="https://demorg.example.org/api/discovery",
                self_description_jsonld={"ui": {"ui_color": "#22C55E"}, "doc": demorg_sd},
            ),
        )
        if (demorg.self_description_jsonld or {}).get("doc") is None:
            demorg.self_description_jsonld = {"ui": {"ui_color": "#22C55E"}, "doc": demorg_sd}
            demorg.save(update_fields=["self_description_jsonld"])

        # --- 2) demo volunteer
        alvaro, _ = Volunteer.objects.get_or_create(
            name="Alvaro",
            defaults=dict(
                password="alvaro",
                location="Palma",
                availability_preference="Weekends 09:00-18:00",
                is_manager=True,
                skills=["emergency care", "german"],
                organization=demorg,
            ),
        )
        self.stdout.write(self.style.SUCCESS("✅ Volunteer ready: Alvaro / (password ignored, stored='alvaro')"))

        # --- 3) Demorg events

        # (A) Beach Clean-up (ensure image + ensure Alvaro registered)
        ev1, _ = VolunteerEvent.objects.update_or_create(
            organization=demorg,
            source_local_id="DEM-SHARED-01",
            defaults=dict(
                name="Beach Clean-up",
                description=(
                    "Join us to clean the beach area and help protect local wildlife. "
                    "Gloves and bags provided. Mondays and Tuesdays. "
                    "If you have any questions, contact Astrid in astrid@example.org"
                ),
                location="Carrer de Manuela de los Herreros, 21 (07610 Palma)",
                duration_hours=2,
                max_attendee_capacity=20,
                image_url="vms/images/events/beach.jpg",  # <-- requested
                isShared=False,
                isFinished=False,
                shared_since=now,
                ds_endpoint=demorg.connector_endpoint,
                ds_asset_id="DEM-SHARED-01",
            ),
        )

        # Register Alvaro in Beach Clean-up (idempotent)
        alvaro.events.add(ev1)

        # (B) Local Warehouse Help (unchanged)
        ev2, _ = VolunteerEvent.objects.update_or_create(
            organization=demorg,
            source_local_id="DEM-LOCAL-01",
            defaults=dict(
                name="Local Warehouse Help",
                description="Assist in organizing donated items in the warehouse. Only weekends. If you have any questions, contact Astrid in astrid@example.org",
                location="Av. de la Cúria 1 (07150 Andratx)",
                duration_hours=2,
                max_attendee_capacity=10,
                isShared=False,
                isFinished=False,
            ),
        )

        # (C) NEW finished opportunity: light medical assistance + required emergency care
        ev3, _ = VolunteerEvent.objects.update_or_create(
            organization=demorg,
            source_local_id="DEM-FINISHED-01",
            defaults=dict(
                name="Light Medical Assistance",
                description=(
                    "Provide light medical assistance on-site (non-critical support such as basic first aid, "
                    "monitoring, and helping participants until professional services are available).\n\n"
                    "Emergency care is needed"
                ),
                location="Carrer de Manuela de los Herreros, 21 (07610 Palma)",
                duration_hours=70,
                max_attendee_capacity=4,
                skills=["Emergency care"],
                isShared=False,
                isFinished=True,
                # optional: set a stable image (avoids random assignment)
                image_url="vms/images/events/first_aid.jpg",
            ),
        )
        alvaro.events.add(ev3)

        self.stdout.write(self.style.SUCCESS("✅ Seed complete."))
