"""El lector de PDF y la desambiguación de firmas compartidas.

Las cifras del plano A1 son de un archivo real de la oficina: caja de 594 × 841 mm —
vertical— con `/Rotate` en 270, que en el papel es una lámina **apaisada** de 841 × 594.
Mirar solo la caja haría que la aplicación llamara «vertical» a una lámina que todo el
mundo ve tumbada, y en una herramienta cuyo trabajo es poner unas hojas verticales y otras
apaisadas eso sería peor que no decir nada.
"""

import pytest

from apps.formats import catalogo, pdf
from apps.formats.deteccion import inspeccionar, por_firma


def _pdf(tmp_path, paginas, nombre="documento.pdf"):
    """Un PDF de verdad, escrito con pypdf. `paginas` son pares (ancho_mm, alto_mm, giro)."""
    from pypdf import PdfWriter

    escritor = PdfWriter()
    for ancho_mm, alto_mm, giro in paginas:
        pagina = escritor.add_blank_page(
            width=ancho_mm / pdf.MM_POR_PUNTO, height=alto_mm / pdf.MM_POR_PUNTO
        )
        if giro:
            pagina.rotate(giro)
    ruta = tmp_path / nombre
    with open(ruta, "wb") as salida:
        escritor.write(salida)
    return ruta


class TestElGiroDecideLaOrientacion:
    def test_una_lamina_a1_con_giro_270_es_apaisada(self, tmp_path):
        """El caso real: caja vertical, giro 270, y en el papel se ve tumbada."""
        leido = pdf.leer_cabecera(_pdf(tmp_path, [(594, 841, 270)]))
        pagina = leido.paginas[0]

        assert pagina.apaisada is True
        assert pagina.formato == "A1"
        assert pagina.etiqueta == "A1 apaisada"

    def test_y_el_tamano_que_se_enseña_es_el_que_se_ve(self, tmp_path):
        leido = pdf.leer_cabecera(_pdf(tmp_path, [(594, 841, 270)]))
        assert leido.paginas[0].ancho_mm == pytest.approx(841, abs=1)
        assert leido.paginas[0].alto_mm == pytest.approx(594, abs=1)

    def test_sin_giro_la_misma_caja_es_vertical(self, tmp_path):
        leido = pdf.leer_cabecera(_pdf(tmp_path, [(594, 841, 0)]))
        assert leido.paginas[0].etiqueta == "A1 vertical"

    def test_un_giro_de_180_no_cambia_la_orientacion(self, tmp_path):
        leido = pdf.leer_cabecera(_pdf(tmp_path, [(594, 841, 180)]))
        assert leido.paginas[0].apaisada is False


class TestLoQueSeLee:
    def test_cuenta_las_paginas(self, tmp_path):
        leido = pdf.leer_cabecera(_pdf(tmp_path, [(210, 297, 0)] * 5))
        assert leido.cuantas == 5

    def test_reconoce_los_tamanos_normalizados(self, tmp_path):
        leido = pdf.leer_cabecera(_pdf(tmp_path, [(210, 297, 0), (297, 420, 0)]))
        assert [p.formato for p in leido.paginas] == ["A4", "A3"]

    def test_un_tamano_raro_se_dice_en_milimetros(self, tmp_path):
        """Inventarle un nombre a una hoja de 500 × 700 sería peor que dar la medida."""
        leido = pdf.leer_cabecera(_pdf(tmp_path, [(500, 700, 0)]))
        assert leido.paginas[0].formato == "500 × 700 mm"

    def test_detecta_que_se_mezclan_orientaciones(self, tmp_path):
        """Es el caso que obliga a mirar la lista antes de unir."""
        leido = pdf.leer_cabecera(_pdf(tmp_path, [(210, 297, 0), (420, 297, 0)]))
        assert leido.mezcla_orientaciones is True
        assert leido.resumen == "2 página(s) · tamaños mezclados"

    def test_con_todo_igual_el_resumen_lo_dice(self, tmp_path):
        leido = pdf.leer_cabecera(_pdf(tmp_path, [(210, 297, 0)] * 3))
        assert leido.resumen == "3 página(s) · A4 vertical"

    def test_un_archivo_que_no_es_pdf(self, tmp_path):
        roto = tmp_path / "x.pdf"
        roto.write_bytes(b"%PDF-1.7\nesto no es un pdf\n")
        with pytest.raises(pdf.NoEsPdf):
            pdf.leer_cabecera(roto)


class TestFirmasCompartidas:
    """Varios formatos empiezan por los mismos bytes, y hasta ahora ganaba el primero.

    Un GeoPackage vectorial se reconocía como `gpkg_raster` —familia equivocada, veredictos
    equivocados, destinos equivocados— y le pasaba a los GeoPackage que produce esta misma
    aplicación. Cuando la firma empata, decide la extensión.
    """

    def test_un_zip_llamado_docx_no_es_un_kmz(self):
        assert por_firma(b"PK\x03\x04" + b"x" * 40, "informe.docx") == "docx"

    def test_y_uno_llamado_kmz_si(self):
        assert por_firma(b"PK\x03\x04" + b"x" * 40, "recinto.kmz") == "kmz"

    def test_una_base_sqlite_llamada_mbtiles_no_es_un_geopackage(self):
        assert por_firma(b"SQLite format 3\x00" + b"x" * 40, "teselas.mbtiles") == "mbtiles"

    def test_sin_nombre_se_elige_igual_que_antes(self):
        """No saber la extensión no puede dejar el archivo sin reconocer."""
        assert por_firma(b"PK\x03\x04" + b"x" * 40) is not None

    def test_el_tiff_sigue_decidiendose_por_su_byte_de_version(self):
        """BigTIFF y TIFF clásico comparten extensión y se separan en un solo byte. Ese
        camino es anterior y no lo puede pisar la desambiguación por nombre."""
        assert por_firma(b"II+\x00" + b"x" * 40, "orto.tif") == "bigtiff"
        assert por_firma(b"II*\x00" + b"x" * 40, "orto.tif") == "geotiff"


class TestUnPdfEnLaInspeccion:
    def test_se_reconoce_por_su_firma(self, tmp_path):
        inspeccion = inspeccionar(_pdf(tmp_path, [(210, 297, 0)]))
        assert inspeccion.codigo_formato == "pdf"
        assert inspeccion.familia == catalogo.DOCUMENTO

    def test_la_ficha_dice_cuantas_paginas(self, tmp_path):
        inspeccion = inspeccionar(_pdf(tmp_path, [(210, 297, 0)] * 4))
        assert inspeccion.pdf.cuantas == 4
        assert any("4 página(s)" in aviso for aviso in inspeccion.avisos)

    def test_avisa_cuando_mezcla_orientaciones(self, tmp_path):
        inspeccion = inspeccionar(_pdf(tmp_path, [(210, 297, 0), (420, 297, 0)]))
        assert any("verticales y apaisadas" in aviso for aviso in inspeccion.avisos)

    def test_ningun_perfil_geoespacial_opina_de_un_pdf(self, tmp_path):
        """Seis «no abre» delante de un PDF son una respuesta correcta a una pregunta que
        nadie hizo: un PDF abre en todas partes."""
        from apps.targets import perfiles

        inspeccion = inspeccionar(_pdf(tmp_path, [(210, 297, 0)]))
        assert perfiles.veredictos(inspeccion) == ()
