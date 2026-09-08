from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.mesa, name="mesa"),
    path("inspeccionar/", views.inspeccionar, name="inspeccionar"),
]
