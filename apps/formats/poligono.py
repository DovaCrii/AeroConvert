"""El polígono de recorte, con su sistema de referencia pegado (F21.3).

**Un polígono sin sistema de referencia no es un polígono: es una lista de números.**
Recortar con él
deja el archivo en otro sitio o vacío, y lo hace en silencio. Por eso aquí no hay valor por omisión
ni «el más probable» (regla 3): sin CRS declarado y válido, el trabajo se detiene con `crs-ausente`.

Los vértices viajan como `PuntoConCrs` (ninguna función acepta un `(x, y)` pelado). Lo que llega en
`options` es JSON, así que `anillo_de_opciones` es la única puerta por la que un par de números se
convierte en punto, y solo si trae su CRS.

## Formas de darlo

- `recorte_vertices`: una lista `[[x, y], …]` o un texto (`x y; x y; …`, un vértice por línea o
  separado por `;`; punto decimal) **y** `recorte_crs` (`EPSG:32719` o `32719`).
- `recorte_archivo`: un archivo vectorial con un polígono (lo lee GDAL; su CRS lo dice `ogrinfo`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from apps.engines.base import PlanNoValido

from . import crs as crs_mod
from .crs import Crs, PuntoConCrs

#: Menos de tres vértices distintos no encierran nada.
VERTICES_MINIMOS = 3

#: Con qué se lee un archivo de polígonos: solo formatos de datos. Un VRT de OGR puede abrir **otros
#: archivos del disco**, así que ni se admite (mismo criterio que B-04 con el ASCII Grid).
EXTENSIONES_DE_POLIGONO = (".geojson", ".json", ".gpkg", ".shp", ".kml")


def crs_de_opciones(opciones: dict) -> Crs:
    """El CRS **declarado** del polígono. Sin él, se detiene: no se deduce de nada."""
    texto = str(opciones.get("recorte_crs") or "").strip()
    try:
        return crs_mod.validar_declarado(texto)
    except crs_mod.CrsInvalido as fallo:
        raise PlanNoValido(
            "El polígono de recorte no declara un sistema de referencia válido "
            f"({fallo}). No se adivina: dígalo usted.",
            "crs-ausente" if fallo.codigo == "crs-ausente" else "crs-invalido",
        ) from fallo


def _pares(vertices) -> list[tuple[float, float]]:
    if isinstance(vertices, str):
        trozos = [t.strip() for t in re.split(r"[;\n]", vertices) if t.strip()]
        crudos = [re.split(r"[\s,]+", t) for t in trozos]
    else:
        crudos = [list(v) for v in vertices or ()]
    pares: list[tuple[float, float]] = []
    for crudo in crudos:
        if len(crudo) != 2:
            raise PlanNoValido(
                "Cada vértice del polígono lleva dos números: este y norte.", "error-del-motor"
            )
        try:
            x, y = float(crudo[0]), float(crudo[1])
        except (TypeError, ValueError) as fallo:
            raise PlanNoValido(
                "Un vértice del polígono no es un número.", "error-del-motor"
            ) from fallo
        if not (math.isfinite(x) and math.isfinite(y)):
            raise PlanNoValido("Un vértice del polígono no es un número finito.", "error-del-motor")
        pares.append((x, y))
    return pares


def anillo_de_opciones(opciones: dict) -> tuple[PuntoConCrs, ...]:
    """Los vértices de `recorte_vertices`, cada uno con el CRS declarado. Anillo **abierto**."""
    crs = crs_de_opciones(opciones)
    pares = _pares(opciones.get("recorte_vertices"))
    if len(pares) > 1 and pares[0] == pares[-1]:
        pares = pares[:-1]
    if len({*pares}) < VERTICES_MINIMOS:
        raise PlanNoValido(
            f"Un polígono necesita al menos {VERTICES_MINIMOS} vértices distintos.",
            "error-del-motor",
        )
    return tuple(PuntoConCrs(x_m=x, y_m=y, crs=crs) for x, y in pares)


def crs_unico(anillo: Sequence[PuntoConCrs]) -> Crs:
    crs = {str(p.crs) for p in anillo}
    if len(crs) != 1 or not anillo[0].crs.conocido:
        raise PlanNoValido(
            "Los vértices del polígono no comparten un sistema de referencia conocido.",
            "crs-ausente",
        )
    return anillo[0].crs


def area_m2(anillo: Sequence[PuntoConCrs]) -> float:
    """El área con la fórmula del cordón, en las unidades del CRS al cuadrado. Cero = degenerado."""
    crs_unico(anillo)
    suma = 0.0
    for a, b in zip(anillo, (*anillo[1:], anillo[0]), strict=True):
        suma += a.x_m * b.y_m - b.x_m * a.y_m
    return abs(suma) / 2


def a_wkt(anillo: Sequence[PuntoConCrs]) -> str:
    """`POLYGON((x y, …))` cerrado, en el CRS de los vértices. `repr` guarda todos los decimales."""
    if area_m2(anillo) == 0:
        raise PlanNoValido(
            "El polígono de recorte no encierra ninguna superficie.", "error-del-motor"
        )
    puntos = [*anillo, anillo[0]]
    return "POLYGON((" + ", ".join(f"{p.x_m!r} {p.y_m!r}" for p in puntos) + "))"


def llevar_a(anillo: Sequence[PuntoConCrs], destino: Crs) -> tuple[PuntoConCrs, ...]:
    """Los mismos vértices en otro sistema (para una nube, que PDAL recorta en el suyo).

    Con los dos CRS conocidos: sin ellos, `crs_unico` y la comprobación de abajo detienen. Orden
    este-norte (`always_xy`), el de los vértices.
    """
    origen = crs_unico(anillo)
    if not destino.conocido:
        raise PlanNoValido(
            "El archivo no declara su sistema de referencia: no se sabe dónde cae el polígono.",
            "crs-ausente",
        )
    if str(origen) == str(destino):
        return tuple(anillo)
    from pyproj import Transformer
    from pyproj.exceptions import CRSError, ProjError

    try:
        mover = Transformer.from_crs(str(origen), str(destino), always_xy=True)
        movidos = [mover.transform(p.x_m, p.y_m) for p in anillo]
    except (CRSError, ProjError) as fallo:
        raise PlanNoValido(
            f"No se pudo llevar el polígono a {destino}: {fallo}", "crs-invalido"
        ) from fallo
    if not all(math.isfinite(x) and math.isfinite(y) for x, y in movidos):
        raise PlanNoValido("El polígono no cabe en el sistema del archivo.", "recorte-vacio")
    return tuple(PuntoConCrs(x_m=x, y_m=y, crs=destino) for x, y in movidos)


def caja_de(anillo: Sequence[PuntoConCrs]) -> tuple[float, float, float, float]:
    """`(oeste, sur, este, norte)` de los vértices, en el CRS de ellos."""
    crs_unico(anillo)
    este = [p.x_m for p in anillo]
    norte = [p.y_m for p in anillo]
    return min(este), min(norte), max(este), max(norte)


#: Puntos por lado al llevar una caja de un sistema a otro: el borde recto de una caja se curva.
PUNTOS_POR_LADO = 21


def caja_de_extension(
    extension: Sequence[float], origen: Crs, destino: Crs
) -> tuple[float, float, float, float]:
    """La caja `[minx, miny, maxx, maxy]` de un archivo (en `origen`) llevada a `destino`.

    Se reparten puntos por los cuatro lados y se transforman todos: llevar solo las esquinas deja
    fuera lo que el borde curvo asoma entre ellas.
    """
    minx, miny, maxx, maxy = (float(v) for v in extension)
    paso = [i / (PUNTOS_POR_LADO - 1) for i in range(PUNTOS_POR_LADO)]
    borde = (
        [(minx + t * (maxx - minx), miny) for t in paso]
        + [(minx + t * (maxx - minx), maxy) for t in paso]
        + [(minx, miny + t * (maxy - miny)) for t in paso]
        + [(maxx, miny + t * (maxy - miny)) for t in paso]
    )
    anillo = tuple(PuntoConCrs(x_m=x, y_m=y, crs=origen) for x, y in borde)
    return caja_de(llevar_a(anillo, destino))
