"""Markdown a PDF: el camino de vuelta, para entregar lo que se redactó en Markdown.

## Sin dependencia nueva, y por qué se puede

Lo normal para esto es traer un analizador de Markdown y luego un motor de HTML a PDF. El
segundo es el caro: `weasyprint` arrastra Pango, Cairo y las tipografías del sistema, y lo que
entrega es *parecido* a lo que se pidió.

Aquí no hace falta, y la razón es concreta: **el Markdown que hay que imprimir lo escribe
`a_markdown.py`**, y ese emite un subconjunto conocido y pequeño — títulos, párrafos, listas,
tablas, negrita, cursiva y bloques de código. Para ese subconjunto, `reportlab` —que ya está
dentro, y que ya escribe las marcas de agua y la numeración— basta.

## Lo que NO cubre, y se dice antes de convertir

Imágenes, HTML incrustado, notas al pie, tablas con celdas combinadas y enlaces de referencia.
Un Markdown escrito a mano puede traer cualquiera de esas cosas: lo que se hace es **imprimir
su texto tal cual** en vez de tragárselo en silencio, que es lo que haría un analizador
incompleto y es lo que hace difícil darse cuenta.
"""

from __future__ import annotations

import re
from pathlib import Path

from .composicion import ComposicionInvalida

#: Tope de líneas. Un Markdown de cien mil líneas es un volcado, no un documento, y armar
#: cien mil «flowables» de reportlab se lleva la memoria de la máquina antes de escribir nada.
TOPE_LINEAS = 50_000

_TITULO = re.compile(r"^(#{1,6})\s+(.*)$")
_VINETA = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMERADA = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_CITA = re.compile(r"^>\s?(.*)$")
_SEPARADOR_DE_TABLA = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")
_CERCA = re.compile(r"^\s*(```|~~~)")


def _escapar(texto: str) -> str:
    """Para el mini-HTML de reportlab.

    **El orden importa**: el `&` primero, o se acabarían escapando los `&` que acaba de
    escribir el escape de `<`, y un `<` del texto original saldría como `&amp;lt;`.
    """
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _con_formato(texto: str) -> str:
    """Negrita, cursiva y código en línea, al mini-HTML que entiende `Paragraph`.

    Se hace **después** de escapar, así que las etiquetas que se escriben aquí son las únicas
    que llegan vivas: un `<b>` que viniera en el Markdown original ya es `&lt;b&gt;` y se
    imprime como texto, que es lo correcto — este módulo no interpreta HTML incrustado.
    """
    texto = _escapar(texto)
    # Los escapes de Markdown, a un sitio donde no estorben, y de vuelta al final.
    texto = texto.replace(r"\*", "\x00").replace(r"\|", "|").replace("\\\\", "\x01")

    texto = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', texto)
    texto = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", texto)
    texto = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", texto)
    texto = re.sub(r"\*(.+?)\*", r"<i>\1</i>", texto)

    return texto.replace("\x00", "*").replace("\x01", "\\")


def _estilos():
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    hoja = getSampleStyleSheet()
    hoja.add(
        ParagraphStyle(
            "Cita",
            parent=hoja["BodyText"],
            leftIndent=18,
            textColor="#555555",
            borderPadding=0,
        )
    )
    hoja.add(
        ParagraphStyle(
            "Codigo",
            parent=hoja["BodyText"],
            fontName="Courier",
            fontSize=8.5,
            leading=11,
            leftIndent=12,
            alignment=TA_LEFT,
        )
    )
    return hoja


def _tabla_flotante(filas: list[list[str]], ancho: float):
    """Una tabla de Markdown convertida en tabla de reportlab.

    Las celdas van en `Paragraph` y no como texto suelto: sin eso, una celda larga no parte
    línea y la tabla se sale de la hoja por la derecha, sin aviso y sin recorte.
    """
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    hoja = _estilos()
    cuerpo = [[Paragraph(_con_formato(c), hoja["BodyText"]) for c in fila] for fila in filas]

    columnas = max(len(f) for f in cuerpo)
    tabla = Table(cuerpo, colWidths=[ancho / columnas] * columnas, repeatRows=1)
    tabla.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b9c2d0")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return tabla


def _celdas(linea: str) -> list[str]:
    crudo = linea.strip()
    if crudo.startswith("|"):
        crudo = crudo[1:]
    if crudo.endswith("|") and not crudo.endswith("\\|"):
        crudo = crudo[:-1]
    # La barra escapada es contenido, no separador: es justo lo que escribe `a_markdown`.
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", crudo)]


