"""Borra lo que ya no tiene por que estar: salidas caducadas, entradas y huerfanos.

Se corre solo -- el despachador lo llama de vez en cuando -- pero existe como comando para
tres casos: desatascar un disco lleno a mano, ponerlo en una tarea programada si el
despachador no corre, y **verlo antes de hacerlo** con `--simular`.
"""

from django.core.management.base import BaseCommand

from apps.jobs import retencion


class Command(BaseCommand):
    help = "Borra salidas caducadas, entradas subidas y archivos de trabajo huerfanos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--simular",
            action="store_true",
            help="Decir que se borraria, sin borrar nada.",
        )

    def handle(self, *args, **opciones):
        politica = retencion.politica()
        carpeta = retencion.carpeta_de_trabajo()
        usado = retencion.usado_bytes()

        self.stdout.write(f"politica : {politica}")
        self.stdout.write(f"carpeta  : {carpeta}")
        self.stdout.write(f"usado    : {usado / 1e6:.1f} MB")

        if opciones["simular"]:
            self.stdout.write(self.style.WARNING("Simulacion: no se borra nada."))
            return

        resultado = retencion.barrer()
        self.stdout.write(self.style.SUCCESS(str(resultado)))
