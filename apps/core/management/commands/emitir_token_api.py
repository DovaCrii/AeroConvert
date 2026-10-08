"""Emite un token de la API para una persona y lo muestra **una sola vez**.

    python manage.py emitir_token_api ana --nombre "script de entregas"
    python manage.py emitir_token_api --revocar 1a2b3c4d

Además del token, la persona necesita el permiso `jobs.usar_api` (lo da un administrador). Sin él,
la API contesta 403 aunque el token sea bueno.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import TokenDeApi


class Command(BaseCommand):
    help = "Emite (o revoca) un token de la API de conversión."

    def add_arguments(self, parser):
        parser.add_argument("usuario", nargs="?", help="Nombre de usuario de la persona.")
        parser.add_argument("--nombre", default="token", help="Para qué es el token.")
        parser.add_argument("--revocar", metavar="PREFIJO", help="Revoca el token con ese prefijo.")

    def handle(self, *args, **opciones):
        if opciones["revocar"]:
            cuantos = TokenDeApi.objects.filter(prefijo=opciones["revocar"], revocado=False).update(
                revocado=True
            )
            if not cuantos:
                raise CommandError("No hay ningún token vigente con ese prefijo.")
            self.stdout.write(f"Revocado el token {opciones['revocar']}.")
            return
        if not opciones["usuario"]:
            raise CommandError("Diga para qué persona es el token.")
        try:
            usuario = get_user_model().objects.get(username=opciones["usuario"])
        except get_user_model().DoesNotExist as fallo:
            raise CommandError(f"No existe el usuario «{opciones['usuario']}».") from fallo
        registro, token = TokenDeApi.emitir(usuario, opciones["nombre"])
        self.stdout.write(f"Token para {usuario.get_username()} (prefijo {registro.prefijo}):")
        self.stdout.write(token)
        self.stdout.write("Guárdelo ahora: no se puede volver a ver.")
        if not usuario.has_perm("jobs.usar_api"):
            self.stdout.write(
                "Aviso: la persona no tiene el permiso jobs.usar_api; la API dirá 403."
            )
