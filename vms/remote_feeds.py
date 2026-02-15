def remote_opportunities_jsonld():
    mima = [
        {
            "@context": {
                "schema": "https://schema.org/",
                "vms": "https://vms.example.org/context#",
                "esco": "http://data.europa.eu/esco/skill/",
            },
            "@type": ["schema:Event", "vms:Opportunity"],
            "@id": "https://mima.example.org/opportunities/MIMA-001",
            "schema:name": "Open Learning Afternoons (German support)",
            "schema:description": "Support small groups learning German (reading, writing, grammar).",
            "schema:startDate": "02/03/2026",
            "schema:endDate": "18/12/2026",
            "schema:location": {
                "@type": "schema:Place",
                "schema:name": "Mima Community Center",
                "schema:address": {
                    "@type": "schema:PostalAddress",
                    "schema:streetAddress": "Altenberger Straße 69",
                    "schema:addressLocality": "Linz",
                    "schema:postalCode": "4040",
                    "schema:addressCountry": "AT",
                },
            },
            "schema:organizer": {
                "@type": "schema:Organization",
                "schema:name": "Mima",
                "schema:contactPoint": {
                    "@type": "schema:ContactPoint",
                    "schema:name": "Kathrin Fleckl",
                    "schema:telephone": "+43 512564778",
                    "schema:email": "contact@mima.example.org",
                },
            },
            "schema:maximumAttendeeCapacity": 20,
            "vms:commitment": {
                "@type": "vms:VolunteerCommitment",
                "vms:timeBlocks": ["Afternoon"],
                "vms:daysOfWeek": ["Monday", "Tuesday", "Wednesday"],
            },
            "vms:requiresSkill": [
                {
                    "@type": "schema:DefinedTerm",
                    "@id": "esco:e4da156d-a6c4-4b29-935b-eff9c9553cf1",
                    "schema:name": "Working in teams",
                },
                {
                    "@type": "schema:DefinedTerm",
                    "@id": "esco:4812a4ea-dc55-4dc6-b9b0-4a59bba2c647",
                    "schema:name": "German",
                }
            ],
            "vms:durationHours": 2,
        },
        {
            "@context": {
                "schema": "https://schema.org/",
                "vms": "https://vms.example.org/context#",
                "esco": "http://data.europa.eu/esco/skill/",
            },
            "@type": ["schema:Event", "vms:Opportunity"],
            "@id": "https://mima.example.org/opportunities/MIMA-002",
            "schema:name": "Community Garden Help",
            "schema:description": "Help with planting, watering, and elderly caring",
            "schema:startDate": "03/01/2026",
            "schema:endDate": "30/11/2026",
            "schema:location": {
                "@type": "schema:Place",
                "schema:name": "Community Garden (Linz)",
                "schema:address": {
                    "@type": "schema:PostalAddress",
                    "schema:addressLocality": "Linz",
                    "schema:addressCountry": "AT",
                },
            },
            "schema:organizer": {
                "@type": "schema:Organization",
                "schema:name": "Mima",
                "schema:contactPoint": {
                    "@type": "schema:ContactPoint",
                    "schema:name": "Mima Volunteer Desk",
                    "schema:email": "volunteers@mima.example.org",
                    "schema:telephone": "+43 700 000 000",
                },
            },
            "schema:maximumAttendeeCapacity": 20,
            "vms:commitment": {
                "@type": "vms:VolunteerCommitment",
                "vms:timeBlocks": ["Afternoon", "Evening"],
                "vms:daysOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
            },
            "vms:requiresSkill": [
                {
                    "@type": "schema:DefinedTerm",
                    "@id": "esco:5bcec244-3efe-45ac-8891-0ab4a91e9c48",
                    "schema:name": "Complying with health and safety procedures",
                },
                {
                    "@type": "schema:DefinedTerm",
                    "@id": "esco:8a1942a8-bebd-4cc5-bdff-fe215aaa3de5",
                    "schema:name": "Use gardening equipment",
                },
            ],
            "vms:durationHours": 3,
        },
    ]

    volgistics = [
        {
            "@context": {
                "schema": "https://schema.org/",
                "vms": "https://vms.example.org/context#",
                "esco": "http://data.europa.eu/esco/skill/",
            },
            "@type": ["schema:Event", "vms:Opportunity"],
            "@id": "https://volgistics.example.org/opportunities/VOL-101",
            "schema:name": "Food Pantry Intake & Sorting",
            "schema:description": "Sort donations, label boxes, assist with intake line.",
            "schema:startDate": "02/02/2026",
            "schema:endDate": "02/08/2027",
            "schema:location": {
                "@type": "schema:Place",
                "schema:name": "Community Pantry Warehouse",
                "schema:address": {
                    "@type": "schema:PostalAddress",
                    "schema:addressLocality": "Vienna",
                    "schema:addressCountry": "AT",
                },
            },
            "schema:organizer": {
                "@type": "schema:Organization",
                "schema:name": "Volgistics",
                "schema:contactPoint": {
                    "@type": "schema:ContactPoint",
                    "schema:name": "Ana Lopez",
                    "schema:email": "ana.lopez@example.org",
                    "schema:telephone": "+34 612 345 678",
                },
            },
            "schema:maximumAttendeeCapacity": 20,
            "vms:commitment": {
                "@type": "vms:VolunteerCommitment",
                "vms:timeBlocks": ["Morning"],
                "vms:daysOfWeek": ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
            },
            "vms:requiresSkill": [
                {
                    "@type": "schema:DefinedTerm",
                    "@id": "esco:1f1d2ff8-c4c1-45cc-9812-6a7ee84a73cb",
                    "schema:name": "Lead a team",
                },
                {
                    "@type": "schema:DefinedTerm",
                    "@id": "esco:1cf8cd2a-0b84-47f9-be63-4d36d3bff528",
                    "schema:name": "Carry out specialised packing for customers",
                },
            ],
            "vms:durationHours": 3,
        },
        {
            "@context": {
                "schema": "https://schema.org/",
                "vms": "https://vms.example.org/context#",
                "esco": "http://data.europa.eu/esco/skill/",
            },
            "@type": ["schema:Event", "vms:Opportunity"],
            "@id": "https://volgistics.example.org/opportunities/VOL-102",
            "schema:name": "Hospital Reception Support",
            "schema:description": "Welcome visitors, provide basic aid. Weekday shifts.",
            "schema:startDate": "02/11/2026",
            "schema:endDate": "12/12/2026",
            "schema:location": {
                "@type": "schema:Place",
                "schema:name": "Central Hospital - Main Lobby",
                "schema:address": {
                    "@type": "schema:PostalAddress",
                    "schema:addressLocality": "Vienna",
                    "schema:addressCountry": "AT",
                },
            },
            "schema:organizer": {
                "@type": "schema:Organization",
                "schema:name": "Volgistics",
                "schema:contactPoint": {
                    "@type": "schema:ContactPoint",
                    "schema:name": "Front Desk Coordinator",
                    "schema:email": "reception@volgistics.example.org",
                    "schema:telephone": "+43 1 000 0000",
                },
            },
            "schema:maximumAttendeeCapacity": 20,
            "vms:commitment": {
                "@type": "vms:VolunteerCommitment",
                "vms:timeBlocks": ["Morning", "Afternoon"],
                "vms:daysOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            },
            "vms:requiresSkill": [
                {
                    "@type": "schema:DefinedTerm",
                    "@id": "esco:f7464f30-662b-4177-85a0-3df9693e9e58",
                    "schema:name": "First Aid",
                },
            ],
            "vms:durationHours": 40,
        },
    ]

    return {
        "mima": mima,
        "volgistics": volgistics,
    }
