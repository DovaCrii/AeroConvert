"""Un modelo digital de elevación (DEM) en el visor: lo que se **lee** del archivo y nada más.

Son funciones puras, sin GDAL y sin importar `capa.py` (que las usa): reciben lo que dijo
`gdalinfo -json` o el `pyproj.CRS` del archivo.

## Qué es un DEM aquí

Una sola banda, **entera o flotante** (`Int16`, `UInt16`, `Int32`, `UInt32`, `Float32`, `Float64`),
sin paleta. Es una pista, no una certeza: una imagen de 16 bits de una banda también cumple, y por
eso el sombreado se ofrece junto a la imagen en grises, no en su lugar.

## Lo que no se supone (regla 3)

- **La unidad vertical** es la que declara la banda (`unit` de `gdalinfo`). Si no declara
  ninguna, no hay unidad: se dice «unidad no declarada» y nunca «metros» por costumbre.
- **La referencia vertical** (el geoide o el nivel de reducción) es la parte vertical del
  sistema del archivo **si lo trae compuesto** (horizontal + vertical, p. ej. UTM 19S + EGM96).
  Si no, «referencia vertical no declarada»: jamás «sobre el nivel del mar» por suponer. Una
  altura elipsoidal tampoco se llama «sobre el nivel del mar».
- **El sombreado sí necesita una razón vertical/horizontal** para calcular pendientes. Con la unidad
  declarada se usa; sin ella se supone la misma que la horizontal y la pantalla lo dice. Es solo
  el dibujo: ningún número que se lee del archivo depende de esa suposición.

## Textos que vienen del archivo

La unidad y el nombre de la referencia llegan de metadatos que escribió quien hizo el archivo, y van
a la pantalla y a un CSV. Se limpian aquí (`texto_seguro`): letras, cifras y unos pocos signos, y
nunca empiezan por `=`, `+`, `-` o `@` (que una hoja de cálculo leería como fórmula).
"""

from __future__ import annotations

import math
import re

TIPOS_DE_ELEVACION = frozenset({"Int16", "UInt16", "Int32", "UInt32", "Float32", "Float64"})

#: Metros por grado de GDAL (`gdaldem` usa 111120 en su documentación): solo para el sombreado.
METROS_POR_GRADO_DE_GDALDEM = 111120.0

#: Unidades verticales que se reconocen, en minúsculas, y su valor en metros.
UNIDADES_EN_METROS = {
    "m": 1.0,
    "metre": 1.0,
    "metres": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "ft": 0.3048,
    "foot": 0.3048,
    "feet": 0.3048,
    "international foot": 0.3048,
    "us survey foot": 1200 / 3937,
    "us-ft": 1200 / 3937,
    "ftus": 1200 / 3937,
}

_TEXTO_LIMPIO = re.compile(r"[^\w .,()/:\-+]", re.UNICODE)

#: De violeta a amarillo (viridis): sube de forma pareja en luminosidad y se distingue con las
#: variantes comunes de daltonismo. Fracción del rango, rojo, verde y azul.
PARADAS_DE_LA_RAMPA = (
    (0.0, (68, 1, 84)),
    (0.2, (65, 68, 135)),
    (0.4, (42, 120, 142)),
    (0.6, (34, 168, 132)),
    (0.8, (122, 209, 81)),
    (1.0, (253, 231, 37)),
)

#: El centinela de «sin dato» de una tesela de color: el mínimo de un `Float32`.
SIN_DATO_DE_LA_TESELA = "-3.4028234663852886e+38"


def texto_seguro(texto: object, largo: int = 60) -> str:
    """Un texto de metadatos listo para pantalla y CSV: sin signos raros ni apertura de fórmula."""
    limpio = _TEXTO_LIMPIO.sub("", str(texto or "")).strip()
    limpio = re.sub(r"^[^\w(]+", "", limpio)  # `=`, `+`, `-`, `@`… al principio
    return re.sub(r"\s+", " ", limpio)[:largo].strip()


def unidad_vertical(declarada: object) -> tuple[str, float | None]:
    """`(texto, metros por unidad)`. Sin unidad declarada o ilegible: `("", None)`."""
    texto = texto_seguro(declarada, largo=24)
    if not texto:
        return "", None
    return texto, UNIDADES_EN_METROS.get(texto.lower())


def referencia_vertical(crs) -> str:
    """El nombre de la parte vertical del sistema, si el archivo lo trae compuesto; si no, `""`."""
    try:
        partes = crs.sub_crs_list if crs.is_compound else []
    except AttributeError:  # un objeto que no es de `pyproj`: no declara nada
        return ""
    for parte in partes:
        if parte.is_vertical:
            return texto_seguro(parte.name)
    return ""


def es_dem(*, bandas: int, tipo: str, paleta: bool) -> bool:
    return bandas == 1 and tipo in TIPOS_DE_ELEVACION and not paleta


def sin_dato_de(banda: dict) -> tuple[float | None, bool]:
    """`(valor, es_nan)` del «sin dato» de la banda; `(None, False)` si no declara ninguno."""
    crudo = banda.get("noDataValue")
    if crudo is None:
        return None, False
    try:
        valor = float(crudo)
    except (TypeError, ValueError):
        return None, False
    if math.isnan(valor):
        return None, True
    return (valor, False) if math.isfinite(valor) else (None, False)


def es_sin_dato(valor: float, *, sin_dato: float | None, es_nan: bool) -> bool:
    """¿Ese valor es «sin dato»? Un valor no finito siempre lo es. La comparación aguanta que el
    `Float32` del archivo y el número que escribe `gdallocationinfo` difieran en la última cifra."""
    if not math.isfinite(valor):
        return True
    if sin_dato is None:
        return False
    return math.isclose(valor, sin_dato, rel_tol=1e-6, abs_tol=1e-9)


def escala_de_sombreado(crs, unidad_vertical_m: float | None) -> float:
    """El `-s` de `gdaldem hillshade`: metros por unidad horizontal / metros por unidad vertical.

    Con grados, 111120 (el valor de GDAL, con elevación en metros). Sin unidad vertical declarada se
    supone la horizontal (metros en un sistema proyectado en metros).
    """
    if crs.is_geographic:
        horizontal_m = METROS_POR_GRADO_DE_GDALDEM
    else:
        horizontal_m = (crs.axis_info[0].unit_conversion_factor if crs.axis_info else 1.0) or 1.0
    vertical_m = unidad_vertical_m or horizontal_m
    return horizontal_m / vertical_m


def rampa(minimo: float, maximo: float) -> list[list]:
    """`[[valor, [r, g, b]], …]` de menor a mayor, repartida en el rango medido."""
    if not (math.isfinite(minimo) and math.isfinite(maximo)) or maximo <= minimo:
        return []
    return [
        [minimo + fraccion * (maximo - minimo), list(color)]
        for fraccion, color in PARADAS_DE_LA_RAMPA
    ]


def texto_de_rampa(paradas: list[list]) -> str:
    """Los colores de `gdaldem color-relief` (`valor r g b a`); el «sin dato», transparente."""
    lineas = [f"{valor!r} {c[0]} {c[1]} {c[2]} 255" for valor, c in paradas]
    lineas.append("nv 0 0 0 0")
    return "\n".join(lineas) + "\n"
