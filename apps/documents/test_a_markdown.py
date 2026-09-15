"""Sacar el contenido a Markdown, y el camino de vuelta.

Lo que estas pruebas fijan no es «convierte»: es **lo que hace la conversión fiable de leer**.
Una tabla con una barra sin escapar se descuadra entera a partir de esa fila; un PDF escaneado
entrega cero bytes con pinta de haber funcionado; un EPUB leído en el orden del ZIP devuelve
los capítulos barajados. Las tres cosas «convierten» sin dar error.
"""

from __future__ import annotations

import zipfile

import pytest

from .a_markdown import (
    SinTextoQueSacar,
    a_markdown,
    de_csv,
    de_epub,
    de_excel,
    de_html,
    de_pdf,
    de_word,
)
from .composicion import ComposicionInvalida
from .desde_markdown import markdown_a_pdf

CONTENEDOR = (
    '<?xml version="1.0"?><container '
    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>'
)


def _opf(lomo: str) -> str:
    return (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:title>Manual de vuelo</dc:title></metadata>"
        '<manifest><item id="c1" href="cap1.xhtml"/>'
        '<item id="c2" href="cap2.xhtml"/></manifest>'
        f"<spine>{lomo}</spine></package>"
    )


@pytest.fixture
def libro(tmp_path):
    """Un EPUB cuyo **lomo va al revés que el ZIP**. Es el caso que importa."""
    ruta = tmp_path / "libro.epub"
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("META-INF/container.xml", CONTENEDOR)
        z.writestr("OEBPS/content.opf", _opf('<itemref idref="c2"/><itemref idref="c1"/>'))
        z.writestr("OEBPS/cap1.xhtml", "<html><body><h2>Segundo en el ZIP</h2></body></html>")
        z.writestr("OEBPS/cap2.xhtml", "<html><body><h2>Primero en el lomo</h2></body></html>")
    return ruta


@pytest.fixture
def hoja(tmp_path):
    import openpyxl

    libro = openpyxl.Workbook()
    h = libro.active
    h.title = "Coordenadas"
    h.append(["Punto", "Norte"])
    h.append(["Tramo A | B", 6234567.12])
    libro.create_sheet("Vacia")
    ruta = tmp_path / "medicion.xlsx"
    libro.save(ruta)
    return ruta


def _pdf_con(tmp_path, texto: str | None):
    from reportlab.pdfgen import canvas

    ruta = tmp_path / ("acta.pdf" if texto else "escaneo.pdf")
    lienzo = canvas.Canvas(str(ruta))
    if texto:
        lienzo.drawString(72, 720, texto)
    lienzo.showPage()
    lienzo.save()
    return ruta


class TestLaTabla:
    """Lo que separa una tabla legible de una descuadrada."""

    def test_la_barra_se_escapa(self, hoja):
        """**Es el separador de columnas.** Una celda que la contenga —«Ancho | Alto», una
        ruta escrita a mano— parte la fila en dos y descuadra la tabla a partir de ahí."""
        salida = de_excel(hoja)
        assert r"Tramo A \| B" in salida
        # Y la fila sigue teniendo dos columnas, no tres.
        fila = next(ln for ln in salida.splitlines() if "Tramo A" in ln)
        assert fila.count("|") - fila.count(r"\|") == 3  # los dos bordes y el separador

    def test_lleva_la_fila_de_guiones(self, hoja):
        """Sin ella no es una tabla: es un párrafo lleno de barras."""
        assert "| --- |" in de_excel(hoja)

    def test_las_filas_desiguales_se_rellenan(self, tmp_path):
        import openpyxl

        libro = openpyxl.Workbook()
        h = libro.active
        h.append(["A", "B", "C"])
        h.append(["solo una"])
        ruta = tmp_path / "desigual.xlsx"
        libro.save(ruta)

        filas = [ln for ln in de_excel(ruta).splitlines() if ln.startswith("|")]
        anchos = {ln.count("|") for ln in filas}
        assert len(anchos) == 1, f"Filas de anchos distintos: {filas}"


class TestExcel:
    def test_una_seccion_por_hoja(self, hoja):
        salida = de_excel(hoja)
        assert "## Coordenadas" in salida
        assert "## Vacia" in salida

    def test_una_hoja_vacia_se_nombra_igual(self, hoja):
        """Que el libro traiga una hoja vacía es información. Borrarla del resultado hace
        pensar que se perdió por el camino."""
        assert "*(hoja vacía)*" in de_excel(hoja)

    def test_sin_cache_de_formulas_se_dice(self, tmp_path):
        """**El fallo silencioso de `data_only=True`.**

        Un libro generado por un programa y nunca abierto con Excel no tiene guardado el
        resultado de sus fórmulas, así que todas las celdas salen vacías. Sin esta
        comprobación, la entrega sería una tabla perfecta llena de huecos y sin una sola
        pista de por qué.
        """
        import openpyxl

        libro = openpyxl.Workbook()
        libro.active["A1"] = "=SUMA(B1:B9)"
        ruta = tmp_path / "sin_cache.xlsx"
        libro.save(ruta)

        with pytest.raises(SinTextoQueSacar) as fallo:
            de_excel(ruta)
        assert "fórmulas" in str(fallo.value)
        assert "Excel" in str(fallo.value), "Hay que decir cómo arreglarlo."


