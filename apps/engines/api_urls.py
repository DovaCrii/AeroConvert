from django.urls import path

from apps.jobs import api as api_trabajos

from . import api

urlpatterns = [
    path("capacidades/", api.Capacidades.as_view(), name="api-capacidades"),
    path("trabajos/", api_trabajos.Trabajos.as_view(), name="api-trabajos"),
    path("trabajos/<uuid:pk>/", api_trabajos.Trabajo.as_view(), name="api-trabajo"),
    path(
        "trabajos/<uuid:pk>/descarga/",
        api_trabajos.Descarga.as_view(),
        name="api-trabajo-descarga",
    ),
]
