"""Desarrollo y pruebas. El despachador queda apagado: las pruebas usan
`manage.py procesar_trabajos --una-vez`, que es determinista.
"""

from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
CONVERSION_DISPATCHER_ENABLED = False
