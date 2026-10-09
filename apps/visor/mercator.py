"""La cuadrícula de teselas XYZ en EPSG:3857 (Web Mercator), solo matemática.

Es la cuadrícula de siempre de los mapas en la web («slippy map»): en el nivel `z` el mundo es un
cuadrado de `2**z` por `2**z` teselas de 256 × 256 píxeles, con la tesela `0/0` arriba a la
izquierda (noroeste) y `y` creciendo **hacia el sur**. El cuadrado va de -20 037 508,34 a
+20 037 508,34 m en los dos ejes, que es `π` por el radio de la esfera de WGS84.

No hay biblioteca de mapas ni GDAL aquí: la prueba de este módulo compara con valores conocidos
y con fórmulas escritas aparte, y la del oráculo, con `gdalwarp`.
"""

from __future__ import annotations

import math

#: Radio de la esfera de Web Mercator, en metros. Es el semieje mayor de WGS84.
RADIO_M = 6378137.0

#: Medio lado del mundo, en metros: `π · R`.
ORIGEN_M = math.pi * RADIO_M

LADO_PX = 256

#: El nivel más profundo que se sirve. 24 ya es unos 0,009 m por píxel en el ecuador.
ZOOM_MAXIMO = 24

#: Al norte y al sur de esta latitud Web Mercator no existe (la proyección se va al infinito).
LATITUD_MAXIMA = 85.0511287798066

#: Metros por píxel en el nivel 0.
RESOLUCION_NIVEL_0_M = 2 * ORIGEN_M / LADO_PX


def resolucion_m(z: float) -> float:
    """Metros por píxel en el nivel `z` (en el ecuador de la proyección)."""
    return RESOLUCION_NIVEL_0_M / (2.0**z)


def es_valida(z: int, x: int, y: int) -> bool:
    """¿Existe esa tesela? `0 <= z <= 24` y `0 <= x, y < 2**z`."""
    if not 0 <= z <= ZOOM_MAXIMO:
        return False
    lado = 1 << z
    return 0 <= x < lado and 0 <= y < lado


def caja_de_tesela(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """`(x_min, y_min, x_max, y_max)` de la tesela, en metros de EPSG:3857."""
    if not es_valida(z, x, y):
        raise ValueError(f"No existe la tesela {z}/{x}/{y}.")
    lado_m = 2 * ORIGEN_M / (1 << z)
    x_min = -ORIGEN_M + x * lado_m
    y_max = ORIGEN_M - y * lado_m
    return (x_min, y_max - lado_m, x_min + lado_m, y_max)


def lonlat_a_mercator(lon: float, lat: float) -> tuple[float, float]:
    """Longitud y latitud en grados a metros de EPSG:3857. Falla fuera de ±85,05° de latitud."""
    if not -LATITUD_MAXIMA <= lat <= LATITUD_MAXIMA:
        raise ValueError(f"Web Mercator no llega a la latitud {lat}.")
    x = RADIO_M * math.radians(lon)
    y = RADIO_M * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return (x, y)


def mercator_a_lonlat(x: float, y: float) -> tuple[float, float]:
    """Metros de EPSG:3857 a (longitud, latitud) en grados."""
    lon = math.degrees(x / RADIO_M)
    lat = math.degrees(2 * math.atan(math.exp(y / RADIO_M)) - math.pi / 2)
    return (lon, lat)


def tesela_de_lonlat(lon: float, lat: float, z: int) -> tuple[int, int]:
    """La tesela del nivel `z` que contiene ese punto."""
    mx, my = lonlat_a_mercator(lon, lat)
    lado = 1 << z
    tx = int((mx + ORIGEN_M) / (2 * ORIGEN_M) * lado)
    ty = int((ORIGEN_M - my) / (2 * ORIGEN_M) * lado)
    return (min(max(tx, 0), lado - 1), min(max(ty, 0), lado - 1))


def se_cruzan(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    """¿Dos cajas `(x_min, y_min, x_max, y_max)` comparten área? Tocarse en el borde no cuenta."""
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]
