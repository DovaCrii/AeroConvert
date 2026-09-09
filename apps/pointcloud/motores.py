"""Motores de nubes de puntos, con PDAL.

## Por qué PDAL y no el script portado de AeroBim

El plan decía portar `AeroBim/apps/web/scripts/a-copc.py`, que construye el octree COPC a
mano con `laspy` y `copclib`. Cuando se fue a hacer resultó que **el PDAL instalado ya trae
`writers.copc`**, así que LAS → COPC es un solo comando en vez de 371 líneas de octree.

Portarlo habría sido reescribir lo que la herramienta ya hace, y con más superficie donde
equivocarse. Lo que sí se hereda del script es lo que no es código: la regla de que el CRS
no se adivina, y el hallazgo de la precisión en `float32`.

## Las dos reglas propias de esta familia

**Aquí un CRS ausente es detención dura, sin excepción.** En ráster se admite convertir sin
georreferencia — un TIFF suelto a un COG suelto es legítimo. En nubes no: una nube sin CRS
no se puede cruzar con nada, y el dato se pierde para siempre si nadie lo apunta al
entregarla. Es la regla escrita en `AeroBim/docs/NUBES_DE_PUNTOS.md`.

**PDAL no habla mientras trabaja.** No emite avance por ninguna vía usable desde un
subproceso, así que el plan lo declara con `emite_progreso=False`. Sin eso, el detector de
atasco del runner mataría un trabajo sano en cuanto pasara del umbral de silencio.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from django.conf import settings

from apps.engines import registry
from apps.engines.base import (
    Disponibilidad,
    Motor,
    OpcionDeMotor,
    ParDeFormatos,
    PlanDeEjecucion,
    Verificacion,
    ruta_parcial,
)

ORIGENES = ("las", "laz", "copc", "ply", "xyz_nube")
DESTINOS = ("copc", "laz", "las", "ply", "xyz_nube")

#: El escritor de PDAL para cada código del catálogo. Se pasa **explícito** aunque
#: `ruta_parcial()` conserve la extensión: `.laz` no dice si se quiere un LAZ corriente o un
#: COPC, y esa es justo la distinción que importa.
ESCRITOR = {
    "copc": "writers.copc",
    "laz": "writers.las",
    "las": "writers.las",
    "ply": "writers.ply",
    "xyz_nube": "writers.text",
}

#: Segundos por millón de puntos. Medido con PDAL 2.10 sobre la nube de referencia:
#: 9,6 millones de puntos a COPC. Generoso a propósito -- el presupuesto total es el único
#: detector que queda cuando la herramienta no habla.
SEGUNDOS_POR_MILLON = 12.0


def _bin() -> str:
    """Dónde está `pdal`. Configuración primero, PATH después."""
    carpeta = (getattr(settings, "PDAL_BIN", "") or "").strip().strip('"')
    if carpeta:
        candidato = Path(carpeta) / ("pdal.exe" if os.name == "nt" else "pdal")
        if candidato.is_file():
            return str(candidato)
    return shutil.which("pdal") or "pdal"


class MotorPdalNubes(Motor):
    """Conversión de nubes con `pdal translate`."""

    id = "pdal-nubes"
    nombre = "PDAL"
    familia = "nube"
    prioridad = 10

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(
            ParDeFormatos(origen, destino)
            for origen in ORIGENES
            for destino in DESTINOS
            # Convertir algo a sí mismo no es una conversión; ofrecerlo llenaría la matriz
            # de celdas que no significan nada.
            if origen != destino
        )

    def disponibilidad(self) -> Disponibilidad:
        from apps.engines import sondas

        return sondas.sondar_pdal()

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        comunes = (
            OpcionDeMotor(
                "separacion_minima_m",
                "Diezmar a una separación mínima",
                "decimal",
                por_defecto=0.0,
                minimo=0.0,
                maximo=10.0,
                ayuda=(
                    "Metros entre puntos vecinos. 0 no diezma. Es lo que de verdad se mira "
                    "para decidir: «un punto cada 5 cm» se entiende, «cuatrocientos por "
                    "metro cuadrado» hay que traducirlo."
                ),
            ),
        )
        if par.destino in ("las", "laz", "copc"):
            return (
                *comunes,
                OpcionDeMotor(
                    "conservar_metadatos",
                    "Conservar los metadatos del original",
                    "booleano",
                    por_defecto=True,
                    ayuda="Pasa los VLR y la cabecera al archivo nuevo.",
                ),
            )
        return comunes

    def plan(self, trabajo) -> PlanDeEjecucion:
        origen = Path(trabajo.source_path)
        destino = Path(trabajo.output_path)
        parcial = ruta_parcial(destino)
        opciones = dict(trabajo.options or {})

        argv: list[str] = [_bin(), "translate", str(origen), str(parcial)]

        # Las etapas van nombradas y en orden: reproyectar antes de diezmar, porque diezmar
        # por radio en grados no significa nada.
        etapas: list[str] = []
        if trabajo.target_crs_code:
            etapas.append("reprojection")
        separacion = float(opciones.get("separacion_minima_m") or 0)
        if separacion > 0:
            etapas.append("sample")
        argv += etapas

        argv += ["-w", ESCRITOR.get(trabajo.target_format_code, "writers.las")]

        if trabajo.target_crs_code:
            autoridad = trabajo.target_crs_authority or "EPSG"
            argv += [
                f"--filters.reprojection.out_srs={autoridad}:{trabajo.target_crs_code}",
                f"--filters.reprojection.in_srs={trabajo.source_crs_authority or 'EPSG'}"
                f":{trabajo.source_crs_code}",
            ]
        if separacion > 0:
            argv += [f"--filters.sample.radius={separacion}"]

        if trabajo.target_format_code == "laz":
            argv += ["--writers.las.compression=laszip"]
        elif trabajo.target_format_code == "las":
            argv += ["--writers.las.compression=none"]

        if trabajo.target_format_code in ("las", "laz", "copc") and opciones.get(
            "conservar_metadatos"
        ):
            # **El nombre del escritor tiene que ser el que se pasó en `-w`.** Pedir
            # `--writers.las.forward` cuando el escritor es `writers.copc` no se ignora:
            # PDAL responde «Argument references invalid/unused stage» y no escribe nada.
            escritor = ESCRITOR.get(trabajo.target_format_code, "writers.las")
            argv += [f"--{escritor}.forward=all"]

        return PlanDeEjecucion(
            argv=tuple(argv),
            ruta_de_salida=destino,
            posteriores=(),
            env={},
            timeout_s=self._presupuesto(trabajo),
            # PDAL no dice nada mientras trabaja. Ver el docstring del módulo.
            analizador_de_progreso=None,
            emite_progreso=False,
        )

    def _presupuesto(self, trabajo) -> int:
        from apps.formats import las as las_mod

        millones = 10.0
        try:
            millones = max(1.0, las_mod.leer_cabecera(Path(trabajo.source_path)).puntos / 1e6)
        except (OSError, las_mod.NoEsLas, ValueError):
            pass
        por_giga = getattr(settings, "SEGUNDOS_POR_GB", 900)
        return int(
            max(600, millones * SEGUNDOS_POR_MILLON, (trabajo.source_size_bytes / 1e9) * por_giga)
        )

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        """Se le pregunta a PDAL cuántos puntos quedaron y dónde.

        Y **se comprueba que no se hayan perdido puntos sin haberlo pedido**. Es el fallo
        silencioso propio de esta familia: una conversión que se come la mitad de la nube
        deja un archivo que abre, se ve bien, y le falta media obra.
        """
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

        detalles = {
            "puntos": resumen.get("num_points", 0),
            "bytes": salida.stat().st_size,
        }
        limites = resumen.get("bounds") or {}
        if limites:
            detalles["extension_m"] = [
                round(limites.get("maxx", 0) - limites.get("minx", 0), 3),
                round(limites.get("maxy", 0) - limites.get("miny", 0), 3),
                round(limites.get("maxz", 0) - limites.get("minz", 0), 3),
            ]

        esperados = _puntos_de_origen(trabajo)
        diezmado = float((trabajo.options or {}).get("separacion_minima_m") or 0) > 0
        if esperados and not diezmado and detalles["puntos"] < esperados * 0.999:
            return Verificacion(
                correcta=False,
                motivo=(
                    f"El original tenía {esperados:,} puntos y la salida tiene "
                    f"{detalles['puntos']:,}. No se pidió diezmar."
                ).replace(",", "."),
                codigo_motivo="salida-invalida",
                detalles=detalles,
            )

        if esperados:
            detalles["puntos_origen"] = esperados
        return Verificacion(correcta=True, detalles=detalles)


def _puntos_de_origen(trabajo) -> int:
    from apps.formats import las as las_mod

    try:
        return las_mod.leer_cabecera(Path(trabajo.source_path)).puntos
    except (OSError, las_mod.NoEsLas, ValueError):
        return 0


def _pdal_info(ruta: Path) -> dict | None:
    try:
        resultado = subprocess.run(  # nosec B603
            [_bin(), "info", "--summary", str(ruta)],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if resultado.returncode != 0 or not resultado.stdout:
        return None
    try:
        return json.loads(resultado.stdout).get("summary", {})
    except (json.JSONDecodeError, AttributeError):
        return None


class MotorPdalE57(MotorPdalNubes):
    """E57, separado del motor general por la misma razón que ECW lo está del de ráster.

    Si E57 fuera un origen más de `pdal-nubes`, al faltar su controlador se apagaría la fila
    entera con el motivo equivocado — y PDAL sí está. Separarlo permite que su celda diga
    exactamente qué pasa: **los controladores de PDAL se fijan al compilarlo**, y el que
    trae QGIS no incluye E57.
    """

    id = "pdal-e57"
    nombre = "PDAL con E57"
    prioridad = 20

    def pares(self) -> frozenset[ParDeFormatos]:
        hacia = frozenset(ParDeFormatos("e57", destino) for destino in DESTINOS)
        desde = frozenset(ParDeFormatos(origen, "e57") for origen in ORIGENES)
        return hacia | desde

    def disponibilidad(self) -> Disponibilidad:
        from apps.engines import sondas

        return sondas.sondar_pdal_controlador("readers.e57")


class MotorReCap(Motor):
    """ReCap de Autodesk: declara los pares **para poder decir que no se pueden**.

    No convierte nada y no va a convertir nada. Existe para que soltar un `.rcs` dé una
    respuesta útil — «esto sale de ReCap, expórtalo a E57 o LAS»— en vez de «formato no
    reconocido», que suena a fallo de la aplicación cuando es una decisión de Autodesk.

    Es la misma idea que la matriz en tres estados: una capacidad que nadie puede dar y una
    que falta instalar no son lo mismo, y la primera merece un remedio escrito igual que la
    segunda.
    """

    id = "recap"
    nombre = "Autodesk ReCap"
    familia = "nube"
    prioridad = 90

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(
            ParDeFormatos(origen, destino)
            for origen in ("rcs", "rcp")
            for destino in ("las", "laz", "copc", "e57")
        )

    def disponibilidad(self) -> Disponibilidad:
        return Disponibilidad.nunca(
            "formato-propietario",
            "RCS y RCP son binarios cerrados de Autodesk: no hay ningún lector abierto.",
            sugerencia=(
                "Ábrelo en ReCap Pro y usa Exportar → E57 (o LAS). Ese archivo sí se "
                "convierte aquí."
            ),
            alternativas=("e57", "las", "laz"),
        )

    def plan(self, trabajo) -> PlanDeEjecucion:  # pragma: no cover - nunca esta disponible
        raise NotImplementedError("RCS y RCP no se pueden leer sin ReCap.")


def registrar_todos() -> None:
    registry.registrar(MotorPdalNubes())
    registry.registrar(MotorPdalE57())
    registry.registrar(MotorReCap())
