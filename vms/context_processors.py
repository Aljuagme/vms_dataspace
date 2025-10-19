from .models import Volunteer

def current_volunteer(request):
    volunteer = None
    if request.session.get("volunteer_id"):
        try:
            volunteer = Volunteer.objects.get(id=request.session["volunteer_id"])
        except Volunteer.DoesNotExist:
            volunteer = None
    return {"volunteer": volunteer}
