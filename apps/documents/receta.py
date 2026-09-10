"""La receta de composición, ida y vuelta entre la pantalla y el código.

La pantalla de unir PDF no puede guardar estado en el servidor: es una lista que se toca
muchas veces —subir, bajar, quitar, girar— y meter eso en la sesión o en la base sería
inventar un carrito de la compra para algo que dura tres minutos.

Así que **la receta viaja en el propio formulario**, en un campo oculto, y cada acción la
lee, la cambia y la devuelve. La pantalla es entonces una función pura de lo que hay
escrito en ella, que además la hace trivial de probar.

## Y por eso hay que desconfiar de lo que llega

Ese campo lo puede escribir cualquiera. Se analiza con reglas estrictas —índices dentro de
rango, páginas desde 1, giros de la lista— y lo que no encaja se descarta en vez de
reventar: una receta corrupta tiene que dejar la pantalla usable, no una traza.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .composicion import GIROS, PaginaElegida

#: Separadores del campo oculto. Se eligen fuera del juego de caracteres de una ruta para
#: que nunca haya que escapar nada: la ruta no viaja aquí, solo su índice.
ENTRE_PAGINAS = ","
DENTRO = ":"

#: Tope de páginas en una composición. No es una limitación técnica —pypdf aguanta mucho
#: más— sino de la pantalla: mil tarjetas no se ordenan a mano. Y evita que un campo oculto
#: manipulado pida un millón de páginas.
MAXIMO_PAGINAS = 500


@dataclass(frozen=True)
class Entrada:
    """Una página en la receta: de qué archivo, cuál, y girada cuánto."""

    archivo: int
    pagina: int
    giro: int = 0

    def a_texto(self) -> str:
        return f"{self.archivo}{DENTRO}{self.pagina}{DENTRO}{self.giro}"


def a_texto(entradas: list[Entrada]) -> str:
    return ENTRE_PAGINAS.join(e.a_texto() for e in entradas)


def desde_texto(texto: str, cuantos_archivos: int) -> list[Entrada]:
    """Analiza el campo oculto. **Lo que no encaja se descarta, no revienta.**

    `cuantos_archivos` acota los índices: una receta que apunte al archivo 7 cuando solo
    hay dos es basura, venga de un error o de alguien probando.
    """
    entradas: list[Entrada] = []
    for trozo in (texto or "").split(ENTRE_PAGINAS):
        partes = trozo.strip().split(DENTRO)
        if len(partes) != 3:
            continue
        try:
            archivo, pagina, giro = (int(p) for p in partes)
        except ValueError:
            continue
        if not 0 <= archivo < cuantos_archivos or pagina < 1 or giro not in GIROS:
            continue
        entradas.append(Entrada(archivo, pagina, giro))
        if len(entradas) >= MAXIMO_PAGINAS:
            break
    return entradas


# --- Las acciones de la pantalla --------------------------------------------
#
# Todas devuelven una lista nueva y **ninguna levanta por un indice fuera de rango**: los
# botones se pintan desde la misma lista, pero entre que se pinta y se pulsa puede haber
# pasado cualquier cosa, y un 500 por pulsar «subir» en una fila que ya no esta seria una
# forma tonta de perder el trabajo hecho.


def subir(entradas: list[Entrada], indice: int) -> list[Entrada]:
    if not 0 < indice < len(entradas):
        return entradas
    nuevas = list(entradas)
    nuevas[indice - 1], nuevas[indice] = nuevas[indice], nuevas[indice - 1]
    return nuevas


def bajar(entradas: list[Entrada], indice: int) -> list[Entrada]:
    if not 0 <= indice < len(entradas) - 1:
        return entradas
    nuevas = list(entradas)
    nuevas[indice], nuevas[indice + 1] = nuevas[indice + 1], nuevas[indice]
    return nuevas


def quitar(entradas: list[Entrada], indice: int) -> list[Entrada]:
    if not 0 <= indice < len(entradas):
        return entradas
    return [e for i, e in enumerate(entradas) if i != indice]


def girar(entradas: list[Entrada], indice: int, grados: int = 90) -> list[Entrada]:
    """Suma grados al giro de esa página, dando la vuelta en 360.

    Sumar y no fijar: quien pulsa cuatro veces «girar» espera volver al principio, no
    quedarse clavado en 90.
    """
    if not 0 <= indice < len(entradas) or grados not in GIROS:
        return entradas
    nuevas = list(entradas)
    actual = nuevas[indice]
    nuevas[indice] = Entrada(actual.archivo, actual.pagina, (actual.giro + grados) % 360)
    return nuevas


def a_paginas(entradas: list[Entrada], archivos: list[Path]) -> list[PaginaElegida]:
    """De la receta de la pantalla a lo que entiende el compositor."""
    return [
        PaginaElegida(archivo=archivos[e.archivo], numero=e.pagina, giro=e.giro)
        for e in entradas
        if 0 <= e.archivo < len(archivos)
    ]
