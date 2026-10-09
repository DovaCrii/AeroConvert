"""Ver, editar y limpiar los metadatos de un PDF antes de entregarlo.

Un PDF que sale de la oficina lleva, sin que nadie lo haya pedido, quién lo hizo, con qué programa
y cuándo —el `Info` del documento— y, muchas veces, una segunda copia en XMP. **Las dos hay que
tratarlas**: limpiar solo la primera deja el nombre del autor a la vista en la segunda.

## Qué hace y qué no

- **Limpiar** borra el `Info` entero y el paquete XMP del documento.
- **Editar** cambia los campos pedidos en el `Info` y **retira el XMP**, porque dejarlo diría lo
  de antes y contradiría lo nuevo.
- **No toca el contenido.** Una fotografía incrustada puede traer su propio EXIF: eso no es
  metadatos del documento y esta herramienta no lo promete (la pantalla lo dice).
- **El original no se toca**: se escribe una copia.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apps.formats import pdf as _pdf_lectura

from .composicion import ComposicionInvalida

#: Los campos del `Info` que se editan, con su nombre en el PDF. El orden es el de la pantalla.
CAMPOS = {
    "titulo": "/Title",
    "autor": "/Author",
    "asunto": "/Subject",
    "palabras_clave": "/Keywords",
    "creador": "/Creator",
    "productor": "/Producer",
}


@dataclass(frozen=True)
class Metadatos:
    campos: dict[str, str]
    #: Fechas tal como las escribió el programa (`D:2026…`); no se editan.
    creado: str
    modificado: str
    tiene_xmp: bool

    @property
    def vacio(self) -> bool:
        return (
            not any(self.campos.values())
            and not self.tiene_xmp
            and not (self.creado or self.modificado)
        )


def _abrir(ruta: Path):
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        lector = PdfReader(str(ruta))
    except (PyPdfError, OSError) as fallo:
        raise ComposicionInvalida(f"No se pudo abrir {ruta.name}: {fallo}") from fallo
    if _pdf_lectura.pide_clave(lector):
        raise ComposicionInvalida(f"{ruta.name} pide contraseña, así que no se puede leer.")
    return lector


def leer(origen: str | Path) -> Metadatos:
    ruta = Path(origen)
    lector = _abrir(ruta)
    info = lector.metadata or {}
    return Metadatos(
        campos={nombre: str(info.get(clave, "") or "") for nombre, clave in CAMPOS.items()},
        creado=str(info.get("/CreationDate", "") or ""),
        modificado=str(info.get("/ModDate", "") or ""),
        tiene_xmp="/Metadata" in lector.trailer["/Root"],
    )


def escribir(
    origen: str | Path,
    destino: str | Path,
    *,
    cambios: dict[str, str] | None = None,
    limpiar: bool = False,
) -> int:
    """Escribe una copia con los metadatos pedidos. Devuelve cuántas páginas tiene."""
    from pypdf import PdfWriter

    ruta = Path(origen)
    lector = _abrir(ruta)
    desconocidos = set(cambios or {}) - set(CAMPOS)
    if desconocidos:
        raise ComposicionInvalida(f"No se edita «{sorted(desconocidos)[0]}».")

    # **Un documento nuevo al que se le pasan las páginas**, y no una copia del original con
    # un campo borrado: pypdf, al borrar `/Metadata` de la raíz, deja el flujo XMP suelto dentro
    # del archivo —sin que nada lo apunte pero con el nombre del autor en los bytes—. Con
    # `append` solo viaja lo que se alcanza desde las páginas, y el `Info` y el XMP del original
    # no están entre eso.
    escritor = PdfWriter()
    escritor.append(lector)

    if limpiar:
        # El documento nuevo trae su propio `Producer` («pypdf»): tampoco se queda.
        if escritor._info is not None:
            escritor._info.clear()
    else:
        # Editar: el `Info` anterior con los cambios encima. El XMP **no** vuelve: diría lo de
        # antes y contradiría lo nuevo.
        conservados = {str(k): str(v) for k, v in (lector.metadata or {}).items()}
        for nombre, valor in (cambios or {}).items():
            conservados[CAMPOS[nombre]] = valor
        escritor.add_metadata(conservados)

    destino = Path(destino)
    with open(destino, "wb") as salida:
        escritor.write(salida)
    return len(lector.pages)
