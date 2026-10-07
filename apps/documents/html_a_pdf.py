"""Una página web guardada, a PDF: el texto, los títulos, las listas y las tablas.

## Lo que esto es, y lo que no

**No es un navegador.** No ejecuta JavaScript, no baja hojas de estilo ni imágenes y no respeta el
diseño: un PDF «igual que la página» exige un motor de página web, y traerlo (Chromium o similar)
es una decisión de instalación que no se ha tomado. Lo que sí hace bien es lo que casi siempre se
quiere de una página guardada: **un documento legible con su texto y sus tablas**.

Por eso no hay un convertidor propio: la página pasa por los dos que ya existen —de HTML a
Markdown (`a_markdown.de_html`) y de Markdown a PDF (`desde_markdown`)— y cada paso se prueba por
su lado. La pantalla lo dice antes de que alguien espere el diseño.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from . import a_markdown, desde_markdown
from .composicion import ComposicionInvalida

EXTENSIONES = frozenset({".html", ".htm", ".xhtml"})


class PaginaSinTexto(ComposicionInvalida):
    """La página no trae texto que poner en un PDF (solo imágenes o programas)."""


def convertir(origen: str | Path, destino: str | Path) -> int:
    """Escribe el PDF y devuelve cuántas páginas tiene."""
    from pypdf import PdfReader

    origen, destino = Path(origen), Path(destino)
    if origen.suffix.lower() not in EXTENSIONES:
        raise ComposicionInvalida(f"{origen.name} no es una página web (.html o .htm).")

    # Las imágenes no se bajan ni se dibujan: su marca de Markdown no es texto que poner en el PDF.
    markdown = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", a_markdown.de_html(origen)).strip()
    if not markdown:
        raise PaginaSinTexto(
            f"{origen.name} no tiene texto que poner en un PDF: es solo imágenes o programas."
        )

    with tempfile.TemporaryDirectory() as carpeta:
        intermedio = Path(carpeta) / f"{origen.stem}.md"
        intermedio.write_text(markdown + "\n", encoding="utf-8")
        desde_markdown.markdown_a_pdf(intermedio, destino=destino)
    return len(PdfReader(str(destino)).pages)
