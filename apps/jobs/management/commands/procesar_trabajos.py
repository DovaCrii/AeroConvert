"""Corre el bucle del despachador desde la linea de comandos.

Sirve para tres cosas, y las tres importan:

1. **Las pruebas.** Con `--una-vez` el bucle es determinista: no hay hilo, no hay carrera,
   no hay que dormir esperando a que algo pase. Una prueba que arranca un hilo es una
   prueba que falla los martes.
2. **Un servidor sin el hilo.** Si algun dia conviene separar el obrero del servidor web,
   este comando ya lo es.
3. **Desatascar a mano.** `--recoger` voltea los trabajos cuyo obrero desaparecio.
"""

from django.core.management.base import BaseCommand

from apps.jobs import despachador


class Command(BaseCommand):
    help = "Procesa la cola de conversiones."

    def add_arguments(self, parser):
        parser.add_argument(
            "--una-vez",
            action="store_true",
            help="Un solo ciclo y salir. Es lo que usan las pruebas.",
        )
        parser.add_argument(
            "--recoger",
            action="store_true",
            help="Solo recoger trabajos cuyo obrero desaparecio, sin ejecutar nada.",
        )

    def handle(self, *args, **opciones):
        if opciones["recoger"]:
            recogidos = despachador.recoger_muertos()
            self.stdout.write(f"Recogidos {recogidos} trabajos interrumpidos.")
            return

        if opciones["una_vez"]:
            hechos = despachador.procesar_una_vez()
            self.stdout.write(f"Procesados {hechos}.")
            return

        self.stdout.write("Procesando la cola. Ctrl+C para parar.")
        try:
            despachador._bucle()
        except KeyboardInterrupt:
            self.stdout.write("Detenido.")
