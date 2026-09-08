"""Desarrollo y pruebas. El despachador queda apagado: las pruebas usan
`manage.py procesar_trabajos --una-vez`, que es determinista.
"""

from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
CONVERSION_DISPATCHER_ENABLED = False

# Sin manifiesto en desarrollo y en pruebas. `CompressedManifestStaticFilesStorage` exige
# haber corrido `collectstatic` y levanta al pintar cualquier plantilla si no se hizo, lo
# que convierte un olvido de despliegue en una suite roja que no dice por que.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
