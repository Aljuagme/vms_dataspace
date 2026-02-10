# vms/management/commands/seed_demo_data.py
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone

from vms.models import (
    Organization, LocalResource, CanonicalResource, LogEntry,
    Volunteer, Skill, VolunteerEvent,
)


class Command(BaseCommand):
    help = "Seed demo data (superuser, orgs, local payloads, federated cache events, Demorg local+shared events)."

    def handle(self, *args, **options):
        now = timezone.now()

        # 0) superuser
        User = get_user_model()
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@example.com", "admin")
            self.stdout.write(self.style.SUCCESS("✅ Superuser created: admin / admin"))
        else:
            self.stdout.write("ℹ️ Superuser already exists: admin")

        # 1) orgs
        mima, _ = Organization.objects.get_or_create(
            platform_key="mima",
            defaults=dict(
                name="Mima",
                url="https://mima.example.org",
                short_description="Lightweight volunteer management platform with structured opportunity data.",
                country="AT",
                focus_tags=["Health", "Community"],
                platform_vendor="Mima",
                interop_profile="JSON API + skill/location filters",
                member_ds=True,
                contact_email="interop@mima.example.org",
                connector_endpoint="https://mima.example.org/api/discovery",
                metadata_json={"ui_color": "#4F46E5"},
            ),
        )

        volgistics, _ = Organization.objects.get_or_create(
            platform_key="volgistics",
            defaults=dict(
                name="Volgistics",
                url="https://volgistics.example.org",
                short_description="Platform exposing opportunities through a federation bridge.",
                country="US",
                focus_tags=["Emergency response", "Logistics"],
                platform_vendor="Volgistics",
                interop_profile="Bridge adapter + normalization",
                member_ds=True,
                contact_email="interop@volgistics.example.org",
                connector_endpoint="https://volgistics.example.org/api/discovery",
                metadata_json={"ui_color": "#0EA5E9"},
            ),
        )

        demorg, _ = Organization.objects.get_or_create(
            platform_key="demorg",
            defaults=dict(
                name="Demorg",
                url="https://demorg.example.org",
                short_description="Reference implementation used as the local platform for the portal demo.",
                country="ES",
                focus_tags=["Environment", "Health"],
                platform_vendor="Custom",
                interop_profile="Nested domain objects + JSON-LD mapping",
                member_ds=True,
                contact_email="it@demorg.example.org",
                connector_endpoint="https://demorg.example.org/api/discovery",
                metadata_json={"ui_color": "#22C55E"},
            ),
        )

        # 2) skills
        skill_first_aid, _ = Skill.objects.get_or_create(
            label="First Aid",
            defaults=dict(esco_uri="http://data.europa.eu/esco/skill/f7464f30-662b-4177-85a0-3df9693e9e58"),
        )
        skill_team_lead, _ = Skill.objects.get_or_create(
            label="Lead a team",
            defaults=dict(esco_uri="http://data.europa.eu/esco/skill/1f1d2ff8-c4c1-45cc-9812-6a7ee84a73cb"),
        )
        skill_env, _ = Skill.objects.get_or_create(
            label="Environmental Care",
            defaults=dict(esco_uri="http://data.europa.eu/esco/skill/0044-environmental-care"),
        )

        # 3) volunteer Demorg
        alvaro, _ = Volunteer.objects.get_or_create(
            name="Alvaro",
            organization=demorg,
            defaults=dict(
                password="alvaro",
                location="Palma",
                availability_preference="Weekends 09:00-18:00",
                available_hours_per_week=6,
                is_manager=False,
            ),
        )
        if alvaro.password != "alvaro":
            alvaro.password = "alvaro"
            alvaro.save(update_fields=["password"])
        alvaro.skills.add(skill_first_aid, skill_team_lead)

        # 4) local payloads (heterogeneous) — no invent fields
        # IMPORTANT: For remote orgs: mark everything shared, because Demorg must see them
        mima_local_opps = [
            ("M-OPP-1001", {
                "id": "M-OPP-1001",
                "title": "Food Bank Morning Shift",
                "starts_at": "2026-03-05T08:00:00+01:00",
                "duration_minutes": 180,
                "place": "Linz",
                "skills_esco": [skill_first_aid.esco_uri, skill_team_lead.esco_uri],
                "is_shared": True,
                "max_volunteers": 12,
            }),
            ("M-OPP-1002", {
                "id": "M-OPP-1002",
                "title": "Park Clean-up",
                "starts_at": "2026-03-09T10:00:00+01:00",
                "duration_minutes": 120,
                "place": "Urfahr",
                "skills_esco": [skill_env.esco_uri],
                "is_shared": True,
                "max_volunteers": 25,
            }),
        ]

        volgistics_local_opps = [
            ("VLG-77", {
                "OppID": "VLG-77",
                "OppName": "Community Kitchen",
                "StartDate": "03/06/2026",
                "StartTime": "09:30",
                "LengthHours": 4,
                "Site": {"City": "Vienna", "Room": "Kitchen A"},
                "Qualifications": [{"EscoUri": skill_first_aid.esco_uri}],
                "SharingFlag": "Y",
                "Capacity": 20,
            }),
            ("VLG-78", {
                "OppID": "VLG-78",
                "OppName": "Donation Sorting",
                "StartDate": "03/10/2026",
                "StartTime": "14:00",
                "LengthHours": 2,
                "Site": {"City": "Vienna"},
                "Qualifications": [],
                "SharingFlag": "Y",
                "Capacity": 15,
            }),
        ]

        # Demorg: 1 local-only, 1 shared
        demorg_local_opps = [
            ("DEM-LOCAL-01", {
                "opportunity": {
                    "uuid": "DEM-LOCAL-01",
                    "labels": {"en": "Local Warehouse Help"},
                    "schedule": {"date": "2026-03-08", "from": "10:00", "to": "12:00"},
                    "where": {"address": {"city": "Palma", "street": "Carrer Industria 5"}},
                    "requirements": {"competences": [{"esco": skill_team_lead.esco_uri}]},
                    "visibility": {"federated": False},  # local-only
                    "capacity": {"max": 5},
                }
            }),
            ("DEM-SHARED-01", {
                "opportunity": {
                    "uuid": "DEM-SHARED-01",
                    "labels": {"en": "Beach Clean-up (Demorg)"},
                    "schedule": {"date": "2026-03-12", "from": "09:00", "to": "11:00"},
                    "where": {"geo": {"lat": 39.5696, "lng": 2.6502}, "name": "Platja de Palma"},
                    "requirements": {"competences": [{"esco": skill_env.esco_uri}]},
                    "visibility": {"federated": True},   # cross-platform
                    "capacity": {"max": 30},
                }
            }),
        ]

        def upsert_local(org, entity_type, items):
            for local_id, payload in items:
                LocalResource.objects.update_or_create(
                    organization=org,
                    entity_type=entity_type,
                    local_id=local_id,
                    defaults={"payload": payload, "retrieved_at": now},
                )

        upsert_local(mima, "OPPORTUNITY", mima_local_opps)
        upsert_local(volgistics, "OPPORTUNITY", volgistics_local_opps)
        upsert_local(demorg, "OPPORTUNITY", demorg_local_opps)

        # 5) canonical builders (strict, no invention)
        def canonical_from_mima(payload: dict) -> dict:
            doc = {
                "@context": {
                    "schema": "https://schema.org/",
                    "vms": "https://example.org/vms#",
                    "esco": "https://data.europa.eu/esco/skill/",
                },
                "@type": ["schema:Event", "vms:Opportunity"],
                "@id": f"https://vms.example.org/opportunities/mima/{payload.get('id')}",
                "schema:name": payload.get("title"),
                "schema:startDate": payload.get("starts_at", "")[:10] if payload.get("starts_at") else None,
                "schema:location": {"@type": "schema:PostalAddress", "schema:addressLocality": payload.get("place")} if payload.get("place") else None,
            }
            if payload.get("max_volunteers") is not None:
                doc["schema:maximumAttendeeCapacity"] = payload["max_volunteers"]
            if payload.get("skills_esco"):
                doc["vms:requiresSkill"] = [
                    {"@type": "schema:DefinedTerm", "@id": uri, "schema:inDefinedTermSet": "https://ec.europa.eu/esco"}
                    for uri in payload["skills_esco"]
                ]
            return {k: v for k, v in doc.items() if v is not None}

        def canonical_from_volgistics(payload: dict) -> dict:
            city = (payload.get("Site") or {}).get("City")
            doc = {
                "@context": {
                    "schema": "https://schema.org/",
                    "vms": "https://example.org/vms#",
                    "esco": "https://data.europa.eu/esco/skill/",
                },
                "@type": ["schema:Event", "vms:Opportunity"],
                "@id": f"https://vms.example.org/opportunities/volgistics/{payload.get('OppID')}",
                "schema:name": payload.get("OppName"),
                "schema:startDate": payload.get("StartDate"),
                "schema:location": {"@type": "schema:PostalAddress", "schema:addressLocality": city} if city else None,
            }
            if payload.get("Capacity") is not None:
                doc["schema:maximumAttendeeCapacity"] = payload["Capacity"]
            esco_uris = [
                q.get("EscoUri")
                for q in (payload.get("Qualifications") or [])
                if isinstance(q, dict) and q.get("EscoUri")
            ]
            if esco_uris:
                doc["vms:requiresSkill"] = [
                    {"@type": "schema:DefinedTerm", "@id": uri, "schema:inDefinedTermSet": "https://ec.europa.eu/esco"}
                    for uri in esco_uris
                ]
            return {k: v for k, v in doc.items() if v is not None}

        def canonical_from_demorg(payload: dict) -> dict:
            opp = payload.get("opportunity") or {}
            sched = opp.get("schedule") or {}
            where = opp.get("where") or {}
            addr = (where.get("address") or {})
            city = addr.get("city") or None
            name = (opp.get("labels") or {}).get("en") or None

            doc = {
                "@context": {
                    "schema": "https://schema.org/",
                    "vms": "https://example.org/vms#",
                    "esco": "https://data.europa.eu/esco/skill/",
                },
                "@type": ["schema:Event", "vms:Opportunity"],
                "@id": f"https://vms.example.org/opportunities/demorg/{opp.get('uuid')}",
                "schema:name": name,
                "schema:startDate": sched.get("date"),
                "schema:location": {"@type": "schema:PostalAddress", "schema:addressLocality": city} if city else None,
            }

            cap = (opp.get("capacity") or {}).get("max")
            if cap is not None:
                doc["schema:maximumAttendeeCapacity"] = cap

            comps = ((opp.get("requirements") or {}).get("competences") or [])
            esco_uris = [c.get("esco") for c in comps if isinstance(c, dict) and c.get("esco")]
            if esco_uris:
                doc["vms:requiresSkill"] = [
                    {"@type": "schema:DefinedTerm", "@id": uri, "schema:inDefinedTermSet": "https://ec.europa.eu/esco"}
                    for uri in esco_uris
                ]
            return {k: v for k, v in doc.items() if v is not None}

        # 6) federated cache as VolunteerEvent:
        # - remote orgs: always cache as federated_cache
        # - demorg: create real local events (not federated_cache) and only shared ones go into federated feed because isShared=True
        def upsert_event(*, org, source_local_id, name, location, duration_hours, canonical_jsonld, is_shared, is_fed_cache):
            # For Demorg real local events, DO keep source_local_id (it ties to LocalResource) but
            # don't mark as federated_cache and don't blank it.
            source_entity_type = "OPPORTUNITY"
            ev, created = VolunteerEvent.objects.get_or_create(
                organization=org,
                is_federated_cache=is_fed_cache,
                source_entity_type=source_entity_type,
                source_local_id=source_local_id,
                defaults=dict(
                    name=name,
                    description="",
                    location=location or "",
                    duration_hours=duration_hours or 1,
                    isShared=is_shared,
                    isFinished=False,
                    shared_since=now if is_shared else None,
                    ds_endpoint=org.connector_endpoint if is_shared else "",
                    ds_asset_id=(source_local_id[:64] if is_shared else ""),
                    canonical_jsonld=canonical_jsonld if is_shared else {},
                ),
            )
            if not created:
                ev.name = name
                ev.description = ""
                ev.location = location or ""
                ev.duration_hours = duration_hours or 1
                ev.isShared = is_shared
                ev.shared_since = (ev.shared_since or now) if is_shared else None
                ev.ds_endpoint = org.connector_endpoint if is_shared else ""
                ev.ds_asset_id = (source_local_id[:64] if is_shared else "")
                ev.canonical_jsonld = canonical_jsonld if is_shared else {}
                ev.save()

        cached = 0

        # Remote orgs: cache shared opportunities so Demorg can see them
        for local_id, payload in mima_local_opps:
            canonical = canonical_from_mima(payload)
            dur_h = int(round((payload.get("duration_minutes", 60) / 60.0), 0)) if payload.get("duration_minutes") else 1
            upsert_event(
                org=mima,
                source_local_id=local_id,
                name=payload.get("title") or local_id,
                location=payload.get("place"),
                duration_hours=dur_h,
                canonical_jsonld=canonical,
                is_shared=True,
                is_fed_cache=True,
            )
            cached += 1
            CanonicalResource.objects.update_or_create(
                organization=mima,
                entity_type="OPPORTUNITY",
                canonical_id=canonical["@id"],
                defaults={"canonical_jsonld": canonical},
            )

        for local_id, payload in volgistics_local_opps:
            if str(payload.get("SharingFlag", "")).upper() != "Y":
                continue
            canonical = canonical_from_volgistics(payload)
            upsert_event(
                org=volgistics,
                source_local_id=local_id,
                name=payload.get("OppName") or local_id,
                location=(payload.get("Site") or {}).get("City"),
                duration_hours=int(payload.get("LengthHours") or 1),
                canonical_jsonld=canonical,
                is_shared=True,
                is_fed_cache=True,
            )
            cached += 1
            CanonicalResource.objects.update_or_create(
                organization=volgistics,
                entity_type="OPPORTUNITY",
                canonical_id=canonical["@id"],
                defaults={"canonical_jsonld": canonical},
            )

        # Demorg: create local VolunteerEvent rows for BOTH local-only and shared
        for local_id, payload in demorg_local_opps:
            opp = payload.get("opportunity") or {}
            name = (opp.get("labels") or {}).get("en") or local_id
            federated = bool(((opp.get("visibility") or {}).get("federated")))
            canonical = canonical_from_demorg(payload) if federated else {}

            # duration: compute if possible, otherwise 1
            sched = opp.get("schedule") or {}
            dur = 1
            if sched.get("from") and sched.get("to"):
                try:
                    fh, fm = [int(x) for x in str(sched.get("from")).split(":")[:2]]
                    th, tm = [int(x) for x in str(sched.get("to")).split(":")[:2]]
                    minutes = (th * 60 + tm) - (fh * 60 + fm)
                    if minutes > 0:
                        dur = max(1, int(round(minutes / 60.0)))
                except Exception:
                    dur = 1

            where = opp.get("where") or {}
            location = (where.get("address") or {}).get("city") or where.get("name") or "Palma"

            upsert_event(
                org=demorg,
                source_local_id=local_id,  # ties to LocalResource.local_id
                name=name,
                location=location,
                duration_hours=dur,
                canonical_jsonld=canonical,
                is_shared=federated,
                is_fed_cache=False,  # IMPORTANT: these are Demorg's real local events
            )

            if federated and canonical.get("@id"):
                CanonicalResource.objects.update_or_create(
                    organization=demorg,
                    entity_type="OPPORTUNITY",
                    canonical_id=canonical["@id"],
                    defaults={"canonical_jsonld": canonical},
                )

        LogEntry.objects.create(
            level="INFO",
            action="SeedDemoData",
            details=(
                f"Seeded orgs + Alvaro; "
                f"LocalResources={LocalResource.objects.count()}; "
                f"FederatedCacheEvents={cached}; "
                f"TotalVolunteerEvents={VolunteerEvent.objects.count()}"
            ),
        )
        self.stdout.write(self.style.SUCCESS("✅ Seed complete."))
