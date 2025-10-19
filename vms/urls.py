# vms/urls.py
from django.urls import path

# Import your separated view modules
from . import views_ui
from . import views_edc

app_name = "vms"

urlpatterns = [
    # ---------------- UI ROUTES ----------------
    path("", views_ui.index, name="index"),
    path("login/", views_ui.login_view, name="login"),
    path("logout/", views_ui.logout_view, name="logout"),
    path("dashboard/<int:vid>/", views_ui.dashboard_view, name="dashboard"),
    path("events/<int:vid>/", views_ui.events_page, name="events_page"),
    path("certificate/<int:vid>/", views_ui.certificate_view, name="certificate"),
    path("onboard/<int:vid>/", views_ui.onboard_view, name="onboard"),
    path("logs/", views_ui.logs_view, name="logs_view"),
    path("events/create/", views_ui.create_event, name="create_event"),
path("volunteer/<int:vid>/event/<int:eid>/finish/", views_ui.finish_event, name="finish_event"),
path('ranking/', views_ui.ranking_view, name='ranking'),


    # Volunteer actions
    path("api/register-volunteer/", views_ui.api_register_volunteer, name="api_register_volunteer"),
    path("api/import-history/<int:vid>/", views_ui.api_import_history, name="api_import_history"),
    path("register/<int:vid>/<int:eid>/", views_ui.register_event, name="register_event"),
    path("unregister/<int:vid>/<int:eid>/", views_ui.unregister_event, name="unregister_event"),
    path("api/orgs/", views_ui.api_orgs, name="api_orgs"),
    path("toggle-role/<int:volunteer_id>/", views_ui.toggle_role, name="toggle_role"),
    path("switch-volunteer/<int:volunteer_id>/", views_ui.switch_volunteer, name="switch_volunteer"),
    path("api/volunteer/<int:vid>/certificate/context/", views_ui.api_certificate_context, name="api_certificate_context"),
    path("api/certificate/request/", views_ui.api_certificate_request, name="api_certificate_request"),



    # ---------------- EDC / CONNECTOR ROUTES ----------------
    path("api/onboard-organization/", views_edc.api_onboard_organization, name="api_onboard_organization"),
    path("api/logs/", views_edc.api_get_logs, name="api_get_logs"),
    path("api/catalog/<int:org_id>/", views_edc.api_catalog, name="api_catalog"),
    path("api/catalog/<int:org_id>/events/<int:event_id>/", views_edc.api_event_detail, name="api_event_detail"),
    path("volunteer/<int:volunteer_id>/toggle-dataspace/", views_edc.toggle_dataspace, name="toggle_dataspace"),

]
