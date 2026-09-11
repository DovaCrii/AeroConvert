"""Desarrollo y pruebas. El despachador queda apagado: las pruebas usan
`manage.py procesar_trabajos --una-vez`, que es determinista.
"""

import copy

from .base import *  # noqa: F403
from .base import LOGGING as LOGGING_BASE

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
CONVERSION_DISPATCHER_ENABLED = False

# En pruebas, callado. Con `INFO` cada corrida escupe las lineas del despachador y de las
# sondas entre los puntos de pytest, y lo que se quiere leer ahi es el fallo.
#
# Se copia en profundidad en vez de tocar el de `base`: son el mismo objeto, y mutarlo
# dejaria el ajuste cambiado para cualquiera que importe los dos modulos.
LOGGING = copy.deepcopy(LOGGING_BASE)
LOGGING["loggers"]["apps"]["level"] = "WARNING"

# Sin manifiesto en desarrollo y en pruebas. `CompressedManifestStaticFilesStorage` exige
# haber corrido `collectstatic` y levanta al pintar cualquier plantilla si no se hizo, lo
# que convierte un olvido de despliegue en una suite roja que no dice por que.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
