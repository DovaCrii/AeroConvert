"""Lo que Tino **no** sabe, y la única puerta por la que algo puede salir de este equipo.

## Esta puerta nace cerrada, y es la decisión más importante del módulo

El argumento entero de AeroConvert es que un plano bajo acuerdo de confidencialidad no sale
de la máquina, y la aplicación está publicada en internet abierto. Así que esto **no se
enciende solo, no se enciende por omisión y no se enciende porque haya una biblioteca
instalada**: hace falta que alguien ponga una clave a mano, a sabiendas.

Sin `AEROCONVERT_TINO_CLAVE` esto está apagado, `sondar()` lo dice con su motivo, y
**ninguna línea de código de aquí llega a ejecutarse**. Lo que Tino contesta mientras tanto
sale de `saber.py`, de esta máquina, y es la mayor parte de lo que se le pregunta.

## A quién se le pregunta (decisión D9, F20.11)

A la API pública de NVIDIA (`https://integrate.api.nvidia.com/v1/chat/completions`, formato
OpenAI), con la clave que la persona pone a mano en el `.env` de p340: **nunca en el
repositorio ni en el chat, y nunca en un registro ni en un error**. La dirección es un ajuste
(`AEROCONVERT_TINO_URL`) para apuntar más adelante a un NIM autoalojado. Solo se llama con
`TINO_VISIBLE` y clave, y **solo cuando la persona pulsa «Preguntar fuera»**: nunca con cada
tecla, que es como se llena una cuota y se publica media pregunta.

## La regla, que es la que define todo lo demás

**Sale la pregunta escrita por la persona. Nada más.**

Ni el archivo, ni su nombre, ni su contenido, ni sus metadatos, ni la ruta donde estaba, ni
el sistema de referencia que traía dentro. `limpiar()` es lo que lo garantiza, y hay pruebas
que le meten nombres de archivo y rutas por delante para comprobar que no salen.

Y **se dice en pantalla cada vez**, no en una página de condiciones que nadie abre.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from django.conf import settings

log = logging.getLogger(__name__)

#: Modelo por omisión cuando `AEROCONVERT_TINO_MODELO` está vacía: el que ya usa AeroAcademy
#: con esta misma API (mismo catálogo de NVIDIA), de la familia Nemotron, afinada para seguir
#: instrucciones. `manage.py tino_probar` lista los que la clave ve, para elegir otro en p340
#: sin tocar código.
MODELO_RECOMENDADO = "nvidia/nemotron-3.5-lightning-30b-a3b"
#: Si el primero responde 404 (retirado del catálogo), se prueba el siguiente.
RESPALDO_RECOMENDADO = (
    "nvidia/llama-3.1-nemotron-70b-instruct,nvidia/llama-3.1-nemotron-51b-instruct"
)
URL_NVIDIA = "https://integrate.api.nvidia.com/v1"
PLAZO_S = 30
PROVEEDORES = ("nvidia",)

#: Lo que se le dice al modelo sobre qué es esto. No lleva ningún dato de nadie: es la
#: descripción de la aplicación, que es pública y está en el README.
ENCARGO = (
    "Eres Tino, el ayudante de AeroConvert, una aplicación de una oficina de topografía que "
    "convierte planos, ortofotos, nubes de puntos y documentos. Contesta en español, de "
    "usted, en dos o tres frases, sin rodeos. **Si no lo sabes, dilo**: una respuesta "
    "inventada sobre un sistema de referencia o un formato hace que alguien entregue un "
    "archivo mal. No tienes acceso a ningún archivo y no debes pedir que te lo enseñen."
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

#: **Coordenadas**: ubican la obra tanto como una ruta la nombra. Pares decimales
#: (`-33.4567, -70.6483`), un decimal suelto con cuatro o más cifras (≈ 11 m, que ya sitúa un
#: punto) y Este/Norte UTM de 6 o 7 cifras (`345678.12`, `6301234`).
COORDENADAS = re.compile(
    r"""(?x)
    (?<![\w.])-?\d{1,3}\.\d{3,}\s*[,;/]?\s*-?\d{1,3}\.\d{3,}(?![\w.])
    | (?<![\w.])-?\d{1,3}\.\d{4,}(?![\w.])
    | (?<![\w.,])\d{6,7}(?:[.,]\d+)?(?!\w)
    """
)

TOPE_CARACTERES = 500


@dataclass(frozen=True)
class Disponible:
    """Si esta máquina puede preguntar fuera. Con el motivo cuando no."""

    proveedor: str = ""
    codigo: str = ""
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


def _clave() -> str:
    return (getattr(settings, "TINO_CLAVE", "") or "").strip()


def _base() -> str:
    return (getattr(settings, "TINO_URL", "") or URL_NVIDIA).strip().rstrip("/")


def modelos() -> list[str]:
    """El modelo elegido y luego los de respaldo, sin repetir."""
    primero = (getattr(settings, "TINO_MODELO", "") or "").strip() or MODELO_RECOMENDADO
    respaldo = getattr(settings, "TINO_MODELOS_RESPALDO", RESPALDO_RECOMENDADO) or ""
    lista = [primero, *(m.strip() for m in str(respaldo).split(",") if m.strip())]
    return list(dict.fromkeys(lista))


def sondar() -> Disponible:
    """**Apagado mientras no haya una clave puesta a mano** y Tino esté visible."""
    proveedor = (getattr(settings, "TINO_PROVEEDOR", "") or "").strip().lower()

    if not _clave():
        return Disponible(
            codigo="sin-clave-ia",
            motivo="Preguntar fuera está apagado en este equipo, que es como viene de fábrica.",
            sugerencia=(
                "Tino contesta igual lo que esta máquina sabe, que es la mayor parte. Para "
                "lo demás, quien administra el equipo pone AEROCONVERT_TINO_CLAVE en el .env "
                "del servidor: la clave nunca va en el repositorio ni en un chat."
            ),
        )
    if not getattr(settings, "TINO_VISIBLE", False):
        return Disponible(
            codigo="sin-clave-ia",
            motivo="Tino está apagado en este equipo.",
            sugerencia="Se enciende con AEROCONVERT_TINO_VISIBLE=true.",
        )
    if proveedor not in PROVEEDORES:
        return Disponible(
            codigo="sin-clave-ia",
            motivo="Hay clave pero no está dicho a quién se le pregunta.",
            sugerencia=f"AEROCONVERT_TINO_PROVEEDOR debe ser uno de: {', '.join(PROVEEDORES)}.",
        )
    return Disponible(proveedor=proveedor)


@dataclass(frozen=True)
class Consulta:
    """Lo que volvió de fuera, o por qué no se pudo preguntar."""

    texto: str = ""
    modelo: str = ""
    #: Lo que salió, tal cual: es lo que la pantalla enseña.
    enviado: str = ""
    #: Código estable de `apps/jobs/motivos.py` cuando no hubo respuesta.
    codigo: str = ""

    def __bool__(self) -> bool:
        return bool(self.texto)


class _Rechazo(Exception):
    """Un intento que no sirvió. Lleva solo el código HTTP, **nunca** la clave ni el cuerpo."""

    def __init__(self, estado: int | None):
        super().__init__(f"HTTP {estado}" if estado else "sin respuesta")
        self.estado = estado


def _abrir(peticion: urllib.request.Request) -> bytes:
    """Una sola llamada. Solo http/https: la URL la pone quien administra, y `file:` no."""
    if urlparse(peticion.full_url).scheme not in ("http", "https"):
        raise _Rechazo(None)
    try:
        # La dirección sale de AEROCONVERT_TINO_URL: la pone quien administra el equipo, no
        # quien pregunta, y el esquema se comprobó arriba.
        with urllib.request.urlopen(peticion, timeout=PLAZO_S) as r:  # nosec B310
            return r.read(1_000_000)
    except urllib.error.HTTPError as error:
        raise _Rechazo(error.code) from None
    except OSError:  # URLError, plazo vencido y conexión rechazada son todos OSError
        raise _Rechazo(None) from None


def _preguntar_a(modelo: str, texto: str) -> str:
    cuerpo = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": ENCARGO},
            {"role": "user", "content": texto},
        ],
        "temperature": 0.2,
        "max_tokens": 400,
    }
    peticion = urllib.request.Request(  # noqa: S310
        f"{_base()}/chat/completions",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {_clave()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        datos = json.loads(_abrir(peticion))
        contenido = datos["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise _Rechazo(None) from None
    return str(contenido or "").strip()


def consultar(pregunta: str) -> Consulta:
    """Pregunta fuera **solo** lo que `limpiar()` deja, o dice por qué no pudo.

    Un 404 prueba el modelo de respaldo; un 401, un 429, un 5xx o un plazo vencido paran
    aquí: reintentar con otro modelo no arregla una clave mala ni una cuota agotada. En
    ningún caso se registra la clave ni el cuerpo, solo el código de estado.
    """
    if not sondar():
        return Consulta(codigo="sin-clave-ia")
    limpia = limpiar(pregunta)
    if not limpia.texto:
        return Consulta(codigo="ia-no-disponible")
    for modelo in modelos():
        try:
            texto = _preguntar_a(modelo, limpia.texto)
        except _Rechazo as rechazo:
            log.warning("Tino: %s no contestó (%s)", modelo, rechazo)
            if rechazo.estado == 404:
                continue
            return Consulta(enviado=limpia.texto, codigo="ia-no-disponible")
        if texto:
            return Consulta(texto=texto, modelo=modelo, enviado=limpia.texto)
    return Consulta(enviado=limpia.texto, codigo="ia-no-disponible")


def listar_modelos() -> list[str]:
    """`GET {base}/models` con la clave: para elegir el modelo en p340 (`tino_probar`)."""
    peticion = urllib.request.Request(  # noqa: S310
        f"{_base()}/models",
        headers={"Authorization": f"Bearer {_clave()}", "Accept": "application/json"},
    )
    try:
        datos = json.loads(_abrir(peticion))
        return sorted(str(m["id"]) for m in datos["data"])
    except (ValueError, KeyError, TypeError):
        raise _Rechazo(None) from None


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

    def apartar_coordenada(encontrado: re.Match) -> str:
        retirado.append(encontrado.group(0))
        return "«unas coordenadas»"

    texto = COORDENADAS.sub(apartar_coordenada, texto)
    texto = " ".join(texto.split())[:TOPE_CARACTERES]
    return Limpia(texto=texto, retirado=tuple(retirado))
