"""Las rutas de los vuelos de dron.

## Mismo espacio de nombres, mismas direcciones

Estas rutas **no tienen espacio de nombres propio**: `apps/documents/urls.py` las suma a su lista y
se siguen resolviendo como `documents:vuelo_dron`, `documents:video`, etc., y bajo `/documentos/`.
Las direcciones están guardadas en marcadores, en la acción rápida, en Tino y en el historial de
trabajos; mover el código de sitio no es motivo para romperlas.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("telemetria/", views.telemetria_vista, name="telemetria"),
    path("fotos-dron/", views.fotos_dron_vista, name="fotos_dron"),
    path("vuelo-dron/", views.vuelo_dron_vista, name="vuelo_dron"),
    path("vuelo/<uuid:pk>/", views.vuelo_ver, name="vuelo_ver"),
    path("vuelo/<uuid:pk>/datos/", views.vuelo_datos, name="vuelo_datos"),
    path("vuelo/<uuid:pk>/foto/<int:n>/", views.vuelo_miniatura, name="vuelo_miniatura"),
    path("video/", views.video_vista, name="video"),
    path("vuelos/", views.vuelos, name="vuelos"),
]
