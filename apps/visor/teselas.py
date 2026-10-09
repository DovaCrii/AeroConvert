"""Cortar una capa en teselas XYZ de 256 × 256 en EPSG:3857, con GDAL, a petición.

## El camino de una tesela

1. Si la tesela **no toca** la capa, se devuelve una transparente sin lanzar nada.
2. Si ya está en la caché, se devuelve (y se anota que alguien la miró).
3. Si no, `gdalwarp` la corta del original **en solo lectura** a un `.parcial-<id>`, se
   **verifica** (que exista, que la abra Pillow y que mida 256 × 256: el código de salida de GDAL
   no es la prueba) y solo entonces se renombra con `os.replace()` (reglas 1 y 5 de `AGENTS.md`).

## Qué no hace

- No escribe junto al original ni le toca el `mtime`.
- No usa teselas de ningún servidor (D5): todo sale del archivo.
- No lanza más de `HILOS_DE_GDAL` cortes a la vez: un navegador pide una docena de teselas de golpe
  y GDAL ya usa varios núcleos por su cuenta.
"""

from __future__ import annotations

import io
import threading
from functools import lru_cache
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from . import cache, mercator, motor
from .capa import TIPO_DE_8_BITS, Capa

LADO_PX = mercator.LADO_PX

#: Cuántos `gdalwarp` a la vez como mucho, entre todas las peticiones del proceso.
HILOS_DE_GDAL = 3

_cupo = threading.BoundedSemaphore(HILOS_DE_GDAL)

#: El remuestreo. Bilineal: suave al acercar y razonable al alejar con pirámide de vistas previas
#: (GDAL elige la más cercana solo).
REMUESTREO = "bilinear"


@lru_cache(maxsize=1)
def tesela_vacia() -> bytes:
    """Un PNG transparente de 256 × 256, para lo que cae fuera de la capa."""
    salida = io.BytesIO()
    Image.new("RGBA", (LADO_PX, LADO_PX), (0, 0, 0, 0)).save(salida, "PNG", optimize=True)
    return salida.getvalue()


def verificar_png(ruta: Path) -> None:
    """Comprueba la salida **leyéndola**, no mirando cómo terminó GDAL (regla 1).

    Levanta `ErrorDeGdal` con `sin-salida` si no hay nada y `salida-invalida` si lo que hay no es
    un PNG de 256 × 256 legible.
    """
    try:
        if not ruta.is_file() or ruta.stat().st_size == 0:
            raise motor.ErrorDeGdal("GDAL no dejó la tesela.", "sin-salida")
        with Image.open(ruta) as imagen:
            imagen.load()  # decodifica entera: un PNG cortado falla aquí y no en el navegador
            if imagen.format != "PNG" or imagen.size != (LADO_PX, LADO_PX):
                raise motor.ErrorDeGdal(
                    f"La tesela salió de {imagen.size[0]} × {imagen.size[1]} y no de "
                    f"{LADO_PX} × {LADO_PX}.",
                    "salida-invalida",
                )
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as fallo:
        raise motor.ErrorDeGdal(
            f"La tesela que dejó GDAL no se lee: {fallo}", "salida-invalida"
        ) from fallo


def _hay(ruta: Path) -> bool:
    try:
        return ruta.is_file() and ruta.stat().st_size > 0
    except OSError:  # el barrido la pudo borrar entre una pregunta y otra
        return False


def fuente_para(ruta: Path, capa: Capa, clave: str) -> Path:
    """Lo que se le da a `gdalwarp`: el original, o un VRT si no es una imagen de 8 bits.

    Un VRT es un **archivo nuestro** en la caché que apunta al original y le cambia la forma
    (escala a 8 bits, expande la paleta, elige tres bandas). El original no cambia.
    """
    if not capa.necesita_vrt:
        return ruta
    vrt = cache.carpeta_de(clave) / "fuente.vrt"
    if _hay(vrt):
        return vrt

    argumentos = ["-q", "-of", "VRT"]
    if capa.paleta:
        argumentos += ["-expand", "rgba"]
    else:
        if capa.tipo != TIPO_DE_8_BITS:
            minimo, maximo = capa.escala
            argumentos += ["-ot", "Byte", "-scale", repr(minimo), repr(maximo), "0", "255"]
        for banda in (1, 2, 3) if capa.bandas >= 3 else (1,):
            argumentos += ["-b", str(banda)]

    vrt.parent.mkdir(parents=True, exist_ok=True)
    parcial = cache.nombre_de_parcial(vrt)
    try:
        motor.correr(
            "gdal_translate", [*argumentos, str(ruta), str(parcial)], plazo_s=motor.PLAZO_INFO_S
        )
        if not parcial.is_file() or b"<VRTDataset" not in parcial.read_bytes()[:4096]:
            raise motor.ErrorDeGdal("GDAL no dejó la fuente de 8 bits.", "sin-salida")
        cache.reemplazar(parcial, vrt)
    finally:
        parcial.unlink(missing_ok=True)
    return vrt


def argumentos_de_corte(
    fuente: Path, destino: Path, caja: tuple[float, float, float, float]
) -> list[str]:
    """Los argumentos de `gdalwarp` para una tesela. Aparte para que se puedan leer y probar."""
    return [
        "-q",
        "-overwrite",
        "-of",
        "PNG",
        "-t_srs",
        "EPSG:3857",
        "-te",
        *(repr(valor) for valor in caja),
        "-ts",
        str(LADO_PX),
        str(LADO_PX),
        "-r",
        REMUESTREO,
        "-dstalpha",
        str(fuente),
        str(destino),
    ]


def tesela(ruta: Path, capa: Capa, clave: str, z: int, x: int, y: int) -> bytes:
    """El PNG de la tesela `z/x/y`, de la caché o recién cortado."""
    caja = mercator.caja_de_tesela(z, x, y)
    if not mercator.se_cruzan(caja, tuple(capa.caja_3857)):
        return tesela_vacia()

    destino = cache.carpeta_de(clave) / f"{z}-{x}-{y}.png"
    guardada = cache.leer(destino)
    if guardada is not None:
        return guardada

    with _cupo:
        guardada = cache.leer(destino)  # otro hilo pudo hacerla mientras se esperaba el cupo
        if guardada is not None:
            return guardada
        fuente = fuente_para(ruta, capa, clave)
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = cache.nombre_de_parcial(destino)
        try:
            motor.correr(
                "gdalwarp", argumentos_de_corte(fuente, parcial, caja), plazo_s=motor.PLAZO_TESELA_S
            )
            verificar_png(parcial)
            contenido = parcial.read_bytes()
            cache.reemplazar(parcial, destino)
        finally:
            parcial.unlink(missing_ok=True)
    cache.anotar_escritura(len(contenido))
    return contenido
