"""Anota en el historial lo que cambió en las sondas desde la última vez.

Pensado para un temporizador (cada hora basta): así el historial sabe «desde cuándo» aunque nadie
haya abierto la pantalla de compatibilidad.
"""

from django.core.management.base import BaseCommand

from apps.engines import historial


class Command(BaseCommand):
    help = "Sondea los motores y anota los cambios de disponibilidad."

    def handle(self, *args, **opciones):
        cambios = historial.registrar()
        if not cambios:
            self.stdout.write("Sin cambios desde la última vez.")
            return
        for c in cambios:
            antes = c.antes or "(primera vez que se ve)"
            self.stdout.write(f"{c.motor}: {antes} → {c.ahora}")
