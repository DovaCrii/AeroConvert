"""`manage.py resumen_de_uso [--dias N]`: qué se usó y cómo salió, para comparar periodos."""

from django.core.management.base import BaseCommand

from apps.core import incidentes


class Command(BaseCommand):
    help = "Cuenta los trabajos, la tasa de éxito, los motivos de fallo y los incidentes."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=30, help="Cuántos días mirar (30).")

    def handle(self, *args, **opciones):
        resumen = incidentes.resumen_de_uso(max(1, opciones["dias"]))
        self.stdout.write(incidentes.en_texto(resumen))