def markdown_a_pdf(origen: str | Path, *, destino: Path | None = None) -> Path:
    """Escribe el PDF y devuelve su ruta.

    Atómica como el resto: parcial y renombrado. Un fallo a mitad no deja un PDF truncado con
    pinta de estar bien, que es exactamente lo que un visor abriría sin quejarse.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

    origen = Path(origen)
    try:
        texto = origen.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        texto = origen.read_text(encoding="latin-1")
    except OSError as fallo:
        raise ComposicionInvalida(f"No se pudo leer {origen.name}: {fallo}") from fallo

    lineas = texto.splitlines()
    if len(lineas) > TOPE_LINEAS:
        raise ComposicionInvalida(
            f"{origen.name} tiene {len(lineas)} líneas y el tope son {TOPE_LINEAS}. "
            "Eso ya no es un documento: pártelo antes."
        )
    if not texto.strip():
        raise ComposicionInvalida(f"{origen.name} está vacío.")

    hoja = _estilos()
    destino = Path(destino) if destino else origen.with_suffix(".pdf")
    ancho_util = A4[0] - 40 * mm

    piezas: list = []
    parrafo: list[str] = []
    vinetas: list[str] = []
    tabla: list[list[str]] = []
    codigo: list[str] = []
    en_codigo = False

    def cerrar_parrafo():
        if parrafo:
            piezas.append(Paragraph(_con_formato(" ".join(parrafo)), hoja["BodyText"]))
            parrafo.clear()

    def cerrar_vinetas():
        if vinetas:
            piezas.append(
                ListFlowable(
                    [
                        ListItem(Paragraph(_con_formato(v), hoja["BodyText"]), leftIndent=14)
                        for v in vinetas
                    ],
                    bulletType="bullet",
                    start="•",
                    leftIndent=14,
                )
            )
            vinetas.clear()

    def cerrar_tabla():
        if tabla:
            piezas.append(_tabla_flotante(list(tabla), ancho_util))
            piezas.append(Spacer(1, 6))
            tabla.clear()

    def cerrar_todo():
        cerrar_parrafo()
        cerrar_vinetas()
        cerrar_tabla()

    for linea in lineas:
        if _CERCA.match(linea):
            if en_codigo:
                piezas.append(Paragraph(_escapar("\n".join(codigo)), hoja["Codigo"]))
                codigo.clear()
            else:
                cerrar_todo()
            en_codigo = not en_codigo
            continue

        if en_codigo:
            codigo.append(linea)
            continue

        if not linea.strip():
            cerrar_todo()
            continue

        # **La fila de guiones no se imprime.** Es la que declara la tabla en Markdown, y
        # pintarla como una fila más mete una banda de rayas debajo del encabezado.
        if _SEPARADOR_DE_TABLA.match(linea) and tabla:
            continue

        if "|" in linea and re.search(r"(?<!\\)\|", linea):
            cerrar_parrafo()
            cerrar_vinetas()
            tabla.append(_celdas(linea))
            continue
        cerrar_tabla()

        if titulo := _TITULO.match(linea):
            cerrar_todo()
            nivel = min(len(titulo.group(1)), 4)
            piezas.append(Paragraph(_con_formato(titulo.group(2)), hoja[f"Heading{nivel}"]))
            continue

        if cita := _CITA.match(linea):
            cerrar_parrafo()
            cerrar_vinetas()
            piezas.append(Paragraph(_con_formato(cita.group(1)), hoja["Cita"]))
            continue

        if punto := (_VINETA.match(linea) or _NUMERADA.match(linea)):
            cerrar_parrafo()
            vinetas.append(punto.group(1))
            continue

        cerrar_vinetas()
        parrafo.append(linea.strip())

    if en_codigo and codigo:
        # Una cerca sin cerrar. Se imprime lo que hay: perderlo sería peor que enseñarlo.
        piezas.append(Paragraph(_escapar("\n".join(codigo)), hoja["Codigo"]))
    cerrar_todo()

    if not piezas:
        raise ComposicionInvalida(f"{origen.name} no tiene nada que imprimir.")

    parcial = destino.with_name(destino.name + ".parcial")
    documento = SimpleDocTemplate(
        str(parcial),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=origen.stem,
    )
    try:
        documento.build(piezas)
    except Exception as fallo:
        parcial.unlink(missing_ok=True)
        raise ComposicionInvalida(f"No se pudo componer el PDF: {fallo}") from fallo

    parcial.replace(destino)
    return destino