class TestCsv:
    def test_el_punto_y_coma_del_excel_en_espanol(self, tmp_path):
        """Dar por hecho la coma convierte la mitad de los archivos de esta oficina en una
        sola columna con todo dentro — y como la coma es el separador decimal, además parte
        los números."""
        ruta = tmp_path / "puntos.csv"
        ruta.write_text("Punto;Norte\nP1;6234567,12\n", encoding="utf-8")
        salida = de_csv(ruta)
        assert "| Punto | Norte |" in salida
        assert "6234567,12" in salida

    def test_y_la_coma_cuando_es_coma(self, tmp_path):
        ruta = tmp_path / "otro.csv"
        ruta.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
        assert "| a | b | c |" in de_csv(ruta)

    def test_la_marca_de_orden_de_windows_no_ensucia_el_encabezado(self, tmp_path):
        """Leída como utf-8 a secas, la primera columna sale con tres caracteres invisibles
        delante que nadie ve hasta que una búsqueda no encuentra la columna."""
        ruta = tmp_path / "bom.csv"
        ruta.write_text("Punto;Norte\nP1;1\n", encoding="utf-8-sig")
        assert de_csv(ruta).splitlines()[2].startswith("| Punto |")

    def test_uno_vacio_se_queja(self, tmp_path):
        ruta = tmp_path / "nada.csv"
        ruta.write_text("\n\n", encoding="utf-8")
        with pytest.raises(SinTextoQueSacar):
            de_csv(ruta)


class TestWord:
    @pytest.fixture
    def informe(self, tmp_path):
        import docx

        doc = docx.Document()
        doc.add_heading("Informe de terreno", level=1)
        doc.add_paragraph("Levantamiento del 3 de marzo.")
        parrafo = doc.add_paragraph()
        parrafo.add_run("Importante: ").bold = True
        parrafo.add_run("revisar la cota.")
        doc.add_paragraph("Primer punto", style="List Bullet")
        tabla = doc.add_table(rows=1, cols=2)
        tabla.cell(0, 0).text = "Punto"
        tabla.cell(0, 1).text = "Cota"
        ruta = tmp_path / "informe.docx"
        doc.save(ruta)
        return ruta

    def test_los_titulos_por_nivel(self, informe):
        assert "# Informe de terreno" in de_word(informe)

    def test_la_negrita_no_se_lleva_el_espacio_dentro(self, informe):
        """**`**Importante: **revisar` no es negrita en CommonMark**: la norma exige que el
        cierre no venga precedido de un espacio, así que lo que se ve son cuatro asteriscos
        literales en mitad de la frase. Y Word guarda muchísimo «Importante: » así.
        """
        salida = de_word(informe)
        assert "**Importante:** revisar" in salida
        assert "**Importante: **" not in salida

    def test_hay_renglon_en_blanco_antes_de_una_lista(self, informe):
        """Markdown separa bloques por líneas vacías, y Word no las guarda porque para él la
        separación es el estilo. Una lista pegada al párrafo anterior se pinta como parte del
        párrafo en casi todos los visores."""
        lineas = de_word(informe).splitlines()
        i = next(n for n, ln in enumerate(lineas) if ln.startswith("- "))
        assert lineas[i - 1] == ""

    def test_la_tabla_sale_en_su_sitio_y_no_al_final(self, informe):
        """`python-docx` ofrece los párrafos y las tablas por separado, y usarlos así entrega
        todas las tablas al final, fuera del apartado al que pertenecen."""
        salida = de_word(informe)
        assert salida.index("Primer punto") < salida.index("| Punto | Cota |")

    def test_los_asteriscos_del_texto_se_escapan(self, tmp_path):
        """Un «3 * 4» dentro de una frase se comería el resto de la línea."""
        import docx

        doc = docx.Document()
        doc.add_paragraph("La cota 3 " + chr(42) + " 4 metros.")
        ruta = tmp_path / "conasterisco.docx"
        doc.save(ruta)
        assert r"3 \* 4" in de_word(ruta)


class TestPdf:
    def test_saca_el_texto_que_tiene(self, tmp_path):
        assert "Acta de entrega" in de_pdf(_pdf_con(tmp_path, "Acta de entrega"))

    def test_un_escaneo_lo_dice_y_no_entrega_un_archivo_vacio(self, tmp_path):
        """**La regla que gobierna el módulo entero.** `pypdf` devuelve cadenas vacías sin
        quejarse, y escribir ese `.md` de cero bytes sería la peor respuesta posible porque
        parece que funcionó."""
        with pytest.raises(SinTextoQueSacar) as fallo:
            de_pdf(_pdf_con(tmp_path, None))
        assert "escaneo" in str(fallo.value)

    def test_y_no_deja_el_md_escrito(self, tmp_path):
        ruta = _pdf_con(tmp_path, None)
        with pytest.raises(SinTextoQueSacar):
            a_markdown(ruta)
        assert not ruta.with_suffix(".md").exists()


