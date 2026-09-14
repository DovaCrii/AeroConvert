"""Dejar constancia de quién entra, desde dónde, y por qué puerta.

## Por qué hace falta anotarlo

Porque esta instalación está publicada en internet. Una entrada desde la red privada del
equipo y una desde internet abierto **son dos cosas distintas**, llegan por el mismo puerto, y
sin esto el registro no las distingue. El día que haya que revisar quién entró —y ese día
llega cuando algo va mal, no antes— esa columna es la diferencia entre saberlo y suponerlo.

django-axes ya escribe sus propias filas, pero solo de los intentos **fallidos** y sin decir
de qué lado vino la petición.

## Y qué NO se registra

Ni la contraseña, ni nada que se le parezca. Solo el nombre, la dirección y si vino de fuera.
"""

from __future__ import annotations

import logging

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .ip import ip_del_cliente, viene_de_internet

registro = logging.getLogger(__name__)


def _de_donde(request) -> str:
    if request is None:  # pragma: no cover -- una entrada sin peticion, p.ej. una prueba
        return "sin peticion"
    puerta = "internet" if viene_de_internet(request) else "red privada"
    return f"{ip_del_cliente(request) or 'sin direccion'} por {puerta}"


@receiver(user_logged_in)
def anotar_entrada(sender, request, user, **kwargs):
    registro.info("Entró %s desde %s.", user.get_username(), _de_donde(request))


@receiver(user_logged_out)
def anotar_salida(sender, request, user, **kwargs):
    if user is not None:
        registro.info("Salió %s desde %s.", user.get_username(), _de_donde(request))


@receiver(user_login_failed)
def anotar_fallo(sender, credentials, request=None, **kwargs):
    """Un intento fallido, con el nombre que se probó.

    **El nombre sí, la contraseña no.** Saber qué nombres se están probando es lo que
    distingue «alguien de la oficina tecleó mal» de «alguien está recorriendo un diccionario»,
    y es justo lo que hay que mirar primero.
    """
    registro.warning(
        "Intento fallido con «%s» desde %s.",
        (credentials or {}).get("username") or "sin nombre",
        _de_donde(request),
    )
