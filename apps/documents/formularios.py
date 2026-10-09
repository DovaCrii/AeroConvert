"""Rellenar un formulario PDF y, si se pide, aplanarlo.

Un PDF con campos (AcroForm) se rellena en el visor de cada cual, y al reenviarlo cualquiera puede
volver a cambiar lo escrito. **Aplanar** pasa los valores a la página y quita los campos: lo que
queda ya no se puede editar, que es lo que se quiere al entregar.

## Qué campos se tocan

- **Texto** y **casillas** (una casilla marcada o no). Es lo que lleva un formulario de oficina.
- Los demás —listas desplegables, botones de opción, firmas— **se muestran y no se editan**: la
  pantalla los nombra como tales en vez de ofrecer un campo que no hace lo que dice.

## Cómo se aplana

`pypdf` escribe los valores y genera la apariencia de cada campo; después **PDFium** pasa esa
apariencia a la página (`FPDFPage_Flatten`); y por último se reescribe el documento sin el
`AcroForm`, que PDFium deja con referencias a campos que ya no existen.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from apps.formats import pdf as _pdf_lectura

from .composicion import ComposicionInvalida

#: Bits de `/Ff` de un botón (ISO 32000-1, tabla 226): 16 es «opción» y 17 «botón de acción».
_OPCION = 1 << 15
_ACCION = 1 << 16

TEXTO = "texto"
CASILLA = "casilla"
OTRO = "otro"


@dataclass(frozen=True)
class Campo:
    nombre: str
    tipo: str
    valor: str
    #: Solo en las casillas: el nombre del estado «marcada» que trae el PDF (`/Yes`, `/On`…).
    marcada: str = ""
    solo_lectura: bool = False

    @property
    def editable(self) -> bool:
        return self.tipo in (TEXTO, CASILLA) and not self.solo_lectura

    @property
    def esta_marcada(self) -> bool:
        return self.tipo == CASILLA and self.valor == self.marcada


def _abrir(ruta: Path):
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        lector = PdfReader(str(ruta))
    except (PyPdfError, OSError) as fallo:
        raise ComposicionInvalida(f"No se pudo abrir {ruta.name}: {fallo}") from fallo
    if _pdf_lectura.pide_clave(lector):
        raise ComposicionInvalida(f"{ruta.name} pide contraseña, así que no se puede rellenar.")
    return lector


def _clasificar(nombre: str, campo: dict) -> Campo:
    tipo_pdf = str(campo.get("/FT", ""))
    banderas = int(campo.get("/Ff", 0) or 0)
    valor = campo.get("/V", "")
    valor = "" if valor is None else str(valor)
    solo_lectura = bool(banderas & 1)

    if tipo_pdf == "/Tx":
        return Campo(nombre, TEXTO, valor, solo_lectura=solo_lectura)
    if tipo_pdf == "/Btn" and not banderas & (_OPCION | _ACCION):
        estados = [str(e) for e in campo.get("/_States_", []) if str(e) != "/Off"]
        return Campo(
            nombre,
            CASILLA,
            valor or "/Off",
            marcada=estados[0] if estados else "/Yes",
            solo_lectura=solo_lectura,
        )
    return Campo(nombre, OTRO, valor, solo_lectura=True)


def listar(origen: str | Path) -> list[Campo]:
    """Los campos del formulario, en el orden del documento. Vacío si no es un formulario."""
    lector = _abrir(Path(origen))
    return [_clasificar(nombre, campo) for nombre, campo in (lector.get_fields() or {}).items()]


def rellenar(
    origen: str | Path,
    destino: str | Path,
    valores: dict[str, str | bool],
    *,
    aplanar: bool = False,
) -> int:
    """Escribe una copia con los valores puestos. Devuelve cuántos campos se rellenaron."""
    from pypdf import PdfWriter

    ruta = Path(origen)
    campos = {c.nombre: c for c in listar(ruta)}
    if not campos:
        raise ComposicionInvalida(f"{ruta.name} no tiene campos de formulario.")

    por_escribir: dict[str, str] = {}
    for nombre, valor in valores.items():
        campo = campos.get(nombre)
        if campo is None:
            raise ComposicionInvalida(f"El formulario no tiene un campo «{nombre}».")
        if not campo.editable:
            raise ComposicionInvalida(f"«{nombre}» no se puede editar desde aquí.")
        if campo.tipo == CASILLA:
            por_escribir[nombre] = campo.marcada if valor else "/Off"
        else:
            por_escribir[nombre] = str(valor)

    escritor = PdfWriter(clone_from=_abrir(ruta))
    for pagina in escritor.pages:
        escritor.update_page_form_field_values(pagina, por_escribir, auto_regenerate=False)

    puesto = io.BytesIO()
    escritor.write(puesto)
    datos = puesto.getvalue()

    if aplanar:
        datos = _aplanar(datos)

    Path(destino).write_bytes(datos)
    return len(por_escribir)


def _aplanar(datos: bytes) -> bytes:
    import pypdfium2
    import pypdfium2.raw as raw
    from pypdf import PdfReader, PdfWriter

    documento = pypdfium2.PdfDocument(datos)
    try:
        documento.init_forms()
        for numero in range(len(documento)):
            pagina = documento[numero]
            try:
                resultado = raw.FPDFPage_Flatten(pagina.raw, raw.FLAT_NORMALDISPLAY)
            finally:
                pagina.close()
            if resultado == raw.FLATTEN_FAIL:
                raise ComposicionInvalida(f"No se pudo aplanar la página {numero + 1}.")
        plano = io.BytesIO()
        documento.save(plano)
    finally:
        documento.close()

    # PDFium deja el `AcroForm` apuntando a campos que ya no existen. Se reescribe **página a
    # página** y no con `append`, que copiaría también el `AcroForm` (y, borrándolo después, sus
    # campos quedarían sueltos dentro del archivo).
    escritor = PdfWriter()
    lector = PdfReader(io.BytesIO(plano.getvalue()))
    for pagina in lector.pages:
        escritor.add_page(pagina)
    final = io.BytesIO()
    escritor.write(final)
    return final.getvalue()
