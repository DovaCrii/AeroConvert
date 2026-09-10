"""Las pantallas de dividir e imágenes a PDF, y el índice que las junta.

Lo que se vigila aquí es lo mismo que en el resto de la aplicación: que las rutas pasen por
la misma puerta, que el original no se toque, y que un error deje la pantalla usable en vez
de media entrega repartida por la carpeta.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.documents import views
from apps.formats import pdf as lector

pytestmark = pytest.mark.django_db


def _pdf(carpeta, nombre, cuantas):
    from pypdf import PdfWriter

    escritor = PdfWriter()
    for _ in range(cuantas):
        escritor.add_blank_page(width=210 / lector.MM_POR_PUNTO, height=297 / lector.MM_POR_PUNTO)
    ruta = carpeta / nombre
    with open(ruta, "wb") as salida:
        escritor.write(salida)
    return ruta


def _imagen(carpeta, nombre, tamano=(1200, 800)):
    from PIL import Image

    ruta = carpeta / nombre
    Image.new("RGB", tamano, (200, 40, 40)).save(ruta)
    return ruta


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    client.force_login(
        get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    )
    return client


class TestElIndice:
    def test_carga_y_lista_las_herramientas(self, sesion):
        cuerpo = sesion.get(reverse("documents:inicio")).content.decode()
        for herramienta in views.HERRAMIENTAS:
            assert herramienta["nombre"] in cuerpo

    def test_cada_una_lleva_a_su_pantalla(self, sesion):
        cuerpo = sesion.get(reverse("documents:inicio")).content.decode()
        for herramienta in views.HERRAMIENTAS:
            assert reverse(herramienta["url"]) in cuerpo

    def test_dice_por_que_no_se_usa_una_web(self, sesion):
        """Es la razón de que esto exista: un plano bajo acuerdo de confidencialidad no
        puede subirse al servidor de nadie."""
        cuerpo = sesion.get(reverse("documents:inicio")).content.decode()
        assert "suben tu archivo" in cuerpo


class TestDividir:
    def test_mirar_enseña_cuantas_paginas_hay(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 8)
        cuerpo = sesion.post(
            reverse("documents:dividir"), {"ruta": str(memoria), "accion": "mirar"}
        ).content.decode()
        assert "8 página(s)" in cuerpo

    def test_partir_por_rangos(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 8)
        sesion.post(
            reverse("documents:dividir"),
            {"ruta": str(memoria), "accion": "partir", "modo": "rangos", "rangos": "1-3, 7"},
        )
        assert sorted(p.name for p in tmp_path.glob("memoria_*.pdf")) == [
            "memoria_1-3.pdf",
            "memoria_7.pdf",
        ]

    def test_partir_en_hojas_sueltas(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 3)
        sesion.post(
            reverse("documents:dividir"),
            {"ruta": str(memoria), "accion": "partir", "modo": "hojas"},
        )
        assert len(list(tmp_path.glob("memoria_*.pdf"))) == 3

    def test_un_rango_al_reves_lo_dice_y_no_escribe_nada(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 8)
        cuerpo = sesion.post(
            reverse("documents:dividir"),
            {"ruta": str(memoria), "accion": "partir", "modo": "rangos", "rangos": "5-2"},
            follow=True,
        ).content.decode()

        assert "al revés" in cuerpo
        assert list(tmp_path.glob("memoria_*.pdf")) == []

    def test_el_original_no_se_toca(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 4)
        antes = memoria.read_bytes()
        sesion.post(
            reverse("documents:dividir"),
            {"ruta": str(memoria), "accion": "partir", "modo": "hojas"},
        )
        assert memoria.read_bytes() == antes

    def test_una_ruta_fuera_de_las_raices(self, sesion):
        cuerpo = sesion.post(
            reverse("documents:dividir"),
            {"ruta": "C:\\Windows\\System32\\config\\SAM", "accion": "mirar"},
            follow=True,
        ).content.decode()
        assert "página(s)" not in cuerpo

    def test_algo_que_no_es_un_pdf(self, sesion, tmp_path):
        falso = tmp_path / "x.pdf"
        falso.write_bytes(b"%PDF-1.7\nno soy un pdf\n")
        respuesta = sesion.post(
            reverse("documents:dividir"), {"ruta": str(falso), "accion": "mirar"}, follow=True
        )
        assert respuesta.status_code == 200


class TestImagenesAPdf:
    def test_una_pagina_por_imagen(self, sesion, tmp_path):
        fotos = [_imagen(tmp_path, f"foto{i}.jpg") for i in (1, 2)]
        sesion.post(
            reverse("documents:imagenes"),
            {"archivos_texto": "\n".join(str(f) for f in fotos), "tamano": "a4"},
        )
        salida = tmp_path / "foto1_imagenes.pdf"
        assert lector.leer_cabecera(salida).cuantas == 2

    def test_cada_hoja_toma_la_orientacion_de_su_foto(self, sesion, tmp_path):
        fotos = [
            _imagen(tmp_path, "ancha.jpg", (1200, 800)),
            _imagen(tmp_path, "alta.jpg", (800, 1200)),
        ]
        sesion.post(
            reverse("documents:imagenes"),
            {"archivos_texto": "\n".join(str(f) for f in fotos), "tamano": "a4"},
        )
        paginas = lector.leer_cabecera(tmp_path / "ancha_imagenes.pdf").paginas
        assert [p.orientacion for p in paginas] == ["apaisada", "vertical"]

    def test_sin_imagenes_lo_dice(self, sesion):
        cuerpo = sesion.post(
            reverse("documents:imagenes"), {"archivos_texto": "  ", "tamano": "a4"}, follow=True
        ).content.decode()
        assert "ninguna imagen" in cuerpo

    def test_un_pdf_no_es_una_imagen(self, sesion, tmp_path):
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        cuerpo = sesion.post(
            reverse("documents:imagenes"),
            {"archivos_texto": str(memoria), "tamano": "a4"},
            follow=True,
        ).content.decode()
        assert "no es una imagen" in cuerpo

    def test_y_no_deja_un_parcial_tirado(self, sesion, tmp_path):
        """El parcial existe mientras se escribe; si falla, se borra."""
        memoria = _pdf(tmp_path, "memoria.pdf", 1)
        sesion.post(reverse("documents:imagenes"), {"archivos_texto": str(memoria), "tamano": "a4"})
        assert list(tmp_path.glob("*parcial*")) == []
