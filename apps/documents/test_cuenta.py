"""Que el número de herramientas escrito en las palabras sea el de verdad.

## Por qué hace falta una prueba para contar

«Las once herramientas de PDF» estuvo escrito en tres sitios cuando ya eran dieciocho. El
docstring de `estado_de_herramientas` decía —con razón— que dejar el número escrito es lo que
permite ver el desfase; lo que no decía es **quién lo iba a ver**. Para verlo había que abrir
ese archivo y leer esa línea, y nadie abre un archivo a comprobar un número que no sospecha.

Lo que hace daño de verdad no es el docstring: es el `README` del despliegue, que alguien lee
para montar el servidor y del que sale creyendo que faltan siete cosas que ya están.

Así que la cifra se comprueba donde se publica.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings

from .views import HERRAMIENTAS

#: Los números en letra, que es como se escriben en prosa castellana y como están hoy.
#: Hasta veinticinco: pasado eso, la frase correcta deja de ser «las N herramientas».
EN_LETRA = {
    11: "once",
    12: "doce",
    13: "trece",
    14: "catorce",
    15: "quince",
    16: "dieciséis",
    17: "diecisiete",
    18: "dieciocho",
    19: "diecinueve",
    20: "veinte",
    21: "veintiuna",
    22: "veintidós",
    23: "veintitrés",
    24: "veinticuatro",
    25: "veinticinco",
}

#: Dónde se publica la cifra. No es una lista de todos los sitios donde aparece un número: es
#: la lista de los que **cuentan herramientas de documentos**.
DONDE_SE_PUBLICA = (
    "despliegue/README.md",
    "despliegue/SERVIDOR.md",
    "apps/documents/views.py",
)


def _cuantas() -> int:
    return len(HERRAMIENTAS)


def test_la_cifra_tiene_palabra():
    """Si se pasa de veinticinco, esta prueba avisa antes de que la frase quede rara."""
    assert _cuantas() in EN_LETRA, (
        f"Ya son {_cuantas()} herramientas. Añade la palabra a EN_LETRA, o cambia la prosa a "
        "«las herramientas de documentos» sin número — que a partir de cierto punto es mejor."
    )


@pytest.mark.parametrize("archivo", DONDE_SE_PUBLICA)
def test_ningun_sitio_publica_una_cifra_vieja(archivo):
    """**Solo persigue las que están mal.**

    No exige que cada archivo diga el número —`SERVIDOR.md` podría dejar de contarlas y
    estaría bien—: exige que, si lo dice, sea el de verdad. Lo contrario obligaría a escribir
    una cifra en sitios donde no pinta nada.
    """
    texto = (Path(settings.BASE_DIR) / archivo).read_text("utf-8")
    correcta = EN_LETRA[_cuantas()]

    viejas = [
        palabra
        for cuantas, palabra in EN_LETRA.items()
        if cuantas != _cuantas()
        and re.search(rf"\b{palabra}\b[^.\n]{{0,40}}(herramientas|de documentos|de PDF)", texto)
    ]
    assert not viejas, (
        f"{archivo} habla de «{viejas[0]}» herramientas y son {_cuantas()} ({correcta}). "
        "Es la clase de desfase que hace que alguien monte el servidor creyendo que le faltan "
        "cosas que ya están."
    )
