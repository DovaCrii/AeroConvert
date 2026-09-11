"""Despliegue en VM propia, detras de nginx con TLS."""

from decouple import Csv, config

from .base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# **Del entorno, y apagado por omision.** Detras de gunicorn el despachador es una unidad de
# systemd propia: ver el razonamiento en `base.py`. `AEROCONVERT_DESPACHADOR=1` solo en esa
# unidad, nunca en el servicio web.
#
# `/salud/` sin redirigir a HTTPS: con `SECURE_SSL_REDIRECT` puesto, un `curl` local a la
# sonda recibe un 301 y el guion de despliegue se queda esperando un 200 que no llega.
SECURE_REDIRECT_EXEMPT = [r"^salud/$"]
