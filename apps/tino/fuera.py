"""Lo que Tino **no** sabe, y la única puerta por la que algo puede salir de este equipo.

## Esta puerta nace cerrada, y es la decisión más importante del módulo

El argumento entero de AeroConvert es que un plano bajo acuerdo de confidencialidad no sale
de la máquina, y la aplicación está publicada en internet abierto. Así que esto **no se
enciende solo, no se enciende por omisión y no se enciende porque haya una biblioteca
instalada**: hace falta que alguien ponga una clave a mano, a sabiendas.

Sin `AEROCONVERT_TINO_CLAVE` esto está apagado, `sondar()` lo dice con su motivo, y
**ninguna línea de código de aquí llega a ejecutarse**. Lo que Tino contesta mientras tanto
sale de `saber.py`, de esta máquina, y es la mayor parte de lo que se le pregunta.

## Y qué proveedor es una decisión que no está tomada

A propósito. Elegir a quién se le manda la pregunta de alguien es de quien responde por los
datos de esta oficina, no de quien escribe el código. El módulo define **la forma** de esa
llamada —qué sale, qué no sale nunca, y qué se le dice a la persona— y deja el proveedor en
un ajuste.

## La regla, que es la que define todo lo demás

**Sale la pregunta escrita por la persona. Nada más.**

Ni el archivo, ni su nombre, ni su contenido, ni sus metadatos, ni la ruta donde estaba, ni
el sistema de referencia que traía dentro. `limpiar()` es lo que lo garantiza, y hay pruebas
que le meten nombres de archivo y rutas por delante para comprobar que no salen.

Y **se dice en pantalla cada vez**, no en una página de condiciones que nadie abre.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.conf import settings

#: Lo que se le dice al modelo sobre qué es esto. No lleva ningún dato de nadie: es la
#: descripción de la aplicación, que es pública y está en el README.
ENCARGO = (
    "Eres Tino, el ayudante de AeroConvert, una aplicación de una oficina de topografía que "
    "convierte planos, ortofotos, nubes de puntos y documentos. Contesta en castellano, en "
    "dos o tres frases, sin rodeos. **Si no lo sabes, dilo**: una respuesta inventada sobre "
    "un sistema de referencia o un formato hace que alguien entregue un archivo mal. No "
    "tienes acceso a ningún archivo y no debes pedir que te lo enseñen."
)

#: Lo que **nunca** puede viajar, buscado en lo que la persona escribió.
#:
#: No es censura de lo que alguien quiera preguntar: es que una pregunta escrita a las
#: prisas trae pegada la ruta del archivo —«no puedo convertir D:\obras\minera\vuelo.tif»— y
#: esa ruta dice el cliente, la obra y el nombre del proyecto. Se quita y se avisa.
RUTAS = re.compile(
    r"""(?xi)
    (?: [a-z]:[\\/][^\s"']*        # D:\obras\...
      | \\\\[^\s"']+               # \\servidor\carpeta
      | /(?:home|mnt|srv|var)/[^\s"']*
      | \b[\w.\-]+\.(?:tif|tiff|las|laz|dwg|dgn|dxf|shp|pdf|xlsx|docx|mdb|e00|ecw|jp2)\b
    )
    """
)

TOPE_CARACTERES = 500


@dataclass(frozen=True)
class Disponible:
    """Si esta máquina puede preguntar fuera. Con el motivo cuando no."""

    proveedor: str = ""
    motivo: str = ""
    sugerencia: str = ""

    def __bool__(self) -> bool:
        return bool(self.proveedor)


@dataclass(frozen=True)
class Limpia:
    """La pregunta tal como saldría, y qué se le quitó."""

    texto: str
    #: Los trozos retirados. **Se enseñan**: decir «se quitó algo» sin decir qué deja a
    #: alguien sin saber si su pregunta sigue significando lo mismo.
    retirado: tuple[str, ...] = ()

    @property
    def se_toco(self) -> bool:
        return bool(self.retirado)


def sondar() -> Disponible:
    """**Apagado mientras no haya una clave puesta a mano.**"""
    clave = (getattr(settings, "TINO_CLAVE", "") or "").strip()
    proveedor = (getattr(settings, "TINO_PROVEEDOR", "") or "").strip()

    if not clave:
        return Disponible(
            motivo=("Preguntar fuera está apagado en este equipo, que es como viene de fábrica."),
            sugerencia=(
                "Tino contesta igual lo que esta máquina sabe, que es la mayor parte. Para "
                "lo demás haría falta decidir a qué proveedor se le pregunta y poner "
                "AEROCONVERT_TINO_CLAVE — y eso es una decisión sobre los datos de la "
                "oficina, no un ajuste técnico."
            ),
        )
    if not proveedor:
        return Disponible(
            motivo="Hay clave pero no está dicho a quién se le pregunta.",
            sugerencia="Falta AEROCONVERT_TINO_PROVEEDOR.",
        )
    return Disponible(proveedor=proveedor)


def limpiar(pregunta: str) -> Limpia:
    """Deja la pregunta en lo que se puede mandar, y dice qué quitó.

    Una pregunta escrita a las prisas trae pegada la ruta del archivo. Esa ruta no hace
    falta para contestar y sí dice el cliente, la obra y el nombre del proyecto — que es
    exactamente lo que esta aplicación existe para no publicar.
    """
    retirado: list[str] = []

    def apartar(encontrado: re.Match) -> str:
        retirado.append(encontrado.group(0))
        return "«el archivo»"

    texto = RUTAS.sub(apartar, pregunta or "")
    texto = " ".join(texto.split())[:TOPE_CARACTERES]
    return Limpia(texto=texto, retirado=tuple(retirado))
