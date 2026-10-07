"""Dónde cae un archivo en el mundo: las esquinas de su huella, en su sistema y en EPSG:4326.

Se saca de lo que la **cabecera** ya dice (origen y escala de un GeoTIFF, mínimos y máximos de
un LAS), sin abrir los píxeles ni los puntos. No adivina nada (regla 3 de `AGENTS.md`): sin
sistema de referencia conocido no hay huella, porque unas coordenadas sin sistema no dicen
dónde está nada. Y una imagen girada (con matriz de transformación) tampoco: solo se dibuja lo
que la cabecera asegura.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

#: Orden de las esquinas, igual en las dos listas: noroeste, noreste, sureste, suroeste.
ESQUINAS = ("noroeste", "noreste", "sureste", "suroeste")


@dataclass(frozen=True)
class Huella:
    sistema: str
    #: (x, y) en el sistema del archivo, en el orden de `ESQUINAS`.
    en_su_sistema: tuple[tuple[float, float], ...]
    #: (longitud, latitud) en grados, EPSG:4326, en el mismo orden.
    en_grados: tuple[tuple[float, float], ...]

    @property
    def esquinas(self) -> list[dict]:
        return [
            {"nombre": nombre, "x": xy[0], "y": xy[1], "lon": ll[0], "lat": ll[1]}
            for nombre, xy, ll in zip(ESQUINAS, self.en_su_sistema, self.en_grados, strict=True)
        ]


def _rectangulo(x0: float, y0: float, x1: float, y1: float) -> tuple[tuple[float, float], ...]:
    """Noroeste, noreste, sureste, suroeste de una caja `x0 <= x1`, `y0 <= y1`."""
    return ((x0, y1), (x1, y1), (x1, y0), (x0, y0))


@lru_cache(maxsize=32)
def _transformador(sistema: str):
    from pyproj import Transformer

    return Transformer.from_crs(sistema, "EPSG:4326", always_xy=True)


def a_grados(sistema: str, puntos) -> tuple[tuple[float, float], ...]:
    """Las coordenadas de `sistema` a (longitud, latitud). `always_xy`: sin orden de ejes."""
    transformador = _transformador(sistema)
    return tuple(tuple(transformador.transform(x, y)) for x, y in puntos)


def de_inspeccion(inspeccion) -> Huella | None:
    """La huella de lo inspeccionado, o `None` si la cabecera no basta para dibujarla."""
    if not inspeccion.crs.conocido or inspeccion.crs.es_local:
        return None

    rect = None
    tiff = inspeccion.tiff
    las = inspeccion.las
    if tiff is not None and tiff.origen and tiff.escala_pixel:
        x0, y1 = tiff.origen
        ancho = tiff.ancho_px * tiff.escala_pixel[0]
        alto = tiff.alto_px * tiff.escala_pixel[1]
        rect = _rectangulo(x0, y1 - alto, x0 + ancho, y1)
    elif las is not None:
        rect = _rectangulo(las.minimo[0], las.minimo[1], las.maximo[0], las.maximo[1])
    if rect is None:
        return None

    sistema = str(inspeccion.crs)
    try:
        grados = a_grados(sistema, rect)
    except Exception:
        # Un código que PROJ no conoce: sin huella, que es peor que nada solo si se inventa.
        return None
    if not all(-180 <= lon <= 180 and -90 <= lat <= 90 for lon, lat in grados):
        return None
    return Huella(sistema=sistema, en_su_sistema=rect, en_grados=grados)
