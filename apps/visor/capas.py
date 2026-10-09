"""Varias capas y su orden en «Ver en el mapa» (F19.3): el estado que se guarda, sin GDAL ni Django.

## Qué es una capa

Una fila de la lista de capas del mapa. Hay cinco clases:

- `raster`: una ortofoto o un GeoTIFF; la primera es **la principal** (la que lleva el terreno y el
  perfil si es un modelo de elevación).
- `fondo`: el mapa base propio de la casa (`apps/visor/fondo.py`).
- `vuelo-trayectoria`, `vuelo-fotos`, `vuelo-control`: las tres partes de un vuelo de «Corregir un
  vuelo de dron» terminado y de quien mira.

## Qué se guarda, y dónde

Por capa: si se ve y cuánta **transparencia** tiene (0 = opaca, 100 = invisible); y el **orden** de
la lista, de arriba abajo. Todo en un parámetro de la dirección, `e`, para que el mapa se pueda
volver a abrir tal cual, con el enlace:

    e=ra1b2c3:0:1,vd4e5f6f:60:0

Cada elemento es `id:transparencia:visible`. Las capas que no están en `e` se añaden al final en su
orden por omisión; los identificadores que no existen se ignoran; una cifra fuera de rango se
recorta. **El parámetro no lleva rutas ni datos de nadie**: solo identificadores de capas que la
misma petición declara (y que el servidor ya comprobó de quien mira). Un identificador inventado no
abre nada.

## Identificadores estables

Salen de lo que la capa **es** (un resumen corto de su token o del identificador de su trabajo),
no de su posición: quitar una capa de enmedio no cambia el nombre de las demás, y el estado de
esas sigue valiendo.

Lo que dibuja cada una, y qué se lee de dónde, está en `static/js/visor.js`; este módulo es lo que
se puede probar sin navegador: el formato, los límites, el orden y la clase de calidad de una foto.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

RASTER = "raster"
FONDO = "fondo"
VUELO_TRAYECTORIA = "vuelo-trayectoria"
VUELO_FOTOS = "vuelo-fotos"
VUELO_CONTROL = "vuelo-control"

TIPOS = (RASTER, FONDO, VUELO_TRAYECTORIA, VUELO_FOTOS, VUELO_CONTROL)

#: Cuántas imágenes y cuántos vuelos a la vez. Cada ráster pide sus propias teselas; cada vuelo trae
#: miles de puntos. Pasado esto el mapa se vuelve lento y la lista, ilegible.
MAXIMO_DE_RASTERS = 6
MAXIMO_DE_VUELOS = 3

#: 0 es opaca; 100 no se ve. Un tope más bajo dejaría una capa que no se puede apagar del todo.
TRANSPARENCIA_MAXIMA = 100

#: Largo máximo del parámetro `e`: ocho rasters, un fondo y tres vuelos son unos 200 caracteres.
LARGO_MAXIMO_DEL_ESTADO = 900


@dataclass(frozen=True)
class EstadoDeCapa:
    id: str
    visible: bool = True
    transparencia: int = 0


def id_de_raster(token: str) -> str:
    """`r` y seis caracteres del resumen del token: estable mientras el token no cambie."""
    return "r" + hashlib.sha1(token.encode("utf-8"), usedforsecurity=False).hexdigest()[:6]


def id_de_vuelo(pk, parte: str) -> str:
    """`v`, seis caracteres del identificador del trabajo y la parte (`t`, `f` o `c`)."""
    return "v" + str(pk).replace("-", "")[:6] + parte


def id_de_fondo() -> str:
    return "fondo"


def clase_de_calidad(calidad: str | None) -> str:
    """La clase de una foto según su calidad de posición: `buena`, `flotante`, `simple` o `sin`.

    Es la del visor del vuelo (`static/js/vuelo.js`): PPK o fija es buena; flotante, flotante;
    simple, SBAS, DGPS y PPP, simple; lo demás —incluida una calidad **no informada**— es `sin`, que
    el mapa dibuja distinta y la leyenda nombra. Nunca se supone una calidad que el vuelo no trae.
    """
    c = (calidad or "").strip().lower()
    if c in ("ppk", "fija"):
        return "buena"
    if c == "flotante":
        return "flotante"
    if c in ("simple", "sbas", "dgps", "ppp"):
        return "simple"
    return "sin"


def _acotar(valor: int) -> int:
    return max(0, min(TRANSPARENCIA_MAXIMA, valor))


def normalizar(crudo: str | None, ids_por_omision: list[str]) -> list[EstadoDeCapa]:
    """El estado de **todas** las capas, de arriba abajo, a partir de `e` y del orden por omisión.

    No falla nunca: lo que no se entiende se ignora, y la capa vuelve a su estado por omisión. Una
    capa que no está en `e` va detrás de las que sí, en su orden por omisión.
    """
    validos = set(ids_por_omision)
    hallados: dict[str, EstadoDeCapa] = {}
    texto = (crudo or "").strip()
    if texto and len(texto) <= LARGO_MAXIMO_DEL_ESTADO:
        for elemento in texto.split(","):
            partes = elemento.strip().split(":")
            if len(partes) != 3:
                continue
            id_, transparencia, visible = (p.strip() for p in partes)
            if id_ not in validos or id_ in hallados:
                continue
            try:
                cifra = _acotar(int(transparencia))
            except ValueError:
                cifra = 0
            hallados[id_] = EstadoDeCapa(id_, visible != "0", cifra)
    resto = [EstadoDeCapa(i) for i in ids_por_omision if i not in hallados]
    return [*hallados.values(), *resto]


def a_texto(estados: list[EstadoDeCapa]) -> str:
    """El valor de `e` para esas capas: lo mismo que escribe `visor.js` al mover una."""
    return ",".join(f"{e.id}:{_acotar(e.transparencia)}:{1 if e.visible else 0}" for e in estados)


def ordenar(descriptores: list[dict], crudo: str | None) -> list[dict]:
    """Los descriptores de capa, ya en el orden y con la visibilidad y la transparencia guardadas.

    Cada descriptor lleva un `id`. Se devuelven **copias** con `visible` y `transparencia` puestos.
    """
    por_id = {d["id"]: d for d in descriptores}
    estados = normalizar(crudo, [d["id"] for d in descriptores])
    return [
        {**por_id[e.id], "visible": e.visible, "transparencia": e.transparencia} for e in estados
    ]
