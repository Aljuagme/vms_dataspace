def annotate_event(event, volunteer, registered_ids):
    """
    Annotates an event with:
    - Registration status
    - Skill status (has/missing)
    - Eligibility to register
    """
    # Mark if already registered
    event.is_registered = event.id in registered_ids

    # Skill eligibility
    event_skills = list(event.skills.all())
    volunteer_skills = set(volunteer.skills.all())
    skill_status = {}
    missing_skills = []

    for s in event_skills:
        if s in volunteer_skills:
            skill_status[s.label] = "has"
        else:
            skill_status[s.label] = "missing"
            missing_skills.append(s.label)

    event.skill_status = skill_status
    event.missing_skills = missing_skills
    event.can_register = len(missing_skills) == 0
    event.is_federated = (volunteer.organization and event.organization != volunteer.organization)

    return event





