"""Markdown a EPUB 3: un libro electrónico que se lee en el teléfono, el lector o Calibre.

## Por qué desde Markdown

`a_markdown.py` ya sabe sacar el contenido de un PDF, un Word, un HTML o un EPUB a Markdown, y
ese Markdown es un subconjunto pequeño y conocido (títulos, párrafos, listas, tablas, citas,
negrita, cursiva y código). Pasar de ahí a EPUB cierra el camino para **todos esos orígenes a la
vez**, con la misma lectura que ya está probada, y sin dependencia nueva: un EPUB es un zip con
XHTML dentro.

## Lo que se garantiza

- **Un EPUB 3 válido**: `mimetype` primero y sin comprimir, `container.xml`, el paquete OPF con
  identificador único y fecha de modificación, la tabla de contenidos `nav.xhtml` y, para los
  lectores viejos, `toc.ncx`. El oráculo es **EPUBCheck** (W3C), un lector distinto de este
  (`docs/PRUEBAS_CON_ORACULO.md`).
- **Un capítulo por título de primer nivel** (o de segundo, si el documento no trae ninguno de
  primero): el índice del lector salta a cada uno.
- **El texto se escapa siempre.** Un `<script>` que viniera en el Markdown llega al libro como
  texto, nunca como etiqueta: este módulo no interpreta HTML incrustado.

## Lo que no hace

No lleva imágenes ni maqueta: un PDF de planos o un escaneo da un EPUB de texto o vacío, y
`a_markdown` ya avisa cuando el PDF no tiene texto. Tampoco divide un capítulo enorme en
varios archivos.
"""

from __future__ import annotations

import html
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .composicion import ComposicionInvalida

#: El mismo tope que `desde_markdown`: cien mil líneas son un volcado, no un libro.
TOPE_LINEAS = 50_000

_TITULO = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_VINETA = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMERADA = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_CITA = re.compile(r"^>\s?(.*)$")
_SEPARADOR_DE_TABLA = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")
_CERCA = re.compile(r"^\s*(```|~~~)")

ESTILO = """body { font-family: serif; line-height: 1.5; margin: 0 5%; }
h1, h2, h3, h4 { font-family: sans-serif; line-height: 1.2; }
table { border-collapse: collapse; margin: 1em 0; }
th, td { border: 1px solid #888; padding: 0.2em 0.5em; text-align: left; }
pre { white-space: pre-wrap; font-size: 0.9em; }
blockquote { margin-left: 1.5em; color: #444; }
"""


@dataclass
class Capitulo:
    titulo: str
    cuerpo: list[str] = field(default_factory=list)


def _en_linea(texto: str) -> str:
    """Negrita, cursiva y código en línea, **después** de escapar: las únicas etiquetas que llegan
    vivas son las que se escriben aquí."""
    texto = html.escape(texto, quote=False)
    texto = texto.replace(r"\*", "\x00").replace(r"\|", "|").replace("\\\\", "\x01")
    texto = re.sub(r"`([^`]+)`", r"<code>\1</code>", texto)
    texto = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", texto)
    texto = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", texto)
    texto = re.sub(r"\*(.+?)\*", r"<em>\1</em>", texto)
    return texto.replace("\x00", "*").replace("\x01", "\\")


