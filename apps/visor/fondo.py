"""El mapa base propio de «Ver en el mapa» (F19.5, decisión D5): de la casa, nunca de internet.

## Qué es

Una capa de fondo que la persona elige entre las que **la casa configura**: una ortofoto o un
mosaico COG que ya está en el equipo. `AEROCONVERT_VISOR_MAPA_BASE` lleva una o varias rutas
separadas por `;` (como las raíces permitidas), cada una con su nombre opcional:
`Mosaico de la obra=D:\\obra\\m.tif`. Se corta en teselas con el mismo camino que cualquier otra
capa (GDAL del propio archivo), así que **ninguna petición sale del servidor**.

## Por qué no se acepta un servidor de teselas

Un fondo de OpenStreetMap, de Google o de cualquier otro es una petición del navegador a internet, y
«nada sale del equipo» (D5) deja de ser verdad con cada vista. Aquí no hay forma de configurar una
dirección: el valor es una ruta del disco, comprobada contra las raíces permitidas en cada petición.

## Cómo viaja

El navegador **no conoce la ruta**: pide `fondo:<n>` (la posición en la lista) y el servidor la
resuelve aquí. Un `fondo:7` que no existe, o que ya no es usable, es un 403 con su código, igual que
una ruta fuera de las raíces. Un fondo configurado que no sirve (no existe, está fuera de las
raíces, no es un GeoTIFF) **no se esconde**: la lista lo muestra apagado, con su motivo (regla 4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from apps.core import modo as modo_mod
from apps.core.entrada import EntradaNoPermitida, Origen

#: Lo que marca, en lugar de una ruta, «el fondo número n de la lista de la casa».
PREFIJO = "fondo:"

#: Lo que se pide en el parámetro `fondo` para quedarse con la retícula, sin mapa base.
SIN_FONDO = "ninguno"

#: Cuántos se aceptan: una lista de la casa, no un catálogo.
MAXIMO_DE_FONDOS = 8

EXTENSIONES = (".tif", ".tiff")

CODIGO_NO_VALIDO = "mapa-base-no-valido"


@dataclass(frozen=True)
class Fondo:
    indice: int
    nombre: str
    #: `None` si no se puede usar; entonces `detalle` dice por qué, **sin la ruta del servidor**.
    ruta: Path | None
    detalle: str = ""

    @property
    def token(self) -> str:
        return f"{PREFIJO}{self.indice}"

    @property
    def usable(self) -> bool:
        return self.ruta is not None


def _partir(entrada: str) -> tuple[str, str]:
    """`(nombre, ruta)` de una entrada `Nombre=ruta` o solo `ruta`.

    Lo de antes del primer `=` es un nombre **solo si no parece una ruta**: en Linux un directorio
    puede llevar `=` en el nombre, y una ruta no lleva barras, dos puntos ni extensión antes de un
    nombre de persona.
    """
    izquierda, igual, derecha = entrada.partition("=")
    if igual and izquierda.strip() and not re.search(r"[\\/:]", izquierda):
        return izquierda.strip(), derecha.strip().strip('"')
    return "", entrada.strip().strip('"')


def _comprobar(ruta_texto: str) -> tuple[Path | None, str]:
    """La ruta ya resuelta, o `None` y el motivo en palabras (nunca la ruta del servidor)."""
    try:
        ruta = modo_mod.comprobar_ruta(ruta_texto)
    except modo_mod.RutaNoPermitida:
        return None, "Está fuera de las carpetas permitidas."
    if ruta.suffix.lower() not in EXTENSIONES:
        return None, "Solo se admiten GeoTIFF o COG (.tif o .tiff)."
    try:
        existe = ruta.is_file()
    except OSError:
        existe = False
    if not existe:
        return None, "El archivo ya no está."
    return ruta, ""


def configurados() -> list[Fondo]:
    """Los fondos de la casa, en el orden en que se configuraron. Se lee en cada llamada: el valor
    es corto y el disco puede cambiar entre dos peticiones."""
    crudo = (getattr(settings, "VISOR_MAPA_BASE", "") or "").strip()
    fondos: list[Fondo] = []
    for entrada in crudo.split(";"):
        if not entrada.strip():
            continue
        if len(fondos) >= MAXIMO_DE_FONDOS:
            break
        nombre, ruta_texto = _partir(entrada)
        ruta, detalle = _comprobar(ruta_texto)
        if not nombre:
            nombre = Path(ruta_texto).stem or f"Mapa base {len(fondos) + 1}"
        fondos.append(Fondo(indice=len(fondos), nombre=nombre, ruta=ruta, detalle=detalle))
    return fondos


def elegir(valor: str | None, fondos: list[Fondo]) -> Fondo | None:
    """El fondo que se ve: el pedido, o **el primero de la casa que se pueda usar** si no se pidió
    ninguno. `ninguno` es la retícula, sin fondo. Uno pedido que no existe o no sirve es `None`: no
    se sustituye por otro en silencio (regla 4), y la lista dice por qué."""
    texto = (valor or "").strip().lower()
    if texto == SIN_FONDO:
        return None
    if not texto:
        return next((f for f in fondos if f.usable), None)
    if texto.isdigit() and int(texto) < len(fondos) and fondos[int(texto)].usable:
        return fondos[int(texto)]
    return None


def resolver(token: str) -> Origen:
    """`fondo:<n>` a un origen legible, o 403 con su código. La ruta se vuelve a comprobar aquí."""
    posicion = token[len(PREFIJO) :].strip()
    fondos = configurados()
    if not posicion.isdigit() or int(posicion) >= len(fondos) or not fondos[int(posicion)].usable:
        raise EntradaNoPermitida(
            "Ese mapa base no está configurado o ya no se puede usar.", CODIGO_NO_VALIDO
        )
    fondo = fondos[int(posicion)]
    return Origen(ruta=fondo.ruta, nombre=fondo.nombre)
