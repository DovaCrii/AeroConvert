"""La puerta de la API (F16.4): un token por persona, **guardado solo como huella**.

    Authorization: Bearer ac_<prefijo>_<secreto>

## Por qué no `rest_framework.authtoken`

Guarda la clave tal cual en la base: quien lea una copia de respaldo tiene la llave de todos. Aquí
se guarda el **SHA-256** del token entero y un prefijo para encontrarlo; el token se muestra
una sola vez, al emitirlo (`manage.py emitir_token_api`). Se compara con `hmac.compare_digest`.

## Y el permiso aparte

Tener token no basta: hace falta el permiso `jobs.usar_api`, que da un administrador. Sin él, cada
extremo contesta **403** (con token válido) o **401** (sin token o con uno que no vale).
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from django.utils import timezone
from rest_framework import authentication, exceptions, permissions

PREFIJO_DEL_TOKEN = "ac_"

registro_de_accesos = logging.getLogger("aeroconvert.api")
CABECERA = "Bearer"


def huella(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def partes(token: str) -> tuple[str, str] | None:
    """(prefijo, secreto) de un token bien formado, o `None`."""
    if not token.startswith(PREFIJO_DEL_TOKEN):
        return None
    cuerpo = token[len(PREFIJO_DEL_TOKEN) :]
    prefijo, _, secreto = cuerpo.partition("_")
    if len(prefijo) != 8 or len(secreto) < 32:
        return None
    return prefijo, secreto


class TokenDeLaApi(authentication.BaseAuthentication):
    def authenticate(self, request):
        cabecera = authentication.get_authorization_header(request).decode("latin-1").split()
        if not cabecera or cabecera[0] != CABECERA:
            return None  # no es para esta puerta: que pruebe la sesión
        if len(cabecera) != 2:
            raise exceptions.AuthenticationFailed("La cabecera Authorization está mal formada.")
        token = cabecera[1]
        trozos = partes(token)
        if trozos is None:
            raise exceptions.AuthenticationFailed(
                "Ese token no tiene la forma de uno de AeroConvert."
            )

        from apps.core.models import TokenDeApi

        registro = (
            TokenDeApi.objects.select_related("owner")
            .filter(prefijo=trozos[0], revocado=False)
            .first()
        )
        if registro is None or not hmac.compare_digest(registro.huella, huella(token)):
            # El prefijo y la IP, **nunca el token**: con esto se ve un intento repetido.
            registro_de_accesos.warning(
                "API: token rechazado (prefijo %s) desde %s",
                trozos[0],
                request.META.get("REMOTE_ADDR", "?"),
            )
            raise exceptions.AuthenticationFailed("El token no vale o fue revocado.")
        if not registro.owner.is_active:
            registro_de_accesos.warning("API: token de una cuenta desactivada (%s)", trozos[0])
            raise exceptions.AuthenticationFailed("La cuenta del token está desactivada.")
        ahora = timezone.now()
        if registro.ultimo_uso is None or (ahora - registro.ultimo_uso).total_seconds() > 60:
            type(registro).objects.filter(pk=registro.pk).update(ultimo_uso=ahora)
        return registro.owner, registro

    def authenticate_header(self, request):
        return CABECERA


class PuedeUsarLaApi(permissions.BasePermission):
    message = "Su cuenta no tiene el permiso para usar la API (jobs.usar_api)."

    def has_permission(self, request, view):
        usuario = request.user
        return bool(usuario and usuario.is_authenticated and usuario.has_perm("jobs.usar_api"))
