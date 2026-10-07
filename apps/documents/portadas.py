"""Las portadas de J.E.J.: rellenar sus plantillas Word con los datos del documento.

## Qué hace

Toma una de las dos plantillas de la empresa y escribe en ella los datos que cambian en cada
documento: en «Portada Documentos», el **código** (`JEJ-…`), el **título** del procedimiento y el
**autor** (el del pie); en «Portada Ofertas y Planes Licitaciones», el **servicio** y el **plan**
(su pie es la leyenda «PLAN DE …»). Entrega un `.docx`; el PDF es un clic más con «Office a PDF»
si hay Word.

## Las plantillas no están en el repositorio

Llevan el logotipo y el diseño de la empresa. Viven en la carpeta que dice
`AEROCONVERT_PLANTILLAS_JEJ`; sin ella (o sin alguno de los dos archivos) la herramienta sale
**apagada con su motivo** y no se sustituye por una portada inventada.

## Cómo se rellenan

Las plantillas traen **marcadores de relleno** (`XXXXXX`) en el cuerpo, en el encabezado y en el
pie, y el autor en un control de contenido enlazado a las propiedades del documento. Se recorren
los textos de cada parte en orden y se sustituye por la **posición** que ocupan (el `XXXX` que
sigue a «JEJ-» es el código, el que sigue a «PROCEDIMIENTO» es el título…): así no hace falta
tocar la plantilla para que funcione, y si Word reorganiza los trozos de un mismo texto, no se
rompe mientras el orden se mantenga.

**Si un campo obligatorio no se encuentra, se falla** diciendo cuál: una portada con un `XXXXXX`
sin cambiar sale impresa en una oferta, y es peor que no entregar nada.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from django.conf import settings

from .composicion import ComposicionInvalida

MAXIMO_LARGO = 120

#: Un trozo de texto que es solo relleno: `XXXXXX`, o `XXXXXXXx` como el del autor.
_RELLENO = re.compile(r"^X{3,}x?$")
_TROZO = re.compile(r"(<w:t(?:\s[^>]*)?>)([^<]*)(</w:t>)")


@dataclass(frozen=True)
class Tipo:
    id: str
    nombre: str
    archivo: str
    #: Los campos, en el orden de la pantalla: (id, etiqueta, ejemplo).
    campos: tuple[tuple[str, str, str], ...]


TIPOS: dict[str, Tipo] = {
    "documento": Tipo(
        "documento",
        "Portada de documento (procedimiento)",
        "Portada Documentos.docx",
        (
            ("codigo", "Código", "010101"),
            ("titulo", "Título del procedimiento", "PROCEDIMIENTO DE TRABAJO SEGURO"),
            ("autor", "Autor", "Ana Pérez"),
        ),
    ),
    "oferta": Tipo(
        "oferta",
        "Portada de oferta o plan de licitación",
        "Portada Ofertas y Planes Licitaciones.docx",
        (
            ("servicio", "Servicio", "TOPOGRAFÍA Y LEVANTAMIENTO"),
            ("plan", "Plan", "CALIDAD"),
        ),
    ),
}


@dataclass(frozen=True)
class Disponible:
    tipos: frozenset[str] = field(default_factory=frozenset)
    motivo: str = ""
    sugerencia: str = ""

    def __bool__(self) -> bool:
        return bool(self.tipos)

    def tiene(self, tipo: str) -> bool:
        return tipo in self.tipos


def carpeta() -> Path | None:
    configurada = (getattr(settings, "PLANTILLAS_JEJ", "") or "").strip()
    return Path(configurada) if configurada else None


def sondar() -> Disponible:
    """Qué plantillas hay. Barato —mira dos archivos—, así que no se guarda en la caché."""
    base = carpeta()
    if base is None:
        return Disponible(
            motivo="No hay carpeta de plantillas de portada configurada en este servidor.",
            sugerencia=(
                "Copie «Portada Documentos.docx» y «Portada Ofertas y Planes Licitaciones.docx» "
                "a una carpeta y ponga su ruta en AEROCONVERT_PLANTILLAS_JEJ."
            ),
        )
    hay = frozenset(t.id for t in TIPOS.values() if (base / t.archivo).is_file())
    if not hay:
        return Disponible(
            motivo=f"En {base} no están las plantillas de portada.",
            sugerencia="Deben llamarse «Portada Documentos.docx» y «Portada Ofertas y Planes "
            "Licitaciones.docx».",
        )
    return Disponible(tipos=hay)


def _limpiar(campo: str, valor: str) -> str:
    texto = " ".join(str(valor or "").split())
    if not texto:
        raise ComposicionInvalida(f"Falta «{campo}».")
    if len(texto) > MAXIMO_LARGO:
        raise ComposicionInvalida(f"«{campo}» no puede pasar de {MAXIMO_LARGO} caracteres.")
    if any(ord(c) < 32 for c in texto):
        raise ComposicionInvalida(f"«{campo}» lleva caracteres que no se pueden escribir.")
    return texto


class _Cuenta:
    """Cuántas veces se sustituyó cada campo, para exigir que se haya encontrado."""

    def __init__(self) -> None:
        self.veces: dict[str, int] = {}

    def sumar(self, campo: str) -> None:
        self.veces[campo] = self.veces.get(campo, 0) + 1


def _rellenar_parte(xml: str, tipo: str, valores: dict[str, str], cuenta: _Cuenta) -> str:
    """Sustituye los marcadores de una parte (`document`, `header`, `footer`) por posición."""
    esperando: str | None = None  # el campo que se escribe en el próximo relleno suelto

    def cambiar(m: re.Match) -> str:
        nonlocal esperando
        abre, texto, cierra = m.groups()
        plano = texto.strip()

        if tipo == "documento":
            if plano == "JEJ-":
                esperando = "codigo"
                return m.group(0)
            if plano.startswith("PROCEDIMIENTO"):
                esperando = "titulo"
                return m.group(0)
        else:
            if plano.startswith("SERVICIO DE") and not plano.replace("SERVICIO DE", "").strip():
                esperando = "servicio"
                return m.group(0)
            if re.fullmatch(r"PLAN DE\s+X{3,}x?", plano):
                cuenta.sumar("plan")
                return f"{abre}PLAN DE {escape(valores['plan'])}{cierra}"

        if _RELLENO.match(plano):
            campo = esperando or "autor"
            esperando = None
            if campo not in valores:
                return m.group(0)
            cuenta.sumar(campo)
            return f"{abre}{escape(valores[campo])}{cierra}"
        return m.group(0)

    return _TROZO.sub(cambiar, xml)


def _autor_en_propiedades(xml: str, autor: str) -> str:
    """Las propiedades del documento: el control del pie está enlazado a `dc:creator`, y Word
    lo vuelve a escribir desde ahí al abrir. Si no se cambia, el autor vuelve a ser el de antes."""
    if re.search(r"<dc:creator>[^<]*</dc:creator>", xml):
        return re.sub(
            r"<dc:creator>[^<]*</dc:creator>", f"<dc:creator>{escape(autor)}</dc:creator>", xml
        )
    return xml.replace(
        "</cp:coreProperties>", f"<dc:creator>{escape(autor)}</dc:creator></cp:coreProperties>"
    )


def validar(tipo: str, valores: dict[str, str]) -> dict[str, str]:
    """Los valores ya limpios, o `ComposicionInvalida` con el campo que falla.

    Aparte de `rellenar` para que la pantalla lo diga **antes de encolar**.
    """
    if tipo not in TIPOS:
        raise ComposicionInvalida(f"«{tipo}» no es una portada de las que hay.")
    return {
        id_: _limpiar(etiqueta, valores.get(id_, "")) for id_, etiqueta, _ in TIPOS[tipo].campos
    }


def rellenar(
    tipo: str,
    valores: dict[str, str],
    destino: str | Path,
    *,
    base: str | Path | None = None,
) -> Path:
    """Escribe el `.docx` con los datos puestos. El archivo de plantilla no se toca."""
    if tipo not in TIPOS:
        raise ComposicionInvalida(f"«{tipo}» no es una portada de las que hay.")
    definicion = TIPOS[tipo]
    carpeta_de_plantillas = Path(base) if base is not None else carpeta()
    if carpeta_de_plantillas is None:
        raise ComposicionInvalida("No hay carpeta de plantillas de portada configurada.")
    plantilla = carpeta_de_plantillas / definicion.archivo
    if not plantilla.is_file():
        raise ComposicionInvalida(f"No está la plantilla «{definicion.archivo}».")

    limpios = {
        id_: _limpiar(etiqueta, valores.get(id_, "")) for id_, etiqueta, _ in definicion.campos
    }

    destino = Path(destino)
    cuenta = _Cuenta()
    try:
        with (
            zipfile.ZipFile(plantilla) as entrada,
            zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as salida,
        ):
            for parte in entrada.infolist():
                datos = entrada.read(parte.filename)
                if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", parte.filename):
                    datos = _rellenar_parte(datos.decode("utf-8"), tipo, limpios, cuenta).encode(
                        "utf-8"
                    )
                elif parte.filename == "docProps/core.xml":
                    # El pie de cada plantilla está enlazado a `dc:creator`: en «documento» es el
                    # autor; en «oferta» es la propia leyenda «PLAN DE …».
                    texto_del_pie = (
                        limpios["autor"] if tipo == "documento" else f"PLAN DE {limpios['plan']}"
                    )
                    datos = _autor_en_propiedades(datos.decode("utf-8"), texto_del_pie).encode(
                        "utf-8"
                    )
                salida.writestr(parte, datos)
    except zipfile.BadZipFile as fallo:
        destino.unlink(missing_ok=True)
        raise ComposicionInvalida(f"«{definicion.archivo}» no es un documento de Word.") from fallo

    faltan = [etiqueta for id_, etiqueta, _ in definicion.campos if not cuenta.veces.get(id_)]
    if faltan:
        destino.unlink(missing_ok=True)
        raise ComposicionInvalida(
            f"La plantilla «{definicion.archivo}» no tiene dónde poner: {', '.join(faltan)}. "
            "¿Cambió su diseño?"
        )
    return destino
