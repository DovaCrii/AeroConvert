from django.urls import path

from . import api

urlpatterns = [
    path("capacidades/", api.Capacidades.as_view(), name="api-capacidades"),
]
