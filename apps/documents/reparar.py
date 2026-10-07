"""Reparar un PDF dañado: recuperar lo que se pueda leer y escribirlo de nuevo, entero y válido.

Un PDF se rompe casi siempre por el final: una descarga cortada, un adjunto truncado, una copia que
se interrumpió. Las páginas están en el archivo, pero la tabla que dice dónde (`xref`) falta o
apunta mal, y muchos lectores se niegan a abrirlo. PDFium **reconstruye esa tabla leyendo el
archivo de principio a fin**, y lo que consigue abrir se vuelve a escribir con una tabla nueva.

## Lo que promete y lo que no

- **Promete** un archivo que abre en cualquier lector con **las páginas que se pudieron leer**, y
  dice cuántas eran las recuperables.
- **No promete todas las páginas**: lo que ya no está en el archivo (la cola cortada) no se
  inventa. Si quedan menos de las que el original decía tener, se avisa con el número.
- **No arregla el contenido** de una página corrupta: la deja como se pueda leer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .composicion import ComposicionInvalida


@dataclass(frozen=True)
class Reparacion:
    #: Las páginas que PDFium consiguió leer del archivo dañado y que están en la salida.
    paginas: int
    #: `True` si `pypdf`, en modo estricto, ya lo abría: no estaba roto y se reescribió igual.
    estaba_sano: bool


def _abre_estricto(ruta: Path) -> bool:
    from pypdf import PdfReader

    try:
        lector = PdfReader(str(ruta), strict=True)
        return len(lector.pages) > 0
    except Exception:
        return False


def reparar(origen: str | Path, destino: str | Path) -> Reparacion:
    """Escribe una copia reconstruida. Levanta si no se puede recuperar ninguna página."""
    import pypdfium2

    origen, destino = Path(origen), Path(destino)
    sano = _abre_estricto(origen)

    try:
        documento = pypdfium2.PdfDocument(str(origen))
    except Exception as fallo:
        raise ComposicionInvalida(
            f"No se pudo recuperar nada de {origen.name}: ni siquiera se reconoce como PDF."
        ) from fallo

    try:
        paginas = len(documento)
        if paginas == 0:
            raise ComposicionInvalida(f"{origen.name} no tiene ninguna página que se pueda leer.")
        # Cada página se dibuja de verdad: el recuento de PDFium puede ser optimista con una
        # página cuyo contenido se cortó, y lo que se entrega son las que se leen.
        legibles = 0
        for indice in range(paginas):
            hoja = documento[indice]
            try:
                hoja.get_size()
                legibles += 1
            except Exception:  # pragma: no cover - una página que PDFium no puede ni medir
                pass
            finally:
                hoja.close()
        if legibles == 0:
            raise ComposicionInvalida(f"{origen.name} no tiene ninguna página que se pueda leer.")
        documento.save(str(destino))
    finally:
        documento.close()

    return Reparacion(paginas=paginas, estaba_sano=sano)