def _celdas(linea: str) -> list[str]:
    crudo = linea.strip()
    if crudo.startswith("|"):
        crudo = crudo[1:]
    if crudo.endswith("|") and not crudo.endswith("\\|"):
        crudo = crudo[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", crudo)]


def _texto_plano(texto: str) -> str:
    """El título sin marcas de Markdown, para el índice y los metadatos."""
    return re.sub(r"[*`]", "", texto).strip()


def _bloques(lineas: list[str]) -> list[tuple[str, int, str]]:
    """El Markdown, a una lista de bloques XHTML: `(tipo, nivel, xhtml)`.

    `tipo` es `titulo` (con su nivel) o `otro`. Lo demás se cierra al cambiar de clase de línea,
    como en `desde_markdown`.
    """
    bloques: list[tuple[str, int, str]] = []
    parrafo: list[str] = []
    lista: list[str] = []
    lista_numerada = False
    tabla: list[list[str]] = []
    codigo: list[str] = []
    en_codigo = False

    def cerrar_parrafo():
        if parrafo:
            bloques.append(("otro", 0, f"<p>{_en_linea(' '.join(parrafo))}</p>"))
            parrafo.clear()

    def cerrar_lista():
        if lista:
            etiqueta = "ol" if lista_numerada else "ul"
            items = "".join(f"<li>{_en_linea(x)}</li>" for x in lista)
            bloques.append(("otro", 0, f"<{etiqueta}>{items}</{etiqueta}>"))
            lista.clear()

    def cerrar_tabla():
        if tabla:
            cabeza, *filas = tabla
            th = "".join(f"<th>{_en_linea(c)}</th>" for c in cabeza)
            cuerpo = "".join(
                "<tr>" + "".join(f"<td>{_en_linea(c)}</td>" for c in fila) + "</tr>"
                for fila in filas
            )
            bloques.append(
                (
                    "otro",
                    0,
                    f"<table><thead><tr>{th}</tr></thead>"
                    + (f"<tbody>{cuerpo}</tbody>" if cuerpo else "")
                    + "</table>",
                )
            )
            tabla.clear()

    def cerrar_todo():
        cerrar_parrafo()
        cerrar_lista()
        cerrar_tabla()

    for linea in lineas:
        if _CERCA.match(linea):
            if en_codigo:
                texto = html.escape("\n".join(codigo), quote=False)
                bloques.append(("otro", 0, f"<pre><code>{texto}</code></pre>"))
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
        if _SEPARADOR_DE_TABLA.match(linea) and tabla:
            continue
        if re.search(r"(?<!\\)\|", linea):
            cerrar_parrafo()
            cerrar_lista()
            tabla.append(_celdas(linea))
            continue
        cerrar_tabla()
        if titulo := _TITULO.match(linea):
            cerrar_todo()
            nivel = len(titulo.group(1))
            bloques.append(("titulo", nivel, titulo.group(2)))
            continue
        if cita := _CITA.match(linea):
            cerrar_parrafo()
            cerrar_lista()
            bloques.append(
                ("otro", 0, f"<blockquote><p>{_en_linea(cita.group(1))}</p></blockquote>")
            )
            continue
        vineta = _VINETA.match(linea)
        numerada = _NUMERADA.match(linea)
        if vineta or numerada:
            cerrar_parrafo()
            if lista and lista_numerada != bool(numerada):
                cerrar_lista()
            lista_numerada = bool(numerada)
            lista.append((vineta or numerada).group(1))
            continue
        cerrar_lista()
        parrafo.append(linea.strip())

    if en_codigo and codigo:
        # Una cerca sin cerrar: se entrega lo que hay, perderlo sería peor.
        bloques.append(
            ("otro", 0, f"<pre><code>{html.escape(chr(10).join(codigo), quote=False)}</code></pre>")
        )
    cerrar_todo()
    return bloques


def capitulos(texto: str, titulo_del_libro: str) -> list[Capitulo]:
    """Parte el texto en capítulos por el nivel de título más alto que aparezca (1 o 2).

    Lo que hay antes del primer título va a un capítulo con el título del libro, para no
    perderlo.
    """
    bloques = _bloques(texto.splitlines())
    niveles = [n for tipo, n, _ in bloques if tipo == "titulo"]
    corte = 1 if 1 in niveles else (2 if 2 in niveles else 0)

    resultado: list[Capitulo] = []
    actual: Capitulo | None = None
    for tipo, nivel, contenido in bloques:
        if tipo == "titulo" and nivel == corte:
            actual = Capitulo(_texto_plano(contenido) or titulo_del_libro)
            resultado.append(actual)
            actual.cuerpo.append(f"<h1>{_en_linea(contenido)}</h1>")
            continue
        if actual is None:
            actual = Capitulo(titulo_del_libro)
            resultado.append(actual)
            actual.cuerpo.append(f"<h1>{html.escape(titulo_del_libro, quote=False)}</h1>")
        if tipo == "titulo":
            # Los niveles por debajo del corte suben uno: el capítulo es el h1.
            h = min(max(nivel - corte + 1, 2), 6) if corte else min(nivel, 6)
            actual.cuerpo.append(f"<h{h}>{_en_linea(contenido)}</h{h}>")
        else:
            actual.cuerpo.append(contenido)
    return [c for c in resultado if len(c.cuerpo) > 0]


def _xhtml(titulo: str, cuerpo: str, idioma: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
        f'xml:lang="{idioma}" lang="{idioma}">\n'
        f"<head><title>{html.escape(titulo)}</title>"
        '<link rel="stylesheet" type="text/css" href="estilo.css"/></head>\n'
        f"<body>\n{cuerpo}\n</body>\n</html>\n"
    )


def markdown_a_epub(
    texto: str,
    destino: Path,
    *,
    titulo: str,
    autor: str = "",
    idioma: str = "es",
    ahora: datetime | None = None,
    identificador: str | None = None,
) -> dict:
    """Escribe el EPUB en `destino` (atómico: `.parcial` y renombrado) y devuelve un resumen."""
    lineas = texto.splitlines()
    if len(lineas) > TOPE_LINEAS:
        raise ComposicionInvalida(
            f"El texto tiene {len(lineas)} líneas y el tope son {TOPE_LINEAS}: pártalo antes."
        )
    if not texto.strip():
        raise ComposicionInvalida("No hay texto con que hacer el libro.")
    titulo = (titulo or "").strip() or "Sin título"
    caps = capitulos(texto, titulo)
    if not caps:
        raise ComposicionInvalida("No hay texto con que hacer el libro.")

    momento = (ahora or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ident = identificador or f"urn:uuid:{uuid.uuid4()}"
    nombres = [f"cap{i:03d}.xhtml" for i in range(1, len(caps) + 1)]

    manifiesto = "\n".join(
        f'    <item id="c{i}" href="{n}" media-type="application/xhtml+xml"/>'
        for i, n in enumerate(nombres, start=1)
    )
    columna = "\n".join(f'    <itemref idref="c{i}"/>' for i in range(1, len(caps) + 1))
    creador = f"    <dc:creator>{html.escape(autor)}</dc:creator>\n" if autor.strip() else ""
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id" '
        f'xml:lang="{idioma}">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="id">{html.escape(ident)}</dc:identifier>\n'
        f"    <dc:title>{html.escape(titulo)}</dc:title>\n"
        f"{creador}"
        f"    <dc:language>{idioma}</dc:language>\n"
        f'    <meta property="dcterms:modified">{momento}</meta>\n'
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
        'properties="nav"/>\n'
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>\n'
        '    <item id="css" href="estilo.css" media-type="text/css"/>\n'
        f"{manifiesto}\n"
        "  </manifest>\n"
        f'  <spine toc="ncx">\n{columna}\n  </spine>\n'
        "</package>\n"
    )
    enlaces = "\n".join(
        f'      <li><a href="{n}">{html.escape(c.titulo)}</a></li>'
        for n, c in zip(nombres, caps, strict=True)
    )
    nav = _xhtml(
        titulo,
        f'<nav epub:type="toc" id="toc"><h1>Índice</h1>\n    <ol>\n{enlaces}\n    </ol>\n</nav>',
        idioma,
    )
    puntos = "\n".join(
        f'    <navPoint id="p{i}" playOrder="{i}"><navLabel><text>{html.escape(c.titulo)}</text>'
        f'</navLabel><content src="{n}"/></navPoint>'
        for i, (n, c) in enumerate(zip(nombres, caps, strict=True), start=1)
    )
    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        f'  <head><meta name="dtb:uid" content="{html.escape(ident)}"/></head>\n'
        f"  <docTitle><text>{html.escape(titulo)}</text></docTitle>\n"
        f"  <navMap>\n{puntos}\n  </navMap>\n</ncx>\n"
    )
    contenedor = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '  <rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles>\n</container>\n'
    )

    destino = Path(destino)
    parcial = destino.with_name(destino.name + ".parcial")
    try:
        with zipfile.ZipFile(parcial, "w") as z:
            # **El primero y sin comprimir**: así lo reconocen los lectores por sus bytes.
            z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", zipfile.ZIP_STORED)
            z.writestr("META-INF/container.xml", contenedor, zipfile.ZIP_DEFLATED)
            z.writestr("OEBPS/content.opf", opf, zipfile.ZIP_DEFLATED)
            z.writestr("OEBPS/nav.xhtml", nav, zipfile.ZIP_DEFLATED)
            z.writestr("OEBPS/toc.ncx", ncx, zipfile.ZIP_DEFLATED)
            z.writestr("OEBPS/estilo.css", ESTILO, zipfile.ZIP_DEFLATED)
            for nombre, cap in zip(nombres, caps, strict=True):
                z.writestr(
                    f"OEBPS/{nombre}",
                    _xhtml(cap.titulo, "\n".join(cap.cuerpo), idioma),
                    zipfile.ZIP_DEFLATED,
                )
        parcial.replace(destino)
    except Exception:
        parcial.unlink(missing_ok=True)
        raise
    return {"capitulos": len(caps), "titulos": [c.titulo for c in caps]}
