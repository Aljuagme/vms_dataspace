from django.contrib import admin
from .models import Organization, Volunteer, VolunteerEvent

admin.site.register(Organization)
admin.site.register(Volunteer)
admin.site.register(VolunteerEvent)