class TestEpub:
    def test_los_capitulos_en_el_orden_del_lomo(self, libro):
        """Los archivos están dentro del ZIP como al empaquetador le vino bien. Leerlos en ese
        orden entrega los capítulos barajados, y la conversión «funciona» igual."""
        salida = de_epub(libro)
        assert salida.index("Primero en el lomo") < salida.index("Segundo en el ZIP")

    def test_usa_el_titulo_del_libro(self, libro):
        assert de_epub(libro).startswith("# Manual de vuelo")

    def test_un_capitulo_que_falta_no_tumba_el_resto(self, tmp_path):
        """El índice lo nombra y el ZIP no lo trae. El libro sigue sirviendo."""
        ruta = tmp_path / "roto.epub"
        with zipfile.ZipFile(ruta, "w") as z:
            z.writestr("META-INF/container.xml", CONTENEDOR)
            z.writestr("OEBPS/content.opf", _opf('<itemref idref="c1"/><itemref idref="c2"/>'))
            z.writestr("OEBPS/cap1.xhtml", "<html><body><p>El que sí está.</p></body></html>")
        assert "El que sí está" in de_epub(ruta)

    def test_algo_que_no_es_un_epub(self, tmp_path):
        ruta = tmp_path / "falso.epub"
        ruta.write_bytes(b"esto no es un zip")
        with pytest.raises(ComposicionInvalida):
            de_epub(ruta)


class TestHtml:
    def test_los_titulos_salen_con_almohadilla(self):
        """Y no subrayados con guiones, que es la otra forma y no vale del nivel tres en
        adelante."""
        assert de_html("<h2>Resultados</h2>").startswith("## Resultados")

    def test_no_deja_bloques_de_lineas_vacias(self):
        salida = de_html("<p>uno</p>\n\n\n\n<p>dos</p>")
        assert "\n\n\n" not in salida


class TestLaPuerta:
    def test_escribe_el_md_al_lado(self, hoja):
        assert a_markdown(hoja) == hoja.with_suffix(".md")
        assert hoja.with_suffix(".md").read_text(encoding="utf-8").startswith("# medicion")

    def test_no_deja_el_parcial(self, hoja):
        a_markdown(hoja)
        assert not list(hoja.parent.glob("*.parcial"))

    def test_un_formato_que_no_sabe_lo_dice_con_los_que_si(self, tmp_path):
        ruta = tmp_path / "plano.dwg"
        ruta.write_bytes(b"x")
        with pytest.raises(ComposicionInvalida) as fallo:
            a_markdown(ruta)
        assert ".xlsx" in str(fallo.value), "Hay que decir con cuáles sí."


class TestVolverAPdf:
    @pytest.fixture
    def documento(self, tmp_path):
        ruta = tmp_path / "entrega.md"
        ruta.write_text(
            "# Entrega de obra\n\n"
            "Texto con **negrita** y `codigo`.\n\n"
            "- Primero\n- Segundo\n\n"
            "> Una cita.\n\n"
            "| Punto | Cota |\n| --- | --- |\n| P1 | 1250,5 |\n\n"
            "Con <etiqueta> y & ampersand.\n",
            encoding="utf-8",
        )
        return ruta

    def _texto(self, pdf) -> str:
        from pypdf import PdfReader

        return "\n".join((p.extract_text() or "") for p in PdfReader(str(pdf)).pages)

    @pytest.mark.parametrize(
        "aguja", ["Entrega de obra", "negrita", "Primero", "Una cita", "1250,5", "ampersand"]
    )
    def test_todo_llega_al_papel(self, documento, aguja):
        assert aguja in self._texto(markdown_a_pdf(documento))

    def test_la_fila_de_guiones_no_se_imprime(self, documento):
        """Es la que declara la tabla en Markdown. Pintarla mete una banda de rayas debajo
        del encabezado."""
        assert "---" not in self._texto(markdown_a_pdf(documento))

    def test_el_html_incrustado_sale_como_texto(self, documento):
        """Este módulo no interpreta HTML, y lo dice en pantalla. Lo que no puede hacer es
        tragárselo en silencio, que es lo que haría un analizador incompleto."""
        assert "<etiqueta>" in self._texto(markdown_a_pdf(documento))

    def test_uno_vacio_se_queja_en_vez_de_escribir_un_pdf_en_blanco(self, tmp_path):
        ruta = tmp_path / "vacio.md"
        ruta.write_text("   \n\n", encoding="utf-8")
        with pytest.raises(ComposicionInvalida):
            markdown_a_pdf(ruta)
        assert not ruta.with_suffix(".pdf").exists()

    def test_ida_y_vuelta(self, hoja):
        """Excel → Markdown → PDF, con la tabla llegando entera al otro lado."""
        pdf = markdown_a_pdf(a_markdown(hoja))
        assert "Tramo A | B" in self._texto(pdf), "La barra escapada tiene que volver a ser barra."
