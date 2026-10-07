"""Convertir, redimensionar, recortar, girar y comprimir imágenes **por lote**.

Lo que se necesita casi siempre con las fotos de una obra: que entren en un correo (más chicas y
más ligeras), que abran en todas partes (HEIC o WebP a JPG) o que queden todas del mismo formato.
Aquí se hace todo a la vez y se entrega **un zip con una imagen por cada una que entró**.

## Qué se conserva

- **La orientación**: una foto de teléfono lleva «girada 90°» en su EXIF, y quitar el EXIF sin
  aplicarla la deja de lado. Por omisión se **aplica** y la marca vuelve a «normal».
- **El resto del EXIF** (fecha, cámara, **GPS**) en JPEG, WebP y TIFF, que lo admiten. Quitarlo es
  otra decisión, con su propia pantalla (F14.14): aquí no se pierde nada sin pedirlo.
- El **perfil de color**, que es lo que mantiene los colores de una foto al cambiar de formato.

## Qué no se hace en silencio

Un formato que este servidor no sabe leer **se dice** (HEIC necesita `pillow-heif`, que no es
dependencia): no se entrega un lote al que le falta una foto sin avisar. Y un lote es **todo o
nada**: si una imagen no se abre, no sale zip a medias con nombres que parecen completos.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .composicion import ComposicionInvalida

#: Formatos de salida: nombre → (formato de Pillow, extensión).
SALIDAS = {
    "jpg": ("JPEG", ".jpg"),
    "png": ("PNG", ".png"),
    "webp": ("WEBP", ".webp"),
    "tiff": ("TIFF", ".tif"),
}

ETIQUETAS_DE_SALIDA = {
    "jpg": "JPG — el que abre en todas partes",
    "png": "PNG — sin pérdida, con transparencia",
    "webp": "WebP — más ligero que el JPG",
    "tiff": "TIFF — para archivar (sin comprimir si la foto trae GPS)",
}

#: Lado mayor máximo, en píxeles. 0 es «no cambiar». Nunca se agranda: una foto de 1 000 px
#: pedida a 4 096 se queda en 1 000.
LADOS = {0: "Sin cambiar", 4096: "4096 px", 2048: "2048 px", 1600: "1600 px", 1024: "1024 px"}

GIROS = {
    "exif": "Según la orientación de la foto (recomendado)",
    "0": "No girar",
    "90": "90° a la derecha",
    "180": "180°",
    "270": "90° a la izquierda",
}

#: Recorte centrado a una proporción. Vacío es «no recortar».
RECORTES = {"": "No recortar", "1:1": "1:1", "4:3": "4:3", "3:2": "3:2", "16:9": "16:9"}

CALIDADES = {95: "Máxima", 85: "Buena", 70: "Ligera"}

MAXIMO_IMAGENES = 200

#: Lo que Pillow lee de fábrica. HEIC se suma si `pillow-heif` está.
EXTENSIONES_BASE = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif", ".avif"}
)

LADO_MAXIMO_LEIDO = 20_000


def _registrar_heic() -> bool:
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return False
    register_heif_opener()
    return True


def extensiones_admitidas() -> frozenset[str]:
    """Las que este servidor sabe abrir **ahora** (HEIC solo con `pillow-heif`)."""
    if _registrar_heic():
        return EXTENSIONES_BASE | {".heic", ".heif"}
    return EXTENSIONES_BASE


def motivo_si_no_se_lee(nombre: str) -> str:
    """Por qué una extensión no se puede abrir aquí, o vacío si sí."""
    sufijo = Path(nombre).suffix.lower()
    if sufijo in extensiones_admitidas():
        return ""
    if sufijo in (".heic", ".heif"):
        return (
            f"{nombre} es HEIC, y este servidor no trae el lector (`pillow-heif`). "
            "Pásela a JPG en el teléfono, o pida que lo instalen."
        )
    return f"{nombre} no es una imagen de las que se leen aquí."


@dataclass(frozen=True)
class Salida:
    entrada: str
    salida: str
    ancho: int
    alto: int
    bytes: int


def _proporcion(texto: str) -> float:
    ancho, alto = texto.split(":")
    return int(ancho) / int(alto)


def _recortar(imagen, proporcion: float):
    ancho, alto = imagen.size
    if ancho / alto > proporcion:
        nuevo = round(alto * proporcion)
        izq = (ancho - nuevo) // 2
        return imagen.crop((izq, 0, izq + nuevo, alto))
    nuevo = round(ancho / proporcion)
    arriba = (alto - nuevo) // 2
    return imagen.crop((0, arriba, ancho, arriba + nuevo))


def _nombre_libre(base: str, extension: str, usados: set[str]) -> str:
    nombre = f"{base}{extension}"
    n = 2
    while nombre.lower() in usados:
        nombre = f"{base}_{n}{extension}"
        n += 1
    usados.add(nombre.lower())
    return nombre


def procesar(
    origenes: list[Path],
    carpeta: Path,
    *,
    formato: str = "jpg",
    lado_max: int = 0,
    giro: str = "exif",
    recorte: str = "",
    calidad: int = 85,
    progreso: Callable[[float], None] | None = None,
) -> list[Salida]:
    """Escribe una imagen por entrada en `carpeta`. Todo o nada."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if formato not in SALIDAS:
        raise ComposicionInvalida(f"«{formato}» no es un formato de salida de los que se hacen.")
    if lado_max not in LADOS:
        raise ComposicionInvalida(f"«{lado_max}» no es un tamaño de los que se ofrecen.")
    if giro not in GIROS:
        raise ComposicionInvalida(f"«{giro}» no es un giro de los que se ofrecen.")
    if recorte not in RECORTES:
        raise ComposicionInvalida(f"«{recorte}» no es una proporción de las que se ofrecen.")
    if calidad not in CALIDADES:
        raise ComposicionInvalida(f"«{calidad}» no es una calidad de las que se ofrecen.")
    if not origenes:
        raise ComposicionInvalida("No indicó ninguna imagen.")
    if len(origenes) > MAXIMO_IMAGENES:
        raise ComposicionInvalida(f"El máximo son {MAXIMO_IMAGENES} imágenes por lote.")

    nombre_pillow, extension = SALIDAS[formato]
    _registrar_heic()
    escritas: list[Path] = []
    informe: list[Salida] = []
    usados: set[str] = set()
    try:
        for indice, ruta in enumerate(origenes, start=1):
            ruta = Path(ruta)
            try:
                with Image.open(ruta) as abierta:
                    abierta.load()
                    exif = abierta.getexif()
                    perfil = abierta.info.get("icc_profile")
                    imagen = abierta.copy()
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as fallo:
                raise ComposicionInvalida(
                    f"{ruta.name} no se pudo abrir como imagen: {fallo}"
                ) from fallo
            if max(imagen.size) > LADO_MAXIMO_LEIDO:
                raise ComposicionInvalida(
                    f"{ruta.name} mide más de {LADO_MAXIMO_LEIDO} px de lado."
                )

            if giro == "exif":
                imagen = ImageOps.exif_transpose(imagen)
            elif giro != "0":
                imagen = imagen.rotate(-int(giro), expand=True)
            if recorte:
                imagen = _recortar(imagen, _proporcion(recorte))
            if lado_max and max(imagen.size) > lado_max:
                imagen.thumbnail((lado_max, lado_max), Image.Resampling.LANCZOS)

            opciones: dict = {}
            if formato == "jpg":
                if imagen.mode in ("RGBA", "LA", "P"):
                    fondo = Image.new("RGB", imagen.size, (255, 255, 255))
                    convertida = imagen.convert("RGBA")
                    fondo.paste(convertida, mask=convertida.getchannel("A"))
                    imagen = fondo
                elif imagen.mode != "RGB":
                    imagen = imagen.convert("RGB")
                opciones = {"quality": calidad, "optimize": True}
            elif formato == "webp":
                opciones = {"quality": calidad}
            elif formato == "png":
                opciones = {"optimize": True}
            elif formato == "tiff":
                opciones = {"compression": "tiff_lzw"}

            if exif and formato in ("jpg", "webp", "tiff"):
                exif[0x0112] = 1  # ya está aplicada: «normal»
                opciones["exif"] = exif
                if formato == "tiff":
                    # Medido: con EXIF, libtiff rechaza toda compresión («Error setting from
                    # dictionary») salvo `raw`. Se prefiere conservar la fecha y el GPS a
                    # ahorrar bytes: un TIFF de archivo con su posición vale más que uno chico.
                    opciones["compression"] = "raw"
            if perfil:
                opciones["icc_profile"] = perfil

            destino = carpeta / _nombre_libre(ruta.stem, extension, usados)
            imagen.save(destino, nombre_pillow, **opciones)
            escritas.append(destino)
            informe.append(
                Salida(
                    ruta.name, destino.name, imagen.size[0], imagen.size[1], destino.stat().st_size
                )
            )
            if progreso is not None:
                progreso(indice / len(origenes))
    except Exception:
        for hecha in escritas:
            hecha.unlink(missing_ok=True)
        raise
    return informe
