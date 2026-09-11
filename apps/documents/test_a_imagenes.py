"""Sacar las páginas de un PDF como imágenes.

El oráculo aquí es **Pillow leyendo el archivo escrito**: no se comprueba que la función
devolvió una ruta, se abre la imagen y se miran sus píxeles y su modo. Una ruta devuelta no
prueba que haya una imagen al otro lado.
"""

from pathlib import Path

import pytest

from apps.documents import a_imagenes
from apps.documents.composicion import ComposicionInvalida
from apps.documents.dividir import Trozo
from apps.formats import pdf as lector


def _pdf(carpeta: Path, nombre: str, cuantas: int, ancho_mm=210.0, alto_mm=297.0) -> Path:
    from pypdf import PdfWriter

    escritor = PdfWriter()
    for _ in range(cuantas):
        escritor.add_blank_page(
            width=ancho_mm / lector.MM_POR_PUNTO, height=alto_mm / lector.MM_POR_PUNTO
        )
    ruta = carpeta / nombre
    with open(ruta, "wb") as salida:
        escritor.write(salida)
    return ruta


def _abrir(ruta: Path):
    from PIL import Image

    return Image.open(ruta)


class TestLoQueEscribe:
    def test_una_imagen_por_pagina_pedida(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 6)
        escritas = a_imagenes.paginas_a_imagenes(memoria, [Trozo(2, 4)])
        assert [r.name for r in escritas] == [
            "memoria_2.png",
            "memoria_3.png",
            "memoria_4.png",
        ]
        assert all(r.exists() for r in escritas)

    def test_la_resolucion_decide_el_tamano(self, tmp_path):
        """Una A4 a 150 ppp son 1.240 × 1.754 px. Es la cifra del docstring del módulo, y
        se comprueba con la imagen delante."""
        memoria = _pdf(tmp_path, "a4.pdf", 1)
        (salida,) = a_imagenes.paginas_a_imagenes(memoria, [Trozo(1, 1)], ppp=150)
        with _abrir(salida) as imagen:
            assert imagen.size == pytest.approx((1240, 1754), abs=3)

    def test_el_doble_de_ppp_es_el_doble_de_lado(self, tmp_path):
        memoria = _pdf(tmp_path, "a4.pdf", 1)
        fina = tmp_path / "fina"
        gruesa = tmp_path / "gruesa"
        fina.mkdir()
        gruesa.mkdir()

        (a,) = a_imagenes.paginas_a_imagenes(memoria, [Trozo(1, 1)], ppp=150, carpeta=fina)
        (b,) = a_imagenes.paginas_a_imagenes(memoria, [Trozo(1, 1)], ppp=300, carpeta=gruesa)

        with _abrir(a) as una, _abrir(b) as otra:
            assert otra.size[0] == pytest.approx(una.size[0] * 2, abs=3)

    def test_el_jpg_sale_sin_canal_alfa(self, tmp_path):
        """PDFium dibuja con transparencia y el JPEG no la admite: sin el paso por RGB,
        Pillow falla al guardar."""
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        (salida,) = a_imagenes.paginas_a_imagenes(memoria, [Trozo(1, 1)], formato="jpg")
        with _abrir(salida) as imagen:
            assert imagen.mode == "RGB"
            assert imagen.format == "JPEG"

    def test_las_paginas_repetidas_se_escriben_una_vez(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 4)
        escritas = a_imagenes.paginas_a_imagenes(memoria, [Trozo(1, 2), Trozo(2, 3)])
        assert [r.name for r in escritas] == ["memoria_1.png", "memoria_2.png", "memoria_3.png"]

    def test_el_original_no_se_toca(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 3)
        antes = memoria.read_bytes()
        a_imagenes.paginas_a_imagenes(memoria, [Trozo(1, 3)])
        assert memoria.read_bytes() == antes


class TestLoQueSeNiegaAHacer:
    def test_un_formato_que_no_existe(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        with pytest.raises(ComposicionInvalida, match="formato de imagen"):
            a_imagenes.paginas_a_imagenes(memoria, [Trozo(1, 1)], formato="gif")

    def test_una_resolucion_que_no_se_ofrece(self, tmp_path):
        """No hay campo libre de ppp a propósito: 1200 se teclea en un segundo y se paga
        durante dos minutos."""
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        with pytest.raises(ComposicionInvalida, match="resoluciones"):
            a_imagenes.paginas_a_imagenes(memoria, [Trozo(1, 1)], ppp=1200)

    def test_sin_paginas(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        with pytest.raises(ComposicionInvalida, match="ninguna página"):
            a_imagenes.paginas_a_imagenes(memoria, [])

    def test_una_pagina_que_no_existe(self, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 2)
        with pytest.raises(ComposicionInvalida, match="se pidió la 5"):
            a_imagenes.paginas_a_imagenes(memoria, [Trozo(5, 5)])

    def test_algo_que_no_es_un_pdf(self, tmp_path):
        falso = tmp_path / "x.pdf"
        falso.write_bytes(b"no soy un pdf")
        with pytest.raises(ComposicionInvalida, match="No se pudo abrir"):
            a_imagenes.paginas_a_imagenes(falso, [Trozo(1, 1)])

    def test_una_lamina_enorme_a_300_ppp_se_para_antes_de_dibujar(self, tmp_path):
        """Un A0 a 300 ppp son casi 14.000 px de lado y varios cientos de megas. Se dice
        antes, no después de que la máquina se quede parada."""
        a0 = _pdf(tmp_path, "a0.pdf", 1, ancho_mm=1189.0, alto_mm=841.0)
        with pytest.raises(ComposicionInvalida, match="Baja la resolución"):
            a_imagenes.paginas_a_imagenes(a0, [Trozo(1, 1)], ppp=300)

    def test_y_no_deja_a_medias_lo_que_ya_habia_escrito(self, tmp_path):
        """Todas o ninguna: cuatro imágenes con nombres correlativos y la quinta ausente es
        peor que un error, porque parece una entrega completa."""
        memoria = _pdf(tmp_path, "memoria.pdf", 3)
        with pytest.raises(ComposicionInvalida):
            a_imagenes.paginas_a_imagenes(memoria, [Trozo(1, 3), Trozo(9, 9)])
        assert list(tmp_path.glob("memoria_*.png")) == []
