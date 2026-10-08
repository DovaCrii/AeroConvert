"""Paquetes de entrega: «Entrega a BHP» como una receta con nombre.

Un **preajuste** es un destino con sus opciones. Un **paquete** es una lista ordenada de
preajustes que se aplican **al mismo archivo** de una vez, más lo que los une: un patrón para los
nombres de los archivos que salen y, si se pide, el sistema de coordenadas al que llevarlos todos.

## Lo que se garantiza

- **La misma receta produce los mismos parámetros en dos corridas.** `expandir()` es una función
  pura: el nombre del archivo, el destino, las opciones y el CRS salen solo de la receta, del
  nombre del original y de la fecha que se le pase (la hora de la corrida no entra sola).
- **Los nombres son seguros.** Lo que pone una persona en el patrón y el nombre del original pasan
  por `limpiar()`: sin separadores de carpeta, sin los caracteres que Windows rechaza, sin nombres
  reservados y sin puntos ni espacios al final. Un nombre nunca puede escapar de la carpeta.
- **Dos pasos no se pisan.** Si dos pasos dan el mismo nombre (dos destinos con la misma extensión),
  el segundo lleva `_2`, el tercero `_3`.
- **Todo o nada**: si algún paso no se puede hacer con el archivo, no se encola ninguno.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

#: Lo que el patrón puede llevar entre llaves.
MARCAS = {
    "origen": "el nombre del archivo original, sin extensión",
    "destino": "el formato de destino (cog, laz, dxf…)",
    "perfil": "el perfil del preajuste, si lo tiene",
    "fecha": "la fecha de la entrega, AAAAMMDD",
    "n": "el número del paso dentro del paquete",
}

PATRON_POR_OMISION = "{origen}_{destino}"

LARGO_MAXIMO_DE_NOMBRE = 120

#: Lo que Windows no admite en un nombre, y los controles.
_PROHIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVADOS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
_MARCA = re.compile(r"\{([^{}]*)\}")


class PaqueteInvalido(ValueError):
    """La receta no se puede aplicar, con el motivo dicho para una persona."""


@dataclass(frozen=True)
class Paso:
    orden: int  # 1, 2, 3…
    preajuste_slug: str
    formato: str
    perfil_id: str
    opciones: tuple[tuple[str, object], ...]  # ordenadas: la receta no depende del orden del dict
    crs_destino: str
    nombre_de_salida: str  # sin extensión: la pone quien conoce el formato


def validar_patron(patron: str) -> str:
    """El patrón limpio, o `PaqueteInvalido`. Se llama al guardar y, otra vez, al aplicar."""
    patron = (patron or "").strip()
    if not patron:
        raise PaqueteInvalido("El patrón del nombre no puede estar vacío.")
    if len(patron) > LARGO_MAXIMO_DE_NOMBRE:
        raise PaqueteInvalido(f"El patrón pasa de {LARGO_MAXIMO_DE_NOMBRE} caracteres.")
    for marca in _MARCA.findall(patron):
        if marca not in MARCAS:
            posibles = ", ".join("{" + m + "}" for m in MARCAS)
            raise PaqueteInvalido(f"«{{{marca}}}» no es una marca del patrón. Las que hay: {posibles}.")
    sobrante = _MARCA.sub("", patron)
    if "{" in sobrante or "}" in sobrante:
        raise PaqueteInvalido("Hay una llave suelta en el patrón.")
    if _PROHIBIDOS.search(sobrante):
        raise PaqueteInvalido(
            'El patrón lleva un carácter que no puede ir en un nombre de archivo: < > : " / \\ | ? *'
        )
    return patron


def limpiar(texto: str) -> str:
    """Un trozo de nombre de archivo que ningún sistema rechaza ni usa para salir de su carpeta."""
    limpio = _PROHIBIDOS.sub("_", str(texto))
    limpio = re.sub(r"\s+", " ", limpio).strip(" .")
    if limpio.lower() in _RESERVADOS:
        limpio = f"_{limpio}"
    return limpio[:LARGO_MAXIMO_DE_NOMBRE]


def nombre_de_salida(patron: str, *, origen: str, destino: str, perfil: str, fecha: date, n: int) -> str:
    """El nombre (sin extensión) que sale de aplicar el patrón. Siempre limpio y nunca vacío."""
    valores = {
        "origen": limpiar(origen),
        "destino": limpiar(destino),
        "perfil": limpiar(perfil),
        "fecha": fecha.strftime("%Y%m%d"),
        "n": str(n),
    }
    # Se sustituye marca por marca (y no con `str.format`) para que un valor con llaves, venga de
    # un nombre de archivo, no pueda leerse como otra marca.
    bruto = _MARCA.sub(lambda m: valores.get(m.group(1), ""), validar_patron(patron))
    # Lo que queda tras limpiar el patrón entero: los literales también pasan por el filtro.
    resultado = limpiar(re.sub(r"_{2,}", "_", bruto)).strip("_ ") or "entrega"
    return resultado


def expandir(paquete, preajustes: dict, *, nombre_origen: str, fecha: date) -> list[Paso]:
    """Los pasos de aplicar `paquete` a un archivo. **Pura**: no toca la base ni el reloj.

    `preajustes` es un diccionario slug → preajuste con lo que el paquete puede usar; un slug que
    ya no está levanta `PaqueteInvalido` con su nombre, y no se salta en silencio.
    """
    slugs = list(paquete.pasos or [])
    if not slugs:
        raise PaqueteInvalido(f"El paquete «{paquete.nombre}» no tiene ningún paso.")
    patron = validar_patron(paquete.patron_de_nombre or PATRON_POR_OMISION)

    pasos: list[Paso] = []
    usados: set[str] = set()
    for orden, slug in enumerate(slugs, start=1):
        preajuste = preajustes.get(slug)
        if preajuste is None:
            raise PaqueteInvalido(
                f"El paso {orden} del paquete «{paquete.nombre}» usa un preajuste que ya no existe "
                f"(«{slug}»). Edite el paquete."
            )
        base = nombre_de_salida(
            patron,
            origen=nombre_origen,
            destino=preajuste.target_format_code,
            perfil=preajuste.target_profile_id,
            fecha=fecha,
            n=orden,
        )
        nombre, contador = base, 2
        while nombre.lower() in usados:
            nombre = f"{base}_{contador}"
            contador += 1
        usados.add(nombre.lower())
        pasos.append(
            Paso(
                orden=orden,
                preajuste_slug=slug,
                formato=preajuste.target_format_code,
                perfil_id=preajuste.target_profile_id,
                opciones=tuple(sorted((preajuste.options or {}).items())),
                crs_destino=(paquete.target_crs_code or preajuste.target_crs_code or "").strip(),
                nombre_de_salida=nombre,
            )
        )
    return pasos
