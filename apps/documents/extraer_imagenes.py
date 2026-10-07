"""Sacar las imágenes que lleva dentro un PDF, tal como están incrustadas.

No es lo mismo que `a_imagenes`, que **dibuja** cada página: aquí se entrega cada fotografía o
logotipo con la resolución con que se metió en el documento, sin volver a muestrearla. Sirve
para recuperar las fotos de un informe del que se perdió el original.

## Qué entra y qué no

- **Cada imagen una sola vez.** Un logotipo que se repite en las cien páginas del juego es un
  mismo objeto del PDF; sacarlo cien veces llenaría el zip de copias idénticas.
- **Las diminutas no** (por debajo de `MINIMO_PX` de lado): son filetes, viñetas y máscaras, no
  imágenes que nadie quiera guardar.
- **Todas o ninguna**, como al partir: media entrega con nombres correlativos es peor que un error.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .composicion import ComposicionInvalida

#: Lado mayor mínimo, en píxeles, para que una imagen cuente.
MINIMO_PX = 32

#: Las que solo se entregan por su extensión de origen; el resto sale como PNG.
EXTENSIONES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".jp2"}


class SinImagenes(ComposicionInvalida):
    """El PDF no lleva ninguna imagen que valga la pena sacar. No es un fallo: es la respuesta."""

    codigo = "sin-imagenes"


def extraer(
    origen: str | Path,
    carpeta: Path | None = None,
    *,
    minimo_px: int = MINIMO_PX,
    progreso: Callable[[float], None] | None = None,
) -> list[Path]:
    """Escribe una imagen por objeto del PDF y devuelve las rutas, por orden de aparición."""
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    origen = Path(origen)
    carpeta = Path(carpeta) if carpeta else origen.parent

    try:
        lector = PdfReader(str(origen))
    except (PyPdfError, OSError) as fallo:
        raise ComposicionInvalida(f"No se pudo abrir {origen.name}: {fallo}") from fallo
    if lector.is_encrypted:
        raise ComposicionInvalida(f"{origen.name} pide contraseña, así que no se pueden sacar.")

    vistas: set[int] = set()
    escritas: list[Path] = []
    total = len(lector.pages)
    try:
        for numero, pagina in enumerate(lector.pages, start=1):
            for orden, imagen in enumerate(pagina.images, start=1):
                referencia = getattr(imagen, "indirect_reference", None)
                idnum = getattr(referencia, "idnum", None)
                if idnum is not None:
                    if idnum in vistas:
                        continue
                    vistas.add(idnum)

                if max(imagen.image.size) < minimo_px:
                    continue

                sufijo = Path(imagen.name).suffix.lower()
                datos = imagen.data
                if sufijo not in EXTENSIONES:
                    sufijo = ".png"
                    datos = _a_png(imagen.image)
                destino = carpeta / f"{origen.stem}_p{numero}_{orden}{sufijo}"
                destino.write_bytes(datos)
                escritas.append(destino)
            if progreso is not None:
                progreso(numero / total)
    except Exception:
        for hecha in escritas:
            hecha.unlink(missing_ok=True)
        raise

    if not escritas:
        raise SinImagenes(f"{origen.name} no lleva ninguna imagen que valga la pena sacar.")
    return escritas


def _a_png(imagen) -> bytes:
    import io

    puesta = io.BytesIO()
    imagen.save(puesta, "PNG", optimize=True)
    return puesta.getvalue()
