"""Modo taller: corre en la estacion de trabajo y **los archivos no salen del disco**.

Es el modo para el que se diseno la aplicacion. La entrada es una ruta, no una subida: una
ortofoto de obra son cientos de megabytes y copiarla para convertirla es tiempo y espacio
tirados. Sin tope de tamano, porque el limite lo pone el disco.

El login se exige igual que en `nube`. No es ceremonia: en este modo la ruta de origen es un
primitivo de lectura del disco entero, asi que la puerta importa **mas**, no menos.
"""

from .base import *  # noqa: F403

DEBUG = False
CONVERSION_DISPATCHER_ENABLED = True

# HTTPS no aplica: esto escucha en 127.0.0.1. Marcar las cookies como seguras las
# romperia sobre http y dejaria a la persona sin poder entrar.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
