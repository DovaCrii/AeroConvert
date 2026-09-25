"""Corre el bucle del despachador desde la linea de comandos.

Sirve para tres cosas, y las tres importan:

1. **Las pruebas.** Con `--una-vez` el bucle es determinista: no hay hilo, no hay carrera,
   no hay que dormir esperando a que algo pase. Una prueba que arranca un hilo es una
   prueba que falla los martes.
2. **El obrero de la VM.** Ya no es un «si algun dia»: en el despliegue este comando **es**
   el despachador, en su propia unidad de systemd, y el proceso web va con
   `AEROCONVERT_DESPACHADOR=0`. Con varios obreros de gunicorn arrancarian varios
   despachadores, y el tope de trabajos simultaneos se comprueba con un `count()` que no es
   atomico: dos leen cero a la vez y arrancan dos conversiones.

   Ojo: `_bucle()` **no** hace el barrido de arranque -- ese vive en `arrancar()` --, asi
   que la unidad lo lanza aparte con `ExecStartPre`. Es el barrido importante: el unico
   momento en que se sabe que ningun trabajo esta corriendo.
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
        parser.add_argument(
            "--carril",
            choices=despachador.CARRILES,
            default=None,
            help="Con --una-vez: solo ese carril. Sin él, la cola entera.",
        )

    def handle(self, *args, **opciones):
        if opciones["recoger"]:
            recogidos = despachador.recoger_muertos()
            self.stdout.write(f"Recogidos {recogidos} trabajos interrumpidos.")
            return

        if opciones["una_vez"]:
            hechos = despachador.procesar_una_vez(opciones["carril"])
            self.stdout.write(f"Procesados {hechos}.")
            return

        # **Los dos carriles, cada uno en su hilo.** Antes era un solo bucle, y desde que las
        # herramientas de PDF pasan por aquí un «numerar» esperaría detrás de una ortofoto.
        self.stdout.write(
            f"Procesando la cola en los carriles {', '.join(despachador.CARRILES)}. "
            "Ctrl+C para parar."
        )
        try:
            despachador.servir()
        except KeyboardInterrupt:
            self.stdout.write("Detenido.")
