"""Partir un PDF y armar uno con imágenes.

Lo que más se prueba aquí son los rangos, porque es donde alguien escribe a mano y donde un
fallo silencioso reparte media entrega por la carpeta con nombres que parecen correctos.
"""

import pytest

from apps.documents import dividir
from apps.documents.composicion import ComposicionInvalida
from apps.formats import pdf as lector


def _pdf(carpeta, nombre, cuantas):
    from pypdf import PdfWriter

    escritor = PdfWriter()
    for _ in range(cuantas):
        escritor.add_blank_page(width=210 / lector.MM_POR_PUNTO, height=297 / lector.MM_POR_PUNTO)
    ruta = carpeta / nombre
    with open(ruta, "wb") as salida:
        escritor.write(salida)
    return ruta


def _imagen(carpeta, nombre, tamano=(800, 600), modo="RGB"):
    from PIL import Image

    ruta = carpeta / nombre
    Image.new(modo, tamano, "red" if modo != "RGBA" else (255, 0, 0, 128)).save(ruta)
    return ruta


class TestLosRangos:
    def test_se_escriben_como_se_dicen(self):
        assert dividir.analizar_rangos("1-5, 8, 12-14", total=20) == [
            dividir.Trozo(1, 5),
            dividir.Trozo(8, 8),
            dividir.Trozo(12, 14),
        ]

    def test_un_intervalo_incluye_los_dos_extremos(self):
        """`1-5` son cinco páginas. Es como se cuenta un documento."""
        assert dividir.analizar_rangos("1-5", total=10)[0].cuantas == 5

    def test_el_espacio_no_estorba(self):
        assert dividir.analizar_rangos("  3 - 4 ,7 ", total=10) == [
            dividir.Trozo(3, 4),
            dividir.Trozo(7, 7),
        ]

    @pytest.mark.parametrize(
        "malo,dentro",
        [
            ("5-2", "al revés"),
            ("0-3", "desde 1"),
            ("1-99", "10 página"),
            ("uno", "no es un rango"),
            ("1--3", "no es un rango"),
        ],
    )
    def test_lo_que_falla_dice_cual_falla(self, malo, dentro):
        """«Rangos no válidos» obliga a mirar los cinco a ojo."""
        with pytest.raises(ComposicionInvalida) as fallo:
            dividir.analizar_rangos(malo, total=10)
        assert dentro in str(fallo.value)

    def test_sin_rangos(self):
        with pytest.raises(ComposicionInvalida):
            dividir.analizar_rangos("  ,  , ", total=10)

    def test_una_por_pagina(self):
        assert dividir.una_por_pagina(3) == [
            dividir.Trozo(1, 1),
            dividir.Trozo(2, 2),
            dividir.Trozo(3, 3),
        ]


class TestPartir:
    def test_escribe_un_archivo_por_trozo(self, tmp_path):
        origen = _pdf(tmp_path, "memoria.pdf", 10)
        escritos = dividir.partir(origen, dividir.analizar_rangos("1-3, 7", total=10))

        assert [r.name for r in escritos] == ["memoria_1-3.pdf", "memoria_7.pdf"]
        assert lector.leer_cabecera(escritos[0]).cuantas == 3
        assert lector.leer_cabecera(escritos[1]).cuantas == 1

    def test_una_por_pagina_de_verdad(self, tmp_path):
        origen = _pdf(tmp_path, "planos.pdf", 4)
        escritos = dividir.partir(origen, dividir.una_por_pagina(4))
        assert len(escritos) == 4
        assert all(lector.leer_cabecera(r).cuantas == 1 for r in escritos)

    def test_el_original_no_se_toca(self, tmp_path):
        origen = _pdf(tmp_path, "memoria.pdf", 5)
        antes = origen.read_bytes()
        dividir.partir(origen, dividir.una_por_pagina(5))
        assert origen.read_bytes() == antes

    def test_si_uno_falla_no_queda_ninguno(self, tmp_path):
        """Media entrega repartida por la carpeta, con nombres que parecen correctos, es
        peor que un error."""
        origen = _pdf(tmp_path, "memoria.pdf", 3)
        with pytest.raises(ComposicionInvalida):
            dividir.partir(origen, [dividir.Trozo(1, 1), dividir.Trozo(9, 9)])

        assert sorted(p.name for p in tmp_path.glob("*.pdf")) == ["memoria.pdf"]

    def test_se_puede_escribir_en_otra_carpeta(self, tmp_path):
        origen = _pdf(tmp_path, "memoria.pdf", 2)
        aparte = tmp_path / "salida"
        aparte.mkdir()
        escritos = dividir.partir(origen, dividir.una_por_pagina(2), carpeta=aparte)
        assert all(r.parent == aparte for r in escritos)


