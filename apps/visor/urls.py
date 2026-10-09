from django.urls import path

from . import views

app_name = "visor"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("capa/", views.capa, name="capa"),
    path("punto/", views.punto, name="punto"),
    path("perfil/", views.perfil, name="perfil"),
    # Las partes de un vuelo propio (trayectoria, fotos, control) ya en Web Mercator (F19.3).
    path("vuelo/<uuid:pk>/", views.vuelo, name="vuelo"),
    # `z/x/y.png`: la convención de los mapas en la web. La ruta del archivo va en `?ruta=` y pasa
    # por `entrada.resolver` en cada petición.
    path("teselas/<int:z>/<int:x>/<int:y>.png", views.tesela, name="tesela"),
]
