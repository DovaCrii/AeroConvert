"""Recorte de una nube de puntos por un polígono, con `pdal translate` y `filters.crop` (F21.3).

Es un **proceso** (`operacion = "recorte"`), no una conversión: ver
`apps/raster/procesar.py`. Un LAZ a
un LAZ ya lo sabe `pdal-nubes`; este motor se pide con `options["operacion"] = "recorte"`.

## Las reglas, aquí

- **El CRS no se adivina.** El polígono lleva su CRS declarado y la nube tiene que declarar el suyo.
  Si son distintos, los vértices se llevan al de la nube con `pyproj`
  (`poligono.llevar_a`) **antes**
  de pasárselos a PDAL: así `filters.crop` recibe coordenadas en el sistema en que están los puntos
  y no hay una reproyección implícita que nadie vea.
- **El código de salida no es la prueba.** `verificar` le pregunta a `pdal info --summary`: que
  queden puntos (`recorte-vacio` si no), que ninguno caiga fuera de la caja del polígono y que no
  haya más puntos que en el original.
- **El original no se toca:** PDAL lo lee; la salida va a `<destino>.parcial`.
"""

from __future__ import annotations

from pathlib import Path

from apps.engines import registry
from apps.engines.base import (
    Disponibilidad,
    Motor,
    OpcionDeMotor,
    ParDeFormatos,
    PlanDeEjecucion,
    PlanNoValido,
    Verificacion,
    ruta_parcial,
)
from apps.formats import crs as crs_mod
from apps.formats import poligono

from .motores import ESCRITOR, MotorPdalNubes, _bin, _pdal_info, _puntos_de_origen

RECORTE = "recorte"

#: Lo que PDAL lee y escribe sin más. PLY y texto no llevan CRS: no se recortan por un polígono.
FORMATOS_DE_RECORTE = ("las", "laz", "copc")

#: Cuánto puede asomar un punto fuera de la caja del polígono: la escala del LAS (1 mm) redondea.
TOLERANCIA_M = 0.01


class MotorRecorteNube(Motor):
    """`filters.crop` con un polígono: se queda con los puntos de dentro."""

    id = "pdal-recorte"
    nombre = "PDAL (recorte por polígono)"
    familia = "nube"
    prioridad = 10
    operacion = RECORTE

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(
            ParDeFormatos(origen, destino)
            for origen in FORMATOS_DE_RECORTE
            for destino in FORMATOS_DE_RECORTE
        )

    def disponibilidad(self) -> Disponibilidad:
        from apps.engines import sondas

        # No basta con que PDAL esté: tiene que traer el filtro (los filtros se fijan al compilar).
        return sondas.sondar_pdal_controlador("filters.crop")

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        return (
            OpcionDeMotor(
                "recorte_crs",
                "Sistema de referencia del polígono",
                "texto",
                por_defecto=None,
                ayuda=(
                    "El EPSG de las coordenadas de los vértices (por ejemplo EPSG:32719). Sin "
                    "valor "
                    "por omisión: con otro sistema, el recorte cae en otro sitio. Si es distinto "
                    "del de la nube, los vértices se llevan al de la nube antes de recortar."
                ),
            ),
            OpcionDeMotor(
                "recorte_vertices",
                "Vértices del polígono",
                "texto",
                por_defecto=None,
                ayuda="Un vértice por línea o separados por «;», «este norte», con punto decimal.",
            ),
        )

    def plan(self, trabajo) -> PlanDeEjecucion:
        origen = Path(trabajo.source_path)
        destino = Path(trabajo.output_path)
        parcial = ruta_parcial(destino)
        opciones = dict(trabajo.options or {})

        if not trabajo.source_crs_code:
            raise PlanNoValido(
                "La nube no declara su sistema de referencia: no se sabe dónde cae el polígono.",
                "crs-ausente",
            )
        anillo = poligono.anillo_de_opciones(opciones)
        nube = crs_mod.epsg(trabajo.source_crs_code)
        en_la_nube = poligono.llevar_a(anillo, nube)
        wkt = poligono.a_wkt(en_la_nube)

        escritor = ESCRITOR.get(trabajo.target_format_code, "writers.las")
        argv = [
            _bin(),
            "translate",
            str(origen),
            str(parcial),
            "crop",
            "-w",
            escritor,
            f"--filters.crop.polygon={wkt}",
        ]
        if trabajo.target_format_code == "laz":
            argv += ["--writers.las.compression=laszip"]
        elif trabajo.target_format_code == "las":
            argv += ["--writers.las.compression=none"]
        if trabajo.target_format_code in FORMATOS_DE_RECORTE:
            # Misma regla que `pdal-nubes`: el nombre del escritor tiene que ser el de `-w`.
            argv += [f"--{escritor}.forward=all"]

        return PlanDeEjecucion(
            argv=tuple(argv),
            ruta_de_salida=destino,
            env={},
            timeout_s=MotorPdalNubes()._presupuesto(trabajo),
            analizador_de_progreso=None,
            emite_progreso=False,
        )

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        base = super().verificar(trabajo, salida)
        if not base.correcta:
            return base
        resumen = _pdal_info(salida)
        if resumen is None:
            return Verificacion(
                correcta=False,
                motivo="PDAL no puede leer la nube que acaba de escribir.",
                codigo_motivo="salida-invalida",
            )
        puntos = int(resumen.get("num_points", 0) or 0)
        detalles = {"puntos": puntos, "bytes": salida.stat().st_size}
        esperados = _puntos_de_origen(trabajo)
        if esperados:
            detalles["puntos_origen"] = esperados
        if puntos == 0:
            return Verificacion(
                correcta=False,
                motivo=(
                    "El recorte quedó sin un solo punto: el polígono no toca la nube. Compruebe su "
                    "posición y el sistema de referencia que declaró."
                ),
                codigo_motivo="recorte-vacio",
                detalles=detalles,
            )
        if esperados and puntos > esperados:
            return Verificacion(
                correcta=False,
                motivo=f"El recorte tiene más puntos ({puntos}) que el original ({esperados}).",
                codigo_motivo="salida-invalida",
                detalles=detalles,
            )
        # Ningún punto fuera de la caja del polígono (en el sistema de la nube).
        try:
            anillo = poligono.llevar_a(
                poligono.anillo_de_opciones(dict(trabajo.options or {})),
                crs_mod.epsg(trabajo.source_crs_code),
            )
        except PlanNoValido:
            return Verificacion(correcta=True, detalles=detalles)
        limites = resumen.get("bounds") or {}
        if limites:
            este = [p.x_m for p in anillo]
            norte = [p.y_m for p in anillo]
            fuera = (
                limites.get("minx", min(este)) < min(este) - TOLERANCIA_M
                or limites.get("maxx", max(este)) > max(este) + TOLERANCIA_M
                or limites.get("miny", min(norte)) < min(norte) - TOLERANCIA_M
                or limites.get("maxy", max(norte)) > max(norte) + TOLERANCIA_M
            )
            if fuera:
                return Verificacion(
                    correcta=False,
                    motivo="Quedaron puntos fuera de la caja del polígono.",
                    codigo_motivo="salida-invalida",
                    detalles=detalles,
                )
        return Verificacion(correcta=True, detalles=detalles)


def registrar() -> None:
    registry.registrar(MotorRecorteNube())
