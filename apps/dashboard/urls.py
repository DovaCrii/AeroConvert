from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.convertir, name="convertir"),
    # El catálogo de todo, con buscador. La puerta para quien llega con una intención y no
    # con un formato.
    path("que-hacer/", views.que_puedo_hacer, name="que_puedo_hacer"),
    path("inspeccionar/", views.inspeccionar, name="inspeccionar"),
    # Las dos vías que faltaban: subir desde el equipo de quien mira, y andar la carpeta
    # compartida en vez de teclear su ruta.
    path("subir/", views.subir, name="subir"),
    path("explorar/", views.explorar, name="explorar"),
    path("ajustes/", views.ajustes, name="ajustes"),
    # Se llama `encolar` y no `convertir` porque es lo que hace: la conversión la ejecuta
    # el despachador después. Tener las dos con el mismo nombre invitaba a esperar que esta
    # devolviera el archivo.
    path("encolar/", views.encolar, name="encolar"),
]
