from django.urls import path
from . import views

app_name = "vms"

urlpatterns = [
    path("", views.index, name="index"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/<int:vid>/", views.dashboard_view, name="dashboard"),
    path("dashboard/<int:vid>/register/<int:eid>/", views.register_event, name="register_event"),
    path("dashboard/<int:vid>/unregister/<int:eid>/", views.unregister_event, name="unregister_event"),
    path("events/<int:vid>/", views.events_page, name="events_page"),
    path("certificate/<str:vid>/", views.certificate_view, name="certificate"),
    path("logs/", views.logs_view, name="logs_view"),

    # API endpoints (JSON)
    path("api/volunteer/register/", views.api_register_volunteer, name="api_register"),
    path("api/volunteer/<str:vid>/import/", views.api_import_history, name="api_import"),

    path("api/edc/orgs/", views.api_orgs, name="api_orgs"),
    path("api/get_logs/", views.api_get_logs, name="api_logs"),
    path("api/onboard_organization/", views.api_onboard_organization, name="api_onboard_organization"),
    path("api/catalog/<int:org_id>/", views.api_catalog, name="api_catalog"),
    path("onboard/<int:vid>/", views.onboard_view, name="onboard"),


]
