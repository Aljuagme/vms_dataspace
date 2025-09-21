from django.contrib import admin
from .models import Organization, Skill, Volunteer, VolunteerEvent, Certificate, LogEntry

admin.site.register(Organization)
admin.site.register(Skill)
admin.site.register(Volunteer)
admin.site.register(VolunteerEvent)
admin.site.register(Certificate)
admin.site.register(LogEntry)

