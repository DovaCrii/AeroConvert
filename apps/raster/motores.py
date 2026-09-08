"""Motores raster.

Por ahora solo se declara **que pares se saben hacer y si la maquina puede** -- que es lo
que la matriz de capacidades y la tira de veredictos necesitan. Construir el `argv` y
ejecutarlo llega con el modelo de trabajo, en las fases F1.2 y F1.5.

Declararlo ya no es adelantarse: es lo que permite que la pantalla de motores diga la
verdad sobre esta instalacion desde el primer dia, incluido el «ECW: falta la clave OEM».
"""

from __future__ import annotations

from pathlib import Path

from apps.engines import registry
from apps.engines.base import Disponibilidad, Motor, ParDeFormatos, PlanDeEjecucion

#: Origenes raster que GDAL sabe leer en esta version.
ORIGENES = ("geotiff", "bigtiff", "cog", "jp2", "img", "asc", "png", "jpeg", "mrsid", "ecw")
#: Destinos que GDAL escribe sin licencia de nadie.
DESTINOS_LIBRES = ("geotiff", "bigtiff", "cog", "jp2", "img", "asc", "png", "webp")


class MotorGdalRaster(Motor):
    """Conversion raster con GDAL. Es el caballo de tiro del producto."""

    id = "gdal-raster"
    nombre = "GDAL"
    familia = "raster"
    prioridad = 10

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(
            ParDeFormatos(origen, destino) for origen in ORIGENES for destino in DESTINOS_LIBRES
        )

    def disponibilidad(self) -> Disponibilidad:
        from apps.engines import sondas

        gdal = sondas.sondar_gdal()
        if not gdal.disponible:
            return Disponibilidad.no(
                "motor-no-disponible", gdal.motivo, sugerencia="Ver INSTALL.md."
            )
        proj = sondas.sondar_proj()
        if not proj.disponible:
            return Disponibilidad.no(
                proj.codigo_motivo, proj.mensaje, sugerencia=proj.sugerencia, version=gdal.version
            )
        return Disponibilidad.si(gdal.version)

    def plan(self, trabajo) -> PlanDeEjecucion:  # pragma: no cover - fase F1.5
        raise NotImplementedError("El plan de ejecucion llega en la fase F1.5.")


class MotorEcw(Motor):
    """ECW aparte, y no como un destino mas de GDAL.

    Separarlo es lo que permite que su celda tenga **su propio motivo**. Si ECW fuera un
    destino mas del motor GDAL, al faltar la clave la fila entera se apagaria con el motivo
    equivocado -- y GDAL si esta.
    """

    id = "gdal-ecw"
    nombre = "GDAL con SDK de Hexagon"
    familia = "raster"
    prioridad = 20

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(ParDeFormatos(origen, "ecw") for origen in ORIGENES)

    def disponibilidad(self) -> Disponibilidad:
        from apps.engines import sondas

        return sondas.sondar_ecw()

    def plan(self, trabajo) -> PlanDeEjecucion:  # pragma: no cover - fase F1.6
        raise NotImplementedError("El plan de ejecucion llega en la fase F1.6.")

    def verificar(self, trabajo, salida: Path):  # pragma: no cover - fase F1.6
        return super().verificar(trabajo, salida)


def registrar_todos() -> None:
    registry.registrar(MotorGdalRaster())
    registry.registrar(MotorEcw())
