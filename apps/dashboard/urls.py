from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.convertir, name="convertir"),
    path("inspeccionar/", views.inspeccionar, name="inspeccionar"),
    path("ajustes/", views.ajustes, name="ajustes"),
    # Se llama `encolar` y no `convertir` porque es lo que hace: la conversión la ejecuta
    # el despachador después. Tener las dos con el mismo nombre invitaba a esperar que esta
    # devolviera el archivo.
    path("encolar/", views.encolar, name="encolar"),
]
