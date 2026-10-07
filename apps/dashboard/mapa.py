"""La huella de un archivo sobre una retícula de coordenadas, sin mapa base (F13.11, D5).

Se dibuja en el servidor como un SVG sencillo: **no hay biblioteca de mapas, ni teselas, ni
petición a ningún sitio**; nada sale del equipo y no hay nada que vendorizar. La retícula son
meridianos y paralelos con su valor escrito, y la huella es el polígono de las cuatro
esquinas. Proyección plana (longitud corregida por el coseno de la latitud): sirve para ver la
forma y la posición relativa, no para medir.
"""

from __future__ import annotations

import math

ANCHO = 440
ALTO = 280
MARGEN_X = 54
MARGEN_Y = 26


def _paso(extension: float) -> float:
    """Un paso «redondo» (1, 2 o 5 por una potencia de diez) que da unas 4 líneas."""
    bruto = max(extension / 4, 1e-9)
    potencia = 10 ** math.floor(math.log10(bruto))
    for factor in (1, 2, 5, 10):
        if bruto <= factor * potencia:
            return factor * potencia
    return 10 * potencia  # pragma: no cover - el bucle siempre termina en 10


def _lineas(minimo: float, maximo: float, paso: float) -> list[float]:
    primero = math.ceil(minimo / paso - 1e-9)
    ultimo = math.floor(maximo / paso + 1e-9)
    return [round(i * paso, 10) for i in range(primero, ultimo + 1)]


def _decimales(paso: float) -> int:
    return max(0, -math.floor(math.log10(paso) + 1e-9))


def _grados(valor: float, decimales: int, positivo: str, negativo: str) -> str:
    return f"{abs(valor):.{decimales}f}° {positivo if valor >= 0 else negativo}"


def dibujo(grados: tuple[tuple[float, float], ...]) -> dict:
    """Los datos para pintar el SVG: polígono, meridianos y paralelos con su texto."""
    lons = [p[0] for p in grados]
    lats = [p[1] for p in grados]
    lon_min, lon_max = min(lons), max(lons)
    lat_min, lat_max = min(lats), max(lats)
    centro_lat = (lat_min + lat_max) / 2
    coseno = max(math.cos(math.radians(centro_lat)), 0.05)

    # Un archivo de un punto o de una línea no tiene área: se le da un mínimo para que se vea.
    ancho_lon = max(lon_max - lon_min, 1e-6)
    alto_lat = max(lat_max - lat_min, 1e-6)
    relleno_lon = ancho_lon * 0.25
    relleno_lat = alto_lat * 0.25
    v_lon_min, v_lon_max = lon_min - relleno_lon, lon_max + relleno_lon
    v_lat_min, v_lat_max = lat_min - relleno_lat, lat_max + relleno_lat

    area_x = ANCHO - 2 * MARGEN_X
    area_y = ALTO - 2 * MARGEN_Y
    escala = min(area_x / ((v_lon_max - v_lon_min) * coseno), area_y / (v_lat_max - v_lat_min))
    ancho_px = (v_lon_max - v_lon_min) * coseno * escala
    alto_px = (v_lat_max - v_lat_min) * escala
    x0 = (ANCHO - ancho_px) / 2
    y0 = (ALTO - alto_px) / 2

    def x(lon: float) -> float:
        return x0 + (lon - v_lon_min) * coseno * escala

    def y(lat: float) -> float:
        return y0 + (v_lat_max - lat) * escala

    paso_lon = _paso(v_lon_max - v_lon_min)
    paso_lat = _paso(v_lat_max - v_lat_min)
    dec_lon, dec_lat = _decimales(paso_lon), _decimales(paso_lat)

    return {
        "ancho": ANCHO,
        "alto": ALTO,
        "caja": {
            "x": round(x0, 1),
            "y": round(y0, 1),
            "w": round(ancho_px, 1),
            "h": round(alto_px, 1),
            "derecha": round(x0 + ancho_px, 1),
            "abajo": round(y0 + alto_px, 1),
        },
        "poligono": " ".join(f"{x(lon):.1f},{y(lat):.1f}" for lon, lat in grados),
        "meridianos": [
            {"x": round(x(v), 1), "texto": _grados(v, dec_lon, "E", "O")}
            for v in _lineas(v_lon_min, v_lon_max, paso_lon)
        ],
        "paralelos": [
            {"y": round(y(v), 1), "texto": _grados(v, dec_lat, "N", "S")}
            for v in _lineas(v_lat_min, v_lat_max, paso_lat)
        ],
    }
