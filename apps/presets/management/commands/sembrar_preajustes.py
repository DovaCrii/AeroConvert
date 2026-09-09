"""Crea los preajustes de fábrica. Idempotente: correrlo dos veces no duplica."""

from django.core.management.base import BaseCommand

from apps.presets.models import sembrar


class Command(BaseCommand):
    help = "Crea o actualiza los preajustes de fábrica a partir de los perfiles de destino."

    def handle(self, *args, **opciones):
        creados, actualizados = sembrar()
        self.stdout.write(
            self.style.SUCCESS(f"{creados} preajustes creados, {actualizados} actualizados.")
        )
