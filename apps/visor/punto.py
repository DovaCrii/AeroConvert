"""Qué hay bajo el cursor: coordenadas en el sistema del archivo, columna y fila, y el valor.

Es la mitad «de números» del visor. El navegador sabe la longitud y la latitud del cursor (es la
inversa de Web Mercator, que no depende del archivo); lo que **solo se puede decir con PROJ** es
dónde cae eso en el sistema del archivo, y por eso se pregunta aquí. Con una sola pregunta por
cursor quieto, no por cada píxel que se mueve.

**El punto lleva su sistema** (regla 3): lo que sale de aquí es siempre `(x, y)` **con** el nombre
del sistema al lado, y la entrada es `(lon, lat)` declarado como EPSG:4326, nunca un par suelto.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import dem, motor
from .capa import Capa


@dataclass(frozen=True)
class Punto:
    lon: float
    lat: float
    #: Coordenadas en el sistema del archivo (`Capa.sistema`).
    x: float
    y: float
    columna: float
    fila: float
    dentro: bool
    valores: tuple[float | None, ...] = ()


@lru_cache(maxsize=16)
def _del_mapa_al_archivo(wkt: str):
    from pyproj import CRS, Transformer

    return Transformer.from_crs("EPSG:4326", CRS.from_wkt(wkt), always_xy=True)


def localizar(capa: Capa, lon: float, lat: float) -> Punto:
    """Dónde cae un punto del mapa en el archivo. No lanza GDAL: es geometría."""
    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("Longitud o latitud fuera de rango.")
    x, y = _del_mapa_al_archivo(capa.wkt).transform(lon, lat)
    gt = capa.geotransform
    determinante = gt[1] * gt[5] - gt[2] * gt[4]
    if not (math.isfinite(x) and math.isfinite(y)) or determinante == 0:
        return Punto(lon, lat, math.nan, math.nan, math.nan, math.nan, False)
    dx, dy = x - gt[0], y - gt[3]
    columna = (gt[5] * dx - gt[2] * dy) / determinante
    fila = (-gt[4] * dx + gt[1] * dy) / determinante
    dentro = 0 <= columna < capa.ancho_px and 0 <= fila < capa.alto_px
    return Punto(lon, lat, x, y, columna, fila, dentro)


def con_valores(ruta: Path, capa: Capa, punto: Punto) -> Punto:
    """El mismo punto con el valor de cada banda, leído con `gdallocationinfo` del **original**.

    Se pregunta por la columna y la fila enteras que calculó `localizar`; que GDAL conteste con otro
    píxel que `gdallocationinfo -geoloc` es lo que vigila la prueba con oráculo. Lo que dice un
    valor sin dato no se inventa: sale como `None`.
    """
    if not punto.dentro:
        return punto
    columna, fila = int(math.floor(punto.columna)), int(math.floor(punto.fila))
    salida = motor.correr(
        "gdallocationinfo",
        ["-valonly", str(ruta), str(columna), str(fila)],
        plazo_s=motor.PLAZO_PIXEL_S,
    ).salida
    valores: list[float | None] = []
    for linea in salida.splitlines():
        texto = linea.strip()
        if not texto:
            continue
        try:
            valores.append(float(texto))
        except ValueError:
            valores.append(None)
    # El «sin dato» del modelo de terreno no es una cota (-9999 no es una altura): sale como `None`.
    if capa.es_dem and valores and valores[0] is not None:
        if dem.es_sin_dato(valores[0], sin_dato=capa.nodata, es_nan=capa.nodata_es_nan):
            valores[0] = None
    # `NaN` e infinitos no viajan en JSON: tampoco son un valor.
    valores = [v if v is None or math.isfinite(v) else None for v in valores]
    return Punto(**{**punto.__dict__, "valores": tuple(valores)})
