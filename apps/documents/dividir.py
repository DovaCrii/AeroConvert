"""Partir un PDF en varios, y armar un PDF a partir de imágenes.

Las dos son la operación contraria a componer, y comparten una idea: **el resultado son
archivos nuevos y el original no se toca**.

## Los rangos se escriben como se dicen

`1-5, 8, 12-14` es lo que alguien teclea sin pensarlo, así que es lo que se acepta. Cada
trozo separado por comas es un archivo, y dentro un guion es un intervalo cerrado por los
dos lados —`1-5` son cinco páginas, no cuatro— porque es como se cuenta un documento.

**Lo que no se puede interpretar no se adivina.** Un `5-2` al revés, una página que no
existe, letras: se dice cuál falla y no se compone nada. Partir «casi bien» un entregable
es peor que no partirlo.

## Y una imagen no es una página

Un JPG no tiene tamaño de papel: tiene píxeles y, con suerte, una resolución declarada. Al
llevarlo a PDF hay que decidir de qué tamaño sale la hoja, y las dos respuestas razonables
son distintas de verdad:

- **A4** — la que se quiere para una monografía o un anexo de fotos: todas las hojas del
  mismo tamaño, aunque las fotos no lo sean. La imagen se centra con margen y **no se
  recorta**.
- **El tamaño de la imagen** — la que se quiere para un escaneo: la hoja mide lo que mide
  el original y no se remuestrea nada.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .composicion import ComposicionInvalida

#: Milimetros de un A4 vertical.
A4_MM = (210.0, 297.0)

#: Margen blanco alrededor de la imagen cuando se ajusta a A4.
MARGEN_MM = 10.0

#: Puntos PostScript por milimetro.
PUNTOS_POR_MM = 72 / 25.4

#: Resolucion que se supone cuando la imagen no declara ninguna. 96 es lo que asume
#: Windows, que es de donde salen casi todas las capturas y fotos que llegan aqui.
PPP_POR_DEFECTO = 96

#: Extensiones de imagen que se admiten. Pillow lee muchas mas, pero estas son las que
#: llegan de verdad, y aceptar de todo invita a que alguien suelte un `.psd` y se lleve un
#: mensaje raro en vez de uno claro.
IMAGENES = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"})

PATRON_RANGO = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")


@dataclass(frozen=True)
class Trozo:
    """Un archivo de salida: de la página `desde` a la `hasta`, las dos incluidas."""

    desde: int
    hasta: int

    @property
    def cuantas(self) -> int:
        return self.hasta - self.desde + 1

    @property
    def sufijo(self) -> str:
        """Lo que se le pega al nombre: `_1-5` o `_8`."""
        return f"_{self.desde}" if self.desde == self.hasta else f"_{self.desde}-{self.hasta}"


def analizar_rangos(texto: str, total: int) -> list[Trozo]:
    """`1-5, 8, 12-14` a trozos, comprobados contra el documento.

    Levanta `ComposicionInvalida` diciendo **cuál** falla. Un mensaje que solo diga «rangos
    no válidos» obliga a mirar los cinco a ojo.
    """
    trozos: list[Trozo] = []
    for crudo in (texto or "").split(","):
        if not crudo.strip():
            continue

        coincidencia = PATRON_RANGO.match(crudo)
        if coincidencia is None:
            raise ComposicionInvalida(
                f"«{crudo.strip()}» no es un rango. Se escriben así: 1-5, 8, 12-14."
            )

        desde = int(coincidencia.group(1))
        hasta = int(coincidencia.group(2) or desde)

        if desde < 1:
            raise ComposicionInvalida(f"«{crudo.strip()}»: las páginas se cuentan desde 1.")
        if hasta > total:
            raise ComposicionInvalida(f"«{crudo.strip()}»: el documento tiene {total} página(s).")
        if desde > hasta:
            raise ComposicionInvalida(
                f"«{crudo.strip()}» va al revés. Se escribe de la menor a la mayor."
            )

        trozos.append(Trozo(desde, hasta))

    if not trozos:
        raise ComposicionInvalida("No indicaste ningún rango.")
    return trozos


def una_por_pagina(total: int) -> list[Trozo]:
    """Un archivo por hoja. El otro modo de partir, y el más pedido."""
    return [Trozo(numero, numero) for numero in range(1, total + 1)]


def partir(origen: str | Path, trozos: Iterable[Trozo], carpeta: Path | None = None) -> list[Path]:
    """Escribe un PDF por trozo y devuelve las rutas, en orden.

    **Se escriben todos o ninguno.** Si el cuarto de cinco falla, los tres que ya estaban
    se borran: media entrega repartida en la carpeta, con nombres que parecen correctos, es
    peor que un error.
    """
    from pypdf import PdfReader, PdfWriter

    origen = Path(origen)
    carpeta = Path(carpeta) if carpeta else origen.parent
    trozos = list(trozos)
    if not trozos:
        raise ComposicionInvalida("No hay nada que partir.")

    try:
        lector = PdfReader(str(origen))
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo leer {origen.name}: {fallo}") from fallo

    total = len(lector.pages)
    escritos: list[Path] = []
    try:
        for trozo in trozos:
            if trozo.hasta > total:
                raise ComposicionInvalida(
                    f"{origen.name} tiene {total} página(s) y se pidió hasta la {trozo.hasta}."
                )

            escritor = PdfWriter()
            for numero in range(trozo.desde, trozo.hasta + 1):
                escritor.add_page(lector.pages[numero - 1])

            destino = carpeta / f"{origen.stem}{trozo.sufijo}.pdf"
            with open(destino, "wb") as salida:
                escritor.write(salida)
            escritos.append(destino)
    except Exception:
        for hecho in escritos:
            hecho.unlink(missing_ok=True)
        raise

    return escritos


def desde_imagenes(
    imagenes: Iterable[str | Path], destino: str | Path, *, tamano: str = "a4"
) -> int:
    """Arma un PDF con una página por imagen. Devuelve cuántas puso.

    `tamano` es `a4` —cada hoja A4, con la imagen centrada y sin recortar— o `imagen`, que
    hace la hoja del tamaño del original y no remuestrea nada.
    """
    from PIL import Image

    rutas = [Path(i) for i in imagenes]
    if not rutas:
        raise ComposicionInvalida("No indicaste ninguna imagen.")
    if tamano not in ("a4", "imagen"):
        raise ComposicionInvalida(f"«{tamano}» no es un tamaño de página conocido.")

    hojas = []
    try:
        for ruta in rutas:
            if ruta.suffix.lower() not in IMAGENES:
                raise ComposicionInvalida(
                    f"{ruta.name} no es una imagen de las que se admiten "
                    f"({', '.join(sorted(IMAGENES))})."
                )
            try:
                imagen = Image.open(ruta)
                imagen.load()
            except Exception as fallo:
                raise ComposicionInvalida(f"No se pudo abrir {ruta.name}: {fallo}") from fallo

            # A RGB sin excepción: un PNG con transparencia guardado en PDF deja el fondo
            # en negro, y una foto en escala de grises con paleta no se guarda tal cual.
            if imagen.mode != "RGB":
                fondo = Image.new("RGB", imagen.size, "white")
                if imagen.mode in ("RGBA", "LA", "P"):
                    convertida = imagen.convert("RGBA")
                    fondo.paste(convertida, mask=convertida.split()[-1])
                else:
                    fondo.paste(imagen.convert("RGB"))
                imagen = fondo

            hojas.append(_a_hoja(imagen, tamano))

        primera, *resto = hojas
        primera.save(
            str(destino),
            format="PDF",
            save_all=True,
            append_images=resto,
            resolution=float(PPP_POR_DEFECTO),
        )
    finally:
        for hoja in hojas:
            hoja.close()

    return len(rutas)


def _a_hoja(imagen, tamano: str):
    """La imagen puesta en la hoja que toca."""
    from PIL import Image

    if tamano == "imagen":
        return imagen

    # A4, con la orientación de la propia imagen: una foto apaisada en una hoja vertical
    # se queda en una franja diminuta con dos bandas blancas enormes.
    corto, largo = A4_MM
    ancho_mm, alto_mm = (largo, corto) if imagen.width > imagen.height else (corto, largo)

    ancho_px = round(ancho_mm / 25.4 * PPP_POR_DEFECTO)
    alto_px = round(alto_mm / 25.4 * PPP_POR_DEFECTO)
    margen_px = round(MARGEN_MM / 25.4 * PPP_POR_DEFECTO)

    hueco = (ancho_px - 2 * margen_px, alto_px - 2 * margen_px)
    copia = imagen.copy()
    # `thumbnail` respeta la proporción y **nunca amplía**: una foto pequeña no se estira
    # hasta reventarla de píxeles falsos.
    copia.thumbnail(hueco, Image.LANCZOS)

    hoja = Image.new("RGB", (ancho_px, alto_px), "white")
    hoja.paste(copia, ((ancho_px - copia.width) // 2, (alto_px - copia.height) // 2))
    copia.close()
    return hoja
