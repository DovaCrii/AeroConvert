"""Deja la caché de teselas del visor por debajo de su tope.

Se corre sola (el barrido de la aplicación la incluye y `cache.escribir` barre cuando lo escrito
pasa de un veinteavo del tope), pero existe como comando para **vaciarla** (`--vaciar`) y para
**verla antes de tocarla** (`--simular`).
"""

from django.core.management.base import BaseCommand

from apps.visor import cache


class Command(BaseCommand):
    help = "Barre la caché de teselas del visor: borra las que hace más tiempo que nadie mira."

    def add_arguments(self, parser):
        parser.add_argument("--simular", action="store_true", help="Decir qué se borraría.")
        parser.add_argument(
            "--tope-mb", type=int, default=None, help="Otro tope, en MB, solo para esta vez."
        )
        parser.add_argument(
            "--vaciar", action="store_true", help="Borrar todo (equivale a un tope de 0)."
        )

    def handle(self, *args, **opciones):
        self.stdout.write(f"carpeta : {cache.carpeta()}")
        self.stdout.write(f"tope    : {cache.tope_bytes() / 1e6:.1f} MB")
        self.stdout.write(f"usado   : {cache.usado_bytes() / 1e6:.1f} MB")

        if opciones["vaciar"]:
            tope = 0
        elif opciones["tope_mb"] is not None:
            tope = max(0, opciones["tope_mb"]) * 1024 * 1024
        else:
            tope = None

        resultado = cache.barrer(tope, simular=opciones["simular"])
        if opciones["simular"]:
            self.stdout.write(self.style.WARNING(f"Simulación: {resultado}"))
        else:
            self.stdout.write(self.style.SUCCESS(str(resultado)))
