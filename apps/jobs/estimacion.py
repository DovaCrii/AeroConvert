"""Cuánto va a pesar, cuánto va a tardar y si cabe. **Antes** de encolar.

## Por qué se estima en vez de callarse

Porque la alternativa es que alguien lance una conversión de cuarenta minutos sin saberlo,
o que llene el disco y se entere cuando el sistema deja de responder. Una línea que diga
«saldrá ≈ 285 MB, unos 7 s, hay 180 GB libres» cuesta unos microsegundos y evita las dos
cosas.

## De dónde salen los números, y qué valen

**Son medidas, no supuestos** -- pero medidas sobre **un** archivo, y eso hay que decirlo.
La referencia está en `docs/PRUEBAS_CON_ORACULO.md`: una ortofoto de fotogrametría de
14.526 × 14.443 px a 2,56 cm/px sobre terreno minero.

Los ratios se anclan al **tamaño sin comprimir**, no al del archivo de entrada. Es lo único
comparable: un GeoTIFF de 466 MB comprimido con LZW y otro de 1,2 GB sin comprimir pueden
tener exactamente el mismo contenido, y estimar sobre el tamaño del archivo daría dos
respuestas distintas para la misma imagen.

Una ortofoto de terreno uniforme -- arena, agua, nieve -- comprime mucho más que este
material, y una con mucha vegetación menos. Por eso la interfaz escribe «≈» y no una cifra
seca: es un orden de magnitud correcto, no una promesa.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

#: Fracción del tamaño **sin comprimir** que ocupa cada combinación, medida el 2026-09-08
#: sobre la ortofoto de referencia. La clave es (formato, compresión).
#:
#: Las tres primeras son sin pérdida y por tanto reproducibles; las de JPEG y JP2 dependen
#: de la calidad pedida y del material, y son las que más se mueven.
RATIOS = {
    ("geotiff", "DEFLATE"): 0.45,
    ("geotiff", "LZW"): 0.48,
    ("geotiff", "NONE"): 1.00,
    ("geotiff", "JPEG"): 0.055,
    ("bigtiff", "DEFLATE"): 0.45,
    ("bigtiff", "LZW"): 0.48,
    ("cog", "DEFLATE"): 0.46,
    ("cog", "LZW"): 0.49,
    ("img", "DEFLATE"): 0.48,
    ("jp2", ""): 0.071,
    ("ecw", ""): 0.045,
    ("png", ""): 0.55,
    ("jpeg", ""): 0.055,
    ("webp", ""): 0.05,
    ("asc", ""): 3.20,  # Texto plano: **crece**, y mucho. Conviene que se vea antes.
}

#: Cuando no hay medida para esa combinación. Conservador a propósito: pasarse por arriba
#: hace esperar a alguien, pasarse por abajo llena el disco.
RATIO_POR_DEFECTO = 0.60

#: Megabytes de entrada por segundo, medidos sobre la ortofoto de referencia: 466 MB en 7 s
#: hacia GeoTIFF y en 9,4 s hacia JP2. Se toma el peor de los dos y se redondea a la baja.
MB_POR_SEGUNDO = 45.0

#: Las pirámides recorren la imagen otra vez, a un tercio de resolución acumulada.
RECARGO_POR_PIRAMIDES = 1.35


@dataclass(frozen=True)
class Estimacion:
    """Lo que se le dice a la persona antes de que pulse el botón."""

    bytes_salida: int
    segundos: float
    memoria_mb: int
    libre_bytes: int
    #: `False` cuando la estimación no se apoya en ninguna medida de esa combinación.
    medida: bool = True
    aviso: str = ""

    @property
    def cabe(self) -> bool:
        # Se pide el doble porque durante un instante conviven el parcial y el definitivo.
        return self.libre_bytes > self.bytes_salida * 2

    @property
    def crece(self) -> bool:
        """`True` si la salida va a pesar más que la entrada. Conviene decirlo."""
        return bool(self.aviso)

    @property
    def minutos(self) -> float:
        return self.segundos / 60


def estimar(
    *, inspeccion, formato_destino: str, opciones: dict | None = None, destino: Path | None = None
) -> Estimacion:
    """Estima la salida de esa conversión sobre ese archivo."""
    opciones = opciones or {}
    sin_comprimir = _bytes_sin_comprimir(inspeccion, opciones)

    clave, medida = _clave_de_ratio(formato_destino, opciones)
    ratio = RATIOS.get(clave, RATIO_POR_DEFECTO)

    bytes_salida = int(sin_comprimir * ratio)

    segundos = (inspeccion.bytes_totales / 1_048_576) / MB_POR_SEGUNDO
    if str(opciones.get("piramides", "")).strip():
        segundos *= RECARGO_POR_PIRAMIDES
    segundos = max(1.0, segundos)

    carpeta = (destino or Path(inspeccion.ruta)).parent
    try:
        libre = shutil.disk_usage(carpeta).free
    except OSError:
        libre = 0

    aviso = ""
    if bytes_salida > inspeccion.bytes_totales * 1.2:
        veces = bytes_salida / max(1, inspeccion.bytes_totales)
        aviso = f"La salida va a pesar unas {veces:.1f} veces el original."

    return Estimacion(
        bytes_salida=bytes_salida,
        segundos=segundos,
        memoria_mb=_memoria_mb(),
        libre_bytes=libre,
        medida=medida,
        aviso=aviso,
    )


def _bytes_sin_comprimir(inspeccion, opciones: dict) -> int:
    """El tamaño de la imagen en crudo, que es el único ancla comparable entre formatos."""
    cabecera = getattr(inspeccion, "tiff", None)
    if cabecera is None:
        # Sin cabecera legible no queda más que el tamaño del archivo. Es peor, y por eso
        # la estimación se marca como no medida más abajo.
        return inspeccion.bytes_totales

    bandas = cabecera.bandas
    if opciones.get("solo_rgb") and bandas > 3:
        bandas = 3

    return cabecera.ancho_px * cabecera.alto_px * bandas * max(1, cabecera.bits_por_muestra // 8)


def _clave_de_ratio(formato: str, opciones: dict) -> tuple[tuple[str, str], bool]:
    """La clave de `RATIOS`, y si hay medida para ella.

    Los formatos con pérdida ignoran la compresión: la calidad la fijan por su cuenta.
    """
    if formato in ("jp2", "ecw", "png", "jpeg", "webp", "asc"):
        clave = (formato, "")
    else:
        compresion = str(opciones.get("compresion", "DEFLATE")).upper()
        clave = (formato, compresion)
    return clave, clave in RATIOS


def _memoria_mb() -> int:
    """Lo que va a pedir el proceso hijo.

    Es el tope de caché de GDAL más un margen para el propio proceso. No es una predicción
    del uso real: es el techo, que es el dato que importa para saber si la estación se va a
    quedar sin memoria.
    """
    return int(getattr(settings, "GDAL_CACHEMAX_MB", 512)) + 128
