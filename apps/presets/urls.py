from django.urls import path

from . import views

app_name = "presets"

urlpatterns = [
    path("", views.lista, name="lista"),
]