class TestImagenesAPdf:
    def test_una_pagina_por_imagen(self, tmp_path):
        imagenes = [_imagen(tmp_path, f"foto{i}.jpg") for i in range(3)]
        destino = tmp_path / "monografia.pdf"

        assert dividir.desde_imagenes(imagenes, destino) == 3
        assert lector.leer_cabecera(destino).cuantas == 3

    def test_en_a4_todas_las_hojas_miden_lo_mismo(self, tmp_path):
        """Es lo que se quiere de una monografía: hojas iguales aunque las fotos no lo
        sean."""
        imagenes = [
            _imagen(tmp_path, "ancha.jpg", (1200, 400)),
            _imagen(tmp_path, "alta.jpg", (400, 1200)),
        ]
        destino = tmp_path / "anexo.pdf"
        dividir.desde_imagenes(imagenes, destino, tamano="a4")

        formatos = {p.formato for p in lector.leer_cabecera(destino).paginas}
        assert formatos == {"A4"}

    def test_y_cada_hoja_toma_la_orientacion_de_su_foto(self, tmp_path):
        """Una foto apaisada en hoja vertical queda en una franja con dos bandas blancas
        enormes."""
        imagenes = [
            _imagen(tmp_path, "ancha.jpg", (1200, 400)),
            _imagen(tmp_path, "alta.jpg", (400, 1200)),
        ]
        destino = tmp_path / "anexo.pdf"
        dividir.desde_imagenes(imagenes, destino, tamano="a4")

        paginas = lector.leer_cabecera(destino).paginas
        assert paginas[0].orientacion == "apaisada"
        assert paginas[1].orientacion == "vertical"

    def test_con_tamano_de_imagen_la_hoja_mide_lo_que_el_original(self, tmp_path):
        imagen = _imagen(tmp_path, "escaneo.png", (1200, 400))
        destino = tmp_path / "escaneo.pdf"
        dividir.desde_imagenes([imagen], destino, tamano="imagen")

        pagina = lector.leer_cabecera(destino).paginas[0]
        assert pagina.apaisada is True
        # 1200 px a 96 ppp son 317,5 mm.
        assert pagina.ancho_mm == pytest.approx(317.5, abs=2)

    def test_una_transparencia_no_sale_con_el_fondo_negro(self, tmp_path):
        """Un PNG con alfa guardado tal cual en PDF deja el fondo en negro."""
        imagen = _imagen(tmp_path, "logo.png", (400, 400), modo="RGBA")
        destino = tmp_path / "logo.pdf"
        assert dividir.desde_imagenes([imagen], destino) == 1

    def test_un_archivo_que_no_es_imagen(self, tmp_path):
        falso = tmp_path / "memoria.pdf"
        falso.write_bytes(b"%PDF-1.7\n")
        with pytest.raises(ComposicionInvalida) as fallo:
            dividir.desde_imagenes([falso], tmp_path / "x.pdf")
        assert "no es una imagen" in str(fallo.value)

    def test_sin_imagenes(self, tmp_path):
        with pytest.raises(ComposicionInvalida):
            dividir.desde_imagenes([], tmp_path / "x.pdf")

    def test_un_tamano_inventado(self, tmp_path):
        imagen = _imagen(tmp_path, "foto.jpg")
        with pytest.raises(ComposicionInvalida):
            dividir.desde_imagenes([imagen], tmp_path / "x.pdf", tamano="tabloide")
