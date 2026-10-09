"""Caracterización de `desde_markdown.markdown_a_pdf` (F11.8, etapa 3), antes de partirla.

`markdown_a_pdf` mide ~145 líneas: lee y valida el Markdown, recorre las líneas armando piezas de
reportlab con un puñado de cierres anidados, y escribe el PDF de forma atómica. Aquí se fija,
para un Markdown de cada forma, el **texto** que sale en el PDF (pypdf, que no lo escribió), el
número de páginas y los errores con su mensaje. El refactor no puede cambiar nada de eso.
"""

from __future__ import annotations

import io
from pathlib import Path

import pypdf
import pytest

from . import desde_markdown
from .composicion import ComposicionInvalida
from .desde_markdown import markdown_a_pdf

TABLA = (
    "| Punto | Este | Norte |\n|---|---|---|\n"
    "| P1 | 495279.4 | 7318729.0 |\n| P2 | 495137.1 | 7318700.3 |\n"
)

#: nombre del caso -> contenido del `.md`.
CASOS: dict[str, str] = {
    "titulos": "# Uno\n\n## Dos\n\n### Tres\n\n#### Cuatro\n\n##### Cinco\n\n###### Seis\n",
    "parrafo-multilinea": "primera línea\nsegunda línea\ntercera\n\nOtro párrafo.\n",
    "vinetas": "- uno\n- dos\n* tres\n+ cuatro\n",
    "numerada": "1. uno\n2) dos\n3. tres\n",
    "vinetas-y-parrafo": "Intro\n- a\n- b\nCierre\n",
    "tabla": TABLA,
    "tabla-con-barra-escapada": "| a | b |\n|---|---|\n| x \\| y | z |\n",
    "tabla-sin-barras-laterales": "a | b\n--|--\n1 | 2\n",
    "tabla-seguida-de-parrafo": TABLA + "Texto después.\n",
    "cita": "> una cita\n> otra línea\n\nTexto.\n",
    "codigo": "Antes\n\n```\nx = 1 < 2 & 3\nprint(x)\n```\n\nDespués\n",
    "codigo-con-tildes": "~~~\nlinea a\n~~~\n",
    "codigo-sin-cerrar": "```\nsin cerrar\nsigue\n",
    "formato-en-linea": "Una **negrita**, una *cursiva*, `código` y ***ambas***.\n",
    "html-escapado": "Texto con <b>etiqueta</b> y & ampersand.\n",
    "escapes-de-markdown": "Un \\*asterisco\\* literal y una barra \\\\ doble.\n",
    "mezcla": "# Informe\n\nIntro con **fuerza**.\n\n- a\n- b\n\n"
    + TABLA
    + "\n> nota\n\n```\ncódigo\n```\n",
    "separador-sin-tabla": "---\n",
    "linea-de-pipes-sola": "|\n",
    "muchas-paginas": "\n\n".join(f"Párrafo número {n}. " + "texto " * 40 for n in range(120)),
}


def _escribir(tmp_path: Path, caso: str) -> Path:
    ruta = tmp_path / "doc.md"
    ruta.write_text(CASOS[caso], encoding="utf-8")
    return ruta


def _texto(pdf: Path) -> tuple[int, str]:
    lector = pypdf.PdfReader(str(pdf))
    return len(lector.pages), "\n".join(p.extract_text() or "" for p in lector.pages)


def _calcular(tmp_path: Path, caso: str) -> dict:
    ruta = _escribir(tmp_path, caso)
    pdf = markdown_a_pdf(ruta)
    paginas, texto = _texto(pdf)
    return {
        "destino": pdf.name,
        "paginas": paginas,
        "texto": texto if paginas < 3 else texto[:400] + " [...] " + texto[-200:],
        "sobran": sorted(p.name for p in tmp_path.iterdir() if p.name not in ("doc.md", "doc.pdf")),
    }


