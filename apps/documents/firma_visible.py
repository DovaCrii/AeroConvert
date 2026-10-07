"""Estampar una firma visible —una imagen, con su fecha— en una página de un PDF.

**Esto no es una firma digital.** Es lo que se hace con una firma escaneada: ponerla donde va y
que se vea. No prueba quién firmó ni detecta cambios posteriores; para eso está la firma digital
(F14.5), que es otra herramienta y dice otra cosa. La pantalla lo explica para que nadie confunda
las dos.

## Dónde cae

Se coloca respecto a **lo que se ve**, no respecto a la hoja sin girar: una lámina apaisada con
`/Rotate 90` lleva la firma en la esquina que el lector ve, como en `marcas.numerar`, de donde se
reutilizan el lienzo, el giro y el pegado. Devuelve el rectángulo exacto que ocupa, en puntos y
con el origen abajo a la izquierda de la página **vista**, para que la prueba lo mida contra lo
que dibuja PDFium.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import marcas
from .composicion import ComposicionInvalida

#: Las mismas seis posiciones que la numeración, y por la misma razón: es donde se espera.
POSICIONES = marcas.POSICIONES

#: Ancho de la firma, en milímetros, con lo que sirve cada uno. Un campo libre invita a 400 mm.
ANCHOS_MM = {30: "Pequeña", 45: "Normal", 70: "Grande"}

MAXIMO_LEYENDA = 80

#: Lado mayor que se admite de la imagen, en píxeles: una firma escaneada a 600 ppp pesa mucho y
#: no se ve distinta a 3 000 px de ancho.
LADO_MAXIMO_PX = 6000


@dataclass(frozen=True)
class Estampado:
    pagina: int
    #: Esquina inferior izquierda y tamaño, en puntos, sobre la página **vista**.
    x: float
    y: float
    ancho: float
    alto: float
    ancho_pagina: float
    alto_pagina: float


def comprobar(posicion: str, ancho_mm: int, leyenda: str, pagina: int, total: int, nombre: str):
    """Lo que se puede decir antes de encolar. Devuelve la leyenda ya limpia."""
    if posicion not in POSICIONES:
        raise ComposicionInvalida(f"«{posicion}» no es una posición de las que se ofrecen.")
    if ancho_mm not in ANCHOS_MM:
        raise ComposicionInvalida(f"«{ancho_mm}» no es un tamaño de los que se ofrecen.")
    leyenda = " ".join((leyenda or "").split())
    if len(leyenda) > MAXIMO_LEYENDA:
        raise ComposicionInvalida(f"El texto bajo la firma no puede pasar de {MAXIMO_LEYENDA}.")
    if not 1 <= pagina <= total:
        raise ComposicionInvalida(f"{nombre} tiene {total} página(s): no existe la {pagina}.")
    return leyenda


def medir_imagen(ruta: str | Path) -> tuple[int, int]:
    """Las dimensiones de la imagen, abriéndola de verdad. Rechaza lo que no es una imagen."""
    from PIL import Image, UnidentifiedImageError

    ruta = Path(ruta)
    try:
        with Image.open(ruta) as imagen:
            imagen.load()
            ancho, alto = imagen.size
    except (UnidentifiedImageError, OSError) as fallo:
        raise ComposicionInvalida(f"{ruta.name} no es una imagen que se pueda abrir.") from fallo
    if max(ancho, alto) > LADO_MAXIMO_PX:
        raise ComposicionInvalida(
            f"La imagen mide {ancho} × {alto} px: pasa de {LADO_MAXIMO_PX}. Redúzcala antes."
        )
    return ancho, alto


def estampar(
    origen: str | Path,
    imagen: str | Path,
    destino: str | Path,
    *,
    pagina: int,
    posicion: str = "pie-derecha",
    ancho_mm: int = 45,
    leyenda: str = "",
) -> Estampado:
    """Escribe una copia con la firma puesta en la página `pagina` (1 es la primera)."""
    from pypdf import PdfWriter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth

    origen, imagen, destino = Path(origen), Path(imagen), Path(destino)
    lector = marcas._abrir(origen)
    leyenda = comprobar(posicion, ancho_mm, leyenda, pagina, len(lector.pages), origen.name)
    ancho_px, alto_px = medir_imagen(imagen)

    escritor = PdfWriter(clone_from=lector)
    hoja = escritor.pages[pagina - 1]
    caja = hoja.mediabox
    ancho, alto = float(caja.width), float(caja.height)
    lienzo, memoria = marcas._capa(ancho, alto)
    lienzo.translate(float(caja.left), float(caja.bottom))
    ancho_vista, alto_vista = marcas._encuadrar(lienzo, ancho, alto, marcas._giro(hoja))

    cuerpo = marcas._cuerpo(ancho_vista, alto_vista)
    margen = marcas.MARGEN_MM / marcas.MM_POR_PUNTO * (cuerpo / marcas.CUERPO_BASE)
    w = ancho_mm / marcas.MM_POR_PUNTO
    h = w * alto_px / ancho_px
    alto_leyenda = cuerpo * 1.3 if leyenda else 0.0
    bloque = h + alto_leyenda
    # Una firma más ancha que la hoja menos sus márgenes no cabe: se dice, no se recorta.
    if w > ancho_vista - 2 * margen or bloque > alto_vista - 2 * margen:
        raise ComposicionInvalida("La firma no cabe en la página con ese tamaño. Elija uno menor.")

    if posicion.endswith("izquierda"):
        x = margen
    elif posicion.endswith("centro"):
        x = (ancho_vista - w) / 2
    else:
        x = ancho_vista - margen - w
    base = alto_vista - margen - bloque if posicion.startswith("cabecera") else margen
    y = base + alto_leyenda  # la imagen va encima de su leyenda

    lienzo.drawImage(ImageReader(str(imagen)), x, y, width=w, height=h, mask="auto")
    if leyenda:
        lienzo.setFont(marcas.FUENTE, cuerpo)
        lienzo.setFillGray(0.15)
        ancho_texto = stringWidth(leyenda, marcas.FUENTE, cuerpo)
        lienzo.drawString(x + (w - ancho_texto) / 2, base + cuerpo * 0.3, leyenda)
    marcas._pegar(hoja, lienzo, memoria)

    with open(destino, "wb") as salida:
        escritor.write(salida)
    return Estampado(pagina, x, y, w, h, ancho_vista, alto_vista)
