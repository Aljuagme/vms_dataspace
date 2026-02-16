# vms/urls.py
from django.urls import path
from django.utils.module_loading import import_string

app_name = "vms"


def lazy_view(dotted_path: str):
    """
    Lazy import a view function only when the route is actually hit.
    This avoids heavy imports during Django/Gunicorn boot on low-memory hosts.
    """
    def _wrapped(request, *args, **kwargs):
        view_func = import_string(dotted_path)
        return view_func(request, *args, **kwargs)
    return _wrapped


urlpatterns = [
    # ---------------- ROOT ----------------
    path("", lazy_view("vms.views_ui.root_redirect"), name="root"),

    # ---------------- UI ROUTES ----------------
    path("login/", lazy_view("vms.views_ui.login_view"), name="login"),
    path("logout/", lazy_view("vms.views_ui.logout_view"), name="logout"),

    path("dashboard/<int:vid>/", lazy_view("vms.views_ui.dashboard_view"), name="dashboard"),
    path("events/<int:vid>/", lazy_view("vms.views_ui.events_page"), name="events_page"),
    path("events/create/", lazy_view("vms.views_ui.create_event"), name="create_event"),

    path("volunteer/<int:vid>/event/<int:eid>/finish/", lazy_view("vms.views_ui.finish_event"), name="finish_event"),
    path("ranking/", lazy_view("vms.views_ui.ranking_view"), name="ranking"),

    path("certificate/<int:vid>/", lazy_view("vms.views_ui.certificate_view"), name="certificate"),
    path("onboard/<int:vid>/", lazy_view("vms.views_ui.onboard_view"), name="onboard"),

    # logs: you had both logs_view + logs; keep both names pointing to same handler
    path("logs/", lazy_view("vms.views_ui.logs_view"), name="logs_view"),
    path("logs/", lazy_view("vms.views_ui.logs_view"), name="logs"),

    # Mapping catalog flows
    path("mapping/save/", lazy_view("vms.views_ui.save_mapping_catalog"), name="save_mapping_catalog"),
    path(
        "mapping-catalog/opportunity/generate/",
        lazy_view("vms.views_ui.generate_opportunity_catalog"),
        name="generate_opportunity_catalog",
    ),

    # Federated register
    path(
        "events/federated-register/<int:vid>/<str:provider_key>/<path:opportunity_id>/",
        lazy_view("vms.views_ui.federated_register_event"),
        name="federated_register_event",
    ),

    # ---------------- API ROUTES (UI module) ----------------
    path("api/register-volunteer/", lazy_view("vms.views_ui.api_register_volunteer"), name="api_register_volunteer"),
    path("api/import-history/<int:vid>/", lazy_view("vms.views_ui.api_import_history"), name="api_import_history"),
    path("register/<int:vid>/<int:eid>/", lazy_view("vms.views_ui.register_event"), name="register_event"),
    path("unregister/<int:vid>/<int:eid>/", lazy_view("vms.views_ui.unregister_event"), name="unregister_event"),
    path("api/orgs/", lazy_view("vms.views_ui.api_orgs"), name="api_orgs"),
    path("toggle-role/<int:volunteer_id>/", lazy_view("vms.views_ui.toggle_role"), name="toggle_role"),
    path("switch-volunteer/<int:volunteer_id>/", lazy_view("vms.views_ui.switch_volunteer"), name="switch_volunteer"),

    # Certificate APIs
    path(
        "api/volunteer/<int:vid>/certificate/context/",
        lazy_view("vms.views_ui.api_certificate_context"),
        name="api_certificate_context",
    ),
    path("api/certificate/request/", lazy_view("vms.views_ui.api_certificate_request"), name="api_certificate_request"),

    # ---------------- EDC / CONNECTOR ROUTES ----------------
    path(
        "api/onboard-organization/",
        lazy_view("vms.views_edc.api_onboard_organization"),
        name="api_onboard_organization",
    ),
    path("api/catalog/<int:org_id>/", lazy_view("vms.views_edc.api_catalog"), name="api_catalog"),
    path(
        "api/catalog/<int:org_id>/events/<int:event_id>/",
        lazy_view("vms.views_edc.api_event_detail"),
        name="api_event_detail",
    ),
    path(
        "volunteer/<int:volunteer_id>/toggle-dataspace/",
        lazy_view("vms.views_edc.toggle_dataspace"),
        name="toggle_dataspace",
    ),
]
