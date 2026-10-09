"""GDAL, ejecutado aparte, para el visor.

**GDAL no es una dependencia del paquete**: se sondea y se lanza como programa externo, igual que
en `apps/raster/motores.py`. Aquí no hay `osgeo` ni `import gdal`. Todo subproceso va con lista de
argumentos, sin `shell=True` y con plazo; nada que escribe la persona llega a una línea de órdenes
(la ruta ya pasó por `entrada.resolver`, que la comprobó contra las raíces permitidas).

## Qué se le cambia al entorno del hijo

- `GDAL_PAM_ENABLED=NO`: sin esto GDAL escribe un `.aux.xml` **junto al original** al calcular
  estadísticas. El original no se toca (regla 5): ni su contenido ni su carpeta.
- `GDAL_CACHEMAX` acotado, para que una tesela no se coma la memoria de la máquina.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass

from django.conf import settings

from apps.engines import sondas
from apps.engines.base import Disponibilidad
from apps.engines.entorno import entorno_de_gdal

registro = logging.getLogger(__name__)

#: Lo que el visor lanza. `gdalinfo` lee, `gdalwarp` corta y reproyecta, `gdal_translate` prepara
#: lo que no es de 8 bits, y `gdallocationinfo` lee el píxel bajo el cursor.
HERRAMIENTAS = ("gdalinfo", "gdalwarp", "gdal_translate", "gdallocationinfo")

#: Una tesela que tarda más que esto no se espera: un GeoTIFF sin pirámide de vistas previas y de
#: varios gigas hay que leerlo casi entero para achicarlo. El mensaje dice qué hacer.
PLAZO_TESELA_S = 90
PLAZO_INFO_S = 120
PLAZO_PIXEL_S = 30


class ErrorDeGdal(Exception):
    """GDAL no pudo hacer lo pedido. `codigo` es un motivo estable de `apps/jobs/motivos.py`."""

    def __init__(self, mensaje: str, codigo: str = "error-del-motor"):
        super().__init__(mensaje)
        self.codigo = codigo


def ejecutable(nombre: str) -> str | None:
    """Dónde está la herramienta: la carpeta configurada primero, el PATH después."""
    return sondas._ejecutable(nombre, getattr(settings, "GDAL_BIN", ""))


def disponibilidad() -> Disponibilidad:
    """¿Se puede cortar un mapa en teselas en esta máquina? Sin lanzar nada que no sea la sonda."""
    estado = sondas.sondar_gdal()
    if not estado.disponible:
        return Disponibilidad.no(
            "sin-gdal",
            "Esta máquina no tiene GDAL, que es lo que corta la imagen en teselas.",
            sugerencia=(
                "Instale GDAL (QGIS lo trae) y apunte AEROCONVERT_GDAL_BIN a su carpeta bin. "
                "Mientras tanto, la ficha del archivo en «Convertir» enseña dónde cae sobre una "
                "retícula de coordenadas."
            ),
        )
    faltan = [nombre for nombre in HERRAMIENTAS if ejecutable(nombre) is None]
    if faltan:
        return Disponibilidad.no(
            "sin-gdal",
            f"A este GDAL le falta {', '.join(faltan)}, que el mapa necesita.",
            sugerencia="Complete la instalación de GDAL; QGIS trae las cuatro herramientas.",
        )
    return Disponibilidad.si(estado.version)


def entorno(**extra: str) -> dict[str, str]:
    """El entorno del hijo: el del servidor más lo de GDAL. **No se toca el del servidor.**"""
    base = {**os.environ, **entorno_de_gdal()}
    base["GDAL_PAM_ENABLED"] = "NO"
    base.setdefault("GDAL_CACHEMAX", "256")
    base.update(extra)
    return base


@dataclass(frozen=True)
class Resultado:
    salida: str
    errores: str


def _sin_rutas(texto: str, argumentos: list[str]) -> str:
    """Quita del mensaje de GDAL las rutas del servidor que lo acompañan: queda solo el nombre.

    El mensaje llega a la pantalla; la carpeta de la obra, la caché o la de trabajo no son de
    nadie más. El detalle completo, si hace falta, se saca del registro del servidor.
    """
    for argumento in argumentos:
        if os.sep in argumento or "/" in argumento:
            texto = texto.replace(argumento, os.path.basename(argumento))
    return texto


def correr(nombre: str, argumentos: list[str], *, plazo_s: int) -> Resultado:
    """Lanza una herramienta de GDAL y devuelve lo que escribió.

    **El código de salida no es la prueba** (regla 1): aquí solo se distingue «ni arrancó» de
    «arrancó». Si el hijo sale con error se levanta `ErrorDeGdal`, pero que salga con `0` no quiere
    decir que haya hecho nada: lo que se comprueba después es el archivo que debía dejar.
    """
    programa = ejecutable(nombre)
    if programa is None:
        raise ErrorDeGdal(f"No se encontró {nombre}.", "sin-gdal")
    try:
        # `programa` sale de la configuración o del PATH; `argumentos` son literales del código y
        # rutas ya comprobadas. Lista y `shell=False`: no hay interpretación de metacaracteres.
        hecho = subprocess.run(  # nosec B603
            [programa, *argumentos],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=plazo_s,
            check=False,
            shell=False,
            env=entorno(),
        )
    except subprocess.TimeoutExpired as fallo:
        raise ErrorDeGdal(
            f"{nombre} tardó más de {plazo_s} s. Una imagen grande sin pirámide de vistas previas "
            "hay que leerla casi entera: conviértala a COG.",
            "tardo-demasiado",
        ) from fallo
    except OSError as fallo:
        raise ErrorDeGdal(f"No se pudo lanzar {nombre}: {fallo}", "error-del-motor") from fallo
    if hecho.returncode != 0:
        detalle = (hecho.stderr or hecho.stdout or "").strip().splitlines()
        registro.warning("%s salió con %s: %s", nombre, hecho.returncode, "\n".join(detalle[-5:]))
        ultima = _sin_rutas(detalle[-1], argumentos) if detalle else "sin mensaje"
        raise ErrorDeGdal(f"{nombre} terminó con error: {ultima}", "error-del-motor")
    return Resultado(salida=hecho.stdout or "", errores=hecho.stderr or "")
