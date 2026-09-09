from django.urls import path

from . import views

app_name = "presets"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("<slug:slug>/copiar/", views.copiar, name="copiar"),
    path("<slug:slug>/borrar/", views.borrar, name="borrar"),
]