#: Lo que sale **hoy** para cada caso (generado con el código sin tocar y revisado a ojo).
ESPERADO: dict[str, dict] = {
    "cita": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "una cita\notra línea\nTexto.\n",
    },
    "codigo": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "Antes\n x = 1 < 2 & 3 print(x)\nDespués\n",
    },
    "codigo-con-tildes": {"destino": "doc.pdf", "paginas": 1, "sobran": [], "texto": "linea a\n"},
    "codigo-sin-cerrar": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "sin cerrar sigue\n",
    },
    "escapes-de-markdown": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "Un *asterisco* literal y una barra \\ doble.\n",
    },
    "formato-en-linea": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "Una negrita, una cursiva, código y ambas.\n",
    },
    "html-escapado": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "Texto con <b>etiqueta</b> y & ampersand.\n",
    },
    "linea-de-pipes-sola": {"destino": "doc.pdf", "paginas": 1, "sobran": [], "texto": ""},
    "mezcla": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "Informe\n"
        "Intro con fuerza.\n"
        "\x7f\n"
        "a\n"
        "\x7f\n"
        "b\n"
        "Punto\n"
        "Este\n"
        "Norte\n"
        "P1\n"
        "495279.4\n"
        "7318729.0\n"
        "P2\n"
        "495137.1\n"
        "7318700.3\n"
        "nota\n"
        "código\n",
    },
    "muchas-paginas": {
        "destino": "doc.pdf",
        "paginas": 8,
        "sobran": [],
        "texto": "Párrafo número 0. texto texto texto texto texto texto texto "
        "texto texto texto texto texto texto texto texto texto\n"
        "texto texto texto texto texto texto texto texto texto texto "
        "texto texto texto texto texto texto texto texto texto\n"
        "texto texto texto texto texto\n"
        "Párrafo número 1. texto texto texto texto texto texto texto "
        "texto texto texto texto texto texto texto texto texto\n"
        "texto texto texto texto text [...] o texto texto texto texto "
        "texto texto texto texto\n"
        "texto texto texto texto texto texto texto texto texto texto "
        "texto texto texto texto texto texto texto texto texto\n"
        "texto texto texto texto texto texto\n",
    },
    "numerada": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "\x7f\nuno\n\x7f\ndos\n\x7f\ntres\n",
    },
    "parrafo-multilinea": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "primera línea segunda línea tercera\nOtro párrafo.\n",
    },
    "separador-sin-tabla": {"destino": "doc.pdf", "paginas": 1, "sobran": [], "texto": "---\n"},
    "tabla": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "Punto\nEste\nNorte\nP1\n495279.4\n7318729.0\nP2\n495137.1\n7318700.3\n",
    },
    "tabla-con-barra-escapada": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "a\nb\nx | y\nz\n",
    },
    "tabla-seguida-de-parrafo": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "Punto\n"
        "Este\n"
        "Norte\n"
        "P1\n"
        "495279.4\n"
        "7318729.0\n"
        "P2\n"
        "495137.1\n"
        "7318700.3\n"
        "Texto después.\n",
    },
    "tabla-sin-barras-laterales": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "a\nb\n1\n2\n",
    },
    "titulos": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "Uno\nDos\nTres\nCuatro\nCinco\nSeis\n",
    },
    "vinetas": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "\x7f\nuno\n\x7f\ndos\n\x7f\ntres\n\x7f\ncuatro\n",
    },
    "vinetas-y-parrafo": {
        "destino": "doc.pdf",
        "paginas": 1,
        "sobran": [],
        "texto": "Intro\n\x7f\na\n\x7f\nb\nCierre\n",
    },
}


@pytest.mark.parametrize("caso", sorted(CASOS))
def test_lo_que_sale_hoy(tmp_path, caso):
    assert _calcular(tmp_path, caso) == ESPERADO[caso]


