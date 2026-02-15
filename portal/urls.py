from django.urls import path
from . import views

urlpatterns = [
    path("", views.portal_directory, name="portal_home"),
    path("providers/<slug:platform_key>/", views.provider_detail, name="provider_detail"),
path(
    "opportunity/<slug:provider_key>/<path:opportunity_id>/",
    views.opportunity_detail,
    name="opportunity_detail"
),

]
