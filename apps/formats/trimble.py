"""Lector de la cabecera de un archivo crudo de Trimble (T00, T01, T02, T04), sin convertidor.

Gemelo de `las.py` y `tiff.py`: es barato, funciona sin ninguna herramienta externa, y dice
lo que la ficha necesita antes de convertir — **de qué receptor viene el archivo**.

## Lo que se sabe, y lo que no

Medido el 2026-10-05 sobre **dos** archivos reales (un T02 de un NetR9 y un T04 de un R12i):

- empiezan por `00 00 00 0d`;
- la cabecera mide 21 bytes y en el offset 21 hay un bloque **bzip2** (`BZh` y un dígito);
- el primer bloque descomprimido trae texto: `ReceiverId:<n>,<modelo>,<serie>`,
  `SystemUptime:<s>` y `filePath:<ruta en el receptor>`;
- hay **más bloques** detrás, con su propio encuadre entre uno y otro, así que el archivo no
  se lee como un único flujo bzip2 seguido.

Es una observación sobre dos archivos y no una especificación: Trimble no publica el formato.
Por eso aquí **solo se identifica**; lo que se hace con el contenido lo hace el convertidor
oficial. No se intenta decodificar observaciones.

## Un bzip2 que viene de fuera es una bomba posible

La aplicación está publicada en internet y este lector abre archivos subidos. Un bloque bzip2
de unos pocos kilobytes puede descomprimir a gigabytes. Por eso se lee un máximo de bytes y
se pide a la biblioteca una salida **acotada** (`max_length`): nunca se descomprime nada que
no se vaya a mirar.
"""

from __future__ import annotations

import bz2
import re
from dataclasses import dataclass
from pathlib import Path

PREFIJO = b"\x00\x00\x00\x0d"
POSICION_BZIP2 = 21
MAGIA_BZIP2 = b"BZh"

#: Cuánto se lee del archivo. El primer bloque medido ocupa 19 KB (T02) y 81 KB (T04); un
#: bloque de bzip2 necesita **entero** para soltar su primer byte, así que hay margen de sobra.
LECTURA_MAXIMA = 1_048_576

#: Cuánto texto se pide al descomprimir. La identificación está en los primeros bytes.
SALIDA_MAXIMA = 8_192

_RECEPTOR = re.compile(rb"ReceiverId:(\d{1,6}),([^,\x00-\x1f]{1,64}),([A-Za-z0-9]{1,32})")
_ENCENDIDO = re.compile(rb"SystemUptime:(\d{1,12})")
_RUTA = re.compile(rb"filePath:(/[^\x00-\x1f]{1,255})")


class NoEsTrimble(Exception):
    """El archivo no tiene la estructura de un crudo de Trimble."""


@dataclass(frozen=True)
class CabeceraTrimble:
    """Lo que se sabe de un crudo de Trimble leyendo solo su primer bloque."""

    #: El nivel de bzip2 (1 a 9): el tamaño de bloque, en cientos de kilobytes.
    nivel_bzip2: int
    id_receptor: int | None
    #: «TRIMBLE NETR9», «TRIMBLE R12i». Vacío si el primer bloque no lo trae.
    modelo: str
    serie: str
    #: Segundos que llevaba encendido el receptor cuando empezó el archivo.
    encendido_s: int | None
    #: La carpeta del receptor donde se guardó. **No el nombre del archivo**: en lo medido,
    #: el nombre llega cortado, y una carpeta es lo único que se puede afirmar entero.
    carpeta_en_receptor: str

    @property
    def identificado(self) -> bool:
        return bool(self.modelo)

    @property
    def descripcion(self) -> str:
        if not self.identificado:
            return "Receptor Trimble (modelo no identificado)"
        return f"{self.modelo}, serie {self.serie}" if self.serie else self.modelo


def leer_cabecera(ruta: Path) -> CabeceraTrimble:
    """Identifica el receptor. No decodifica una sola observación."""
    with open(ruta, "rb") as archivo:
        datos = archivo.read(LECTURA_MAXIMA)

    if not datos.startswith(PREFIJO):
        raise NoEsTrimble("No empieza como un crudo de Trimble.")
    magia = datos[POSICION_BZIP2 : POSICION_BZIP2 + 4]
    if len(magia) < 4 or not magia.startswith(MAGIA_BZIP2) or not magia[3:4].isdigit():
        raise NoEsTrimble("No trae el bloque comprimido que esperan estos archivos.")
    nivel = int(magia[3:4])
    if nivel == 0:
        raise NoEsTrimble("El bloque comprimido declara un tamaño de bloque imposible.")

    try:
        texto = bz2.BZ2Decompressor().decompress(datos[POSICION_BZIP2:], max_length=SALIDA_MAXIMA)
    except (OSError, ValueError, EOFError) as fallo:
        raise NoEsTrimble(f"El primer bloque no se puede descomprimir: {fallo}") from fallo

    receptor = _RECEPTOR.search(texto)
    encendido = _ENCENDIDO.search(texto)
    ruta_receptor = _RUTA.search(texto)

    carpeta = ""
    if ruta_receptor:
        # `/Internal/VUELOS/2023/01/31/GMLA…` a `/Internal/VUELOS/2023/01/31`.
        completa = ruta_receptor.group(1).decode("latin-1")
        carpeta = completa.rsplit("/", 1)[0] or "/"

    return CabeceraTrimble(
        nivel_bzip2=nivel,
        id_receptor=int(receptor.group(1)) if receptor else None,
        modelo=receptor.group(2).decode("latin-1").strip() if receptor else "",
        serie=receptor.group(3).decode("latin-1") if receptor else "",
        encendido_s=int(encendido.group(1)) if encendido else None,
        carpeta_en_receptor=carpeta,
    )
