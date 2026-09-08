"""Motores de mentira para probar el runner sin GDAL.

## La idea, que es la que sostiene media suite

`MotorDeMentira` **no simula la ejecucion**: construye un plan cuyo `argv` es
`[sys.executable, "-c", <script>]`. Se lanza un proceso de verdad, con tuberias de verdad,
progreso de verdad y `os.replace()` de verdad. Lo unico que no hay es GDAL.

Asi lo que se prueba es **el pegamento**, que es donde estan los errores caros: que el argv
se construya entero y en orden, que no se crea el codigo de salida, que cancelar mate al
hijo y borre el parcial, que el original no se toque en ningun camino de fallo.

Es la generalizacion del truco que ya usa AeroBim -- «un conversor de mentira, un script
que escribe un DXF donde le digan, que recorre el camino entero sin depender de la Open
Design Alliance».
"""

from __future__ import annotations

import sys
from pathlib import Path

from .base import Disponibilidad, Motor, ParDeFormatos, PlanDeEjecucion

#: Script del hijo. Recibe la ruta de salida, que escribir, cuanto tardar, que imprimir y
#: con que codigo salir. Todo por argumentos, para que no haya estado escondido.
GUION = r"""
import sys, time
salida, contenido, tarda, pasos, codigo = sys.argv[1:6]
for i in range(int(pasos)):
    print(f"{int(100 * (i + 1) / int(pasos))}...", flush=True)
    time.sleep(float(tarda) / max(1, int(pasos)))
if contenido:
    with open(salida, "wb") as f:
        f.write(contenido.encode("utf-8"))
sys.exit(int(codigo))
"""


class MotorDeMentira(Motor):
    """Un motor que lanza un proceso real y hace exactamente lo que se le pida.

    Parametros:
        escribe: que contenido dejar en la salida. Cadena vacia = **no escribe nada**, que
            es el caso de «codigo 0 y ningun archivo».
        codigo_de_salida: con que codigo termina el hijo.
        tarda_s: cuanto dura. Sirve para probar el timeout y la cancelacion.
        pasos: cuantas lineas de progreso imprime.
    """

    familia = "prueba"

    def __init__(
        self,
        identificador: str = "mentira",
        pares_=((("geotiff", "cog")),),
        *,
        disponible: bool = True,
        prioridad: int = 100,
        motivo: str = "",
        escribe: str = "salida de mentira",
        codigo_de_salida: int = 0,
        tarda_s: float = 0.0,
        pasos: int = 4,
        timeout_s: int = 3600,
        ruta_de_salida: Path | None = None,
    ) -> None:
        self.id = identificador
        self.nombre = identificador
        self.prioridad = prioridad
        self._pares = frozenset(ParDeFormatos(o, d) for o, d in pares_)
        self._disponible = disponible
        self._motivo = motivo
        self.escribe = escribe
        self.codigo_de_salida = codigo_de_salida
        self.tarda_s = tarda_s
        self.pasos = pasos
        self.timeout_s = timeout_s
        self.ruta_de_salida = ruta_de_salida
        #: El ultimo plan construido. Las pruebas lo inspeccionan para comprobar el argv.
        self.ultimo_plan: PlanDeEjecucion | None = None

    def pares(self):
        return self._pares

    def disponibilidad(self):
        if self._disponible:
            return Disponibilidad.si("mentira 1.0")
        return Disponibilidad.no(
            self._motivo or "motor-no-disponible",
            "No esta instalado.",
            sugerencia="Instalalo.",
            alternativas=("cog", "jp2"),
        )

    def opciones(self, par):
        return ()

    def plan(self, trabajo) -> PlanDeEjecucion:
        destino = self.ruta_de_salida or Path(trabajo.output_path or "salida.tif")
        # El hijo escribe en el parcial, igual que haria un motor de verdad.
        parcial = destino.with_name(destino.name + ".parcial")
        plan = PlanDeEjecucion(
            argv=(
                sys.executable,
                "-c",
                GUION,
                str(parcial),
                self.escribe,
                str(self.tarda_s),
                str(self.pasos),
                str(self.codigo_de_salida),
            ),
            ruta_de_salida=destino,
            timeout_s=self.timeout_s,
            analizador_de_progreso=analizar_progreso_de_gdal,
        )
        self.ultimo_plan = plan
        return plan


def analizar_progreso_de_gdal(linea: str) -> float | None:
    """Traduce una linea de progreso al estilo de GDAL a una fraccion.

    GDAL escribe `0...10...20...30...` en una sola linea que va creciendo. Se toma el ultimo
    numero que aparezca. Una linea que no hable de progreso devuelve `None` y acaba en la
    bitacora, que es lo correcto: perder un mensaje de aviso por no entenderlo seria peor
    que no leer el progreso.
    """
    numeros = [
        trozo for trozo in linea.replace(".", " ").split() if trozo.isdigit() and len(trozo) <= 3
    ]
    if not numeros:
        return None
    valor = int(numeros[-1])
    if not 0 <= valor <= 100:
        return None
    return valor / 100.0
