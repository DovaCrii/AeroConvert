from django.urls import path

from . import views

app_name = "presets"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("paquetes/", views.paquetes, name="paquetes"),
    path("paquetes/nuevo/", views.paquete_nuevo, name="paquete_nuevo"),
    path("paquetes/<slug:slug>/borrar/", views.paquete_borrar, name="paquete_borrar"),
    path("lotes/nuevo/", views.lote_nuevo, name="lote_nuevo"),
    path("lotes/<uuid:pk>/", views.lote, name="lote"),
    path("<slug:slug>/copiar/", views.copiar, name="copiar"),
    path("<slug:slug>/borrar/", views.borrar, name="borrar"),
]