class TestLosCaminosDeFallo:
    def test_un_archivo_vacio(self, tmp_path):
        ruta = tmp_path / "vacio.md"
        ruta.write_text("  \n\n  ", encoding="utf-8")
        with pytest.raises(ComposicionInvalida) as fallo:
            markdown_a_pdf(ruta)
        assert str(fallo.value) == "vacio.md está vacío."
        assert not list(tmp_path.glob("*.pdf*"))

    def test_demasiadas_lineas(self, tmp_path, monkeypatch):
        monkeypatch.setattr(desde_markdown, "TOPE_LINEAS", 3)
        ruta = tmp_path / "largo.md"
        ruta.write_text("a\nb\nc\nd\n", encoding="utf-8")
        with pytest.raises(ComposicionInvalida) as fallo:
            markdown_a_pdf(ruta)
        assert str(fallo.value) == (
            "largo.md tiene 4 líneas y el tope son 3. Eso ya no es un documento: pártalo antes."
        )

    def test_no_se_puede_leer(self, tmp_path):
        with pytest.raises(ComposicionInvalida) as fallo:
            markdown_a_pdf(tmp_path / "no_existe.md")
        assert str(fallo.value).startswith("No se pudo leer no_existe.md: ")

    def test_un_archivo_en_latin1_se_lee(self, tmp_path):
        ruta = tmp_path / "viejo.md"
        ruta.write_bytes("Año nuevo\n".encode("latin-1"))
        paginas, texto = _texto(markdown_a_pdf(ruta))
        assert (paginas, texto.strip()) == (1, "Año nuevo")

    def test_el_destino_explicito_manda_y_no_queda_parcial(self, tmp_path):
        ruta = _escribir(tmp_path, "titulos")
        destino = tmp_path / "otra" / "salida.pdf"
        destino.parent.mkdir()
        resultado = markdown_a_pdf(ruta, destino=destino)
        assert resultado == destino
        assert sorted(p.name for p in destino.parent.iterdir()) == ["salida.pdf"]
        assert not (tmp_path / "doc.pdf").exists()

    def test_el_destino_puede_ser_un_texto(self, tmp_path):
        ruta = _escribir(tmp_path, "titulos")
        destino = tmp_path / "t.pdf"
        assert markdown_a_pdf(str(ruta), destino=str(destino)) == destino

    def test_un_fallo_al_componer_borra_el_parcial_y_lo_dice(self, tmp_path, monkeypatch):
        from reportlab.platypus import SimpleDocTemplate

        def revienta(self, flowables, *a, **k):
            Path(self.filename).write_bytes(b"%PDF a medias")
            raise RuntimeError("se rompió reportlab")

        monkeypatch.setattr(SimpleDocTemplate, "build", revienta)
        ruta = _escribir(tmp_path, "titulos")
        with pytest.raises(ComposicionInvalida) as fallo:
            markdown_a_pdf(ruta)
        assert str(fallo.value) == "No se pudo componer el PDF: se rompió reportlab"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["doc.md"]

    def test_el_pdf_se_escribe_en_un_parcial_y_se_renombra(self, tmp_path, monkeypatch):
        vistos = []
        reales = Path.replace

        def espia(self, destino):
            vistos.append((self.name, Path(destino).name, self.exists()))
            return reales(self, destino)

        monkeypatch.setattr(Path, "replace", espia)
        markdown_a_pdf(_escribir(tmp_path, "titulos"))
        assert vistos == [("doc.pdf.parcial", "doc.pdf", True)]

    def test_un_pdf_de_entrada_se_lee_como_texto_y_no_levanta_por_eso(self, tmp_path):
        """La pantalla lo rechaza antes (`apps/core/test_auditoria.py`); aquí solo se fija que la
        función, por sí sola, no se opone."""
        ruta = tmp_path / "falso.md"
        ruta.write_bytes(b"%PDF-1.4\nnada\n")
        paginas, _ = _texto(markdown_a_pdf(ruta))
        assert paginas == 1


def test_la_salida_es_un_pdf_legible(tmp_path):
    ruta = _escribir(tmp_path, "mezcla")
    datos = markdown_a_pdf(ruta).read_bytes()
    assert datos.startswith(b"%PDF")
    assert len(pypdf.PdfReader(io.BytesIO(datos)).pages) == 1


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Defecto hallado al caracterizar (F11.8): los bloques de código se imprimen con "
        "`Paragraph`, que colapsa los saltos de línea, así que un bloque de varias líneas sale "
        "como una sola («x = 1 < 2 & 3 print(x)»). Hace falta `Preformatted` o `<br/>`. No se "
        "arregla en el refactor."
    ),
)
def test_un_bloque_de_codigo_conserva_sus_lineas(tmp_path):
    ruta = _escribir(tmp_path, "codigo")
    _, texto = _texto(markdown_a_pdf(ruta))
    assert "x = 1 < 2 & 3\nprint(x)" in texto
