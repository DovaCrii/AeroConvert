"""Recortar y cambiar el tamaño de un PDF (F14.6).

**El oráculo es PDFium** (`get_size()` y el dibujo de la página), que no escribió el archivo. Los
PDF de partida los dibuja `reportlab` con un rectángulo negro **en un sitio conocido**, así que
las cotas esperadas salen de la geometría y no de lo que devuelve la función.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pypdfium2
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from apps.documents import tamano, tarea

pytestmark = pytest.mark.django_db

A4 = (595.2756, 841.8898)
MM = 72 / 25.4


def _pdf_con_rectangulo(
    carpeta: Path,
    *,
    caja=(100, 200, 300, 400),
    pagina=A4,
    giro: int = 0,
    paginas: int = 1,
    nombre: str = "plano.pdf",
) -> Path:
    ruta = carpeta / nombre
    lienzo = canvas.Canvas(str(ruta), pagesize=pagina)
    for _ in range(paginas):
        lienzo.setFillGray(0)
        x0, y0, x1, y1 = caja
        lienzo.rect(x0, y0, x1 - x0, y1 - y0, stroke=0, fill=1)
        lienzo.showPage()
    lienzo.save()
    if giro:
        lector = PdfReader(str(ruta))
        escritor = PdfWriter()
        for p in lector.pages:
            p.rotate(giro)
            escritor.add_page(p)
        with open(ruta, "wb") as salida:
            escritor.write(salida)
    return ruta


def _tamano_pdfium(ruta: Path, pagina: int = 0) -> tuple[float, float]:
    documento = pypdfium2.PdfDocument(str(ruta))
    try:
        hoja = documento[pagina]
        try:
            return hoja.get_size()
        finally:
            hoja.close()
    finally:
        documento.close()


def _caja_oscura(ruta: Path, pagina: int = 0, escala: float = 2.0):
    """(x0, y0, x1, y1) de lo oscuro, en puntos y con la y desde arriba, y el tamaño visto."""
    documento = pypdfium2.PdfDocument(str(ruta))
    try:
        hoja = documento[pagina]
        try:
            imagen = hoja.render(scale=escala).to_pil().convert("L")
            ancho, alto = hoja.get_size()
        finally:
            hoja.close()
    finally:
        documento.close()
    caja = imagen.point(lambda p: 255 if p < 128 else 0).getbbox()
    return tuple(v / escala for v in caja), (ancho, alto)


def _cerca(a: float, b: float, tolerancia: float = 1.0) -> bool:
    return abs(a - b) <= tolerancia


class TestAlContenido:
    def test_la_hoja_queda_del_tamano_del_dibujo_mas_el_margen(self, tmp_path):
        destino = tmp_path / "recortado.pdf"
        hecho = tamano.recortar_al_contenido(_pdf_con_rectangulo(tmp_path), destino, margen_mm=5)

        assert hecho.modificadas == 1
        ancho, alto = _tamano_pdfium(destino)
        margen = 5 * MM
        assert _cerca(ancho, 200 + 2 * margen) and _cerca(alto, 200 + 2 * margen)
        # Y el dibujo sigue entero, a un margen de cada borde.
        (x0, y0, x1, y1), _ = _caja_oscura(destino)
        assert _cerca(x0, margen) and _cerca(y0, margen)
        assert _cerca(x1 - x0, 200) and _cerca(y1 - y0, 200)

    def test_una_hoja_en_blanco_se_deja_como_estaba(self, tmp_path):
        ruta = tmp_path / "blanco.pdf"
        lienzo = canvas.Canvas(str(ruta), pagesize=A4)
        lienzo.showPage()
        lienzo.save()
        destino = tmp_path / "recortado.pdf"
        hecho = tamano.recortar_al_contenido(ruta, destino)
        assert hecho.modificadas == 0
        assert _cerca(_tamano_pdfium(destino)[0], A4[0])

    def test_una_pagina_girada_se_recorta_en_lo_que_se_ve(self, tmp_path):
        origen = _pdf_con_rectangulo(tmp_path, giro=90)
        destino = tmp_path / "recortado.pdf"
        tamano.recortar_al_contenido(origen, destino, margen_mm=5)
        ancho, alto = _tamano_pdfium(destino)
        margen = 5 * MM
        # El rectángulo mide 200 × 200: gire lo que gire, la hoja es cuadrada de 200 + márgenes.
        assert _cerca(ancho, 200 + 2 * margen) and _cerca(alto, 200 + 2 * margen)
        (x0, y0, x1, y1), _ = _caja_oscura(destino)
        assert _cerca(x0, margen) and _cerca(y0, margen)

    def test_la_posicion_del_dibujo_se_conserva_en_una_pagina_girada(self, tmp_path):
        # Rectángulo bajo y a la izquierda, no cuadrado: 100 de ancho y 40 de alto.
        origen = _pdf_con_rectangulo(tmp_path, caja=(50, 60, 150, 100), giro=90)
        destino = tmp_path / "recortado.pdf"
        tamano.recortar_al_contenido(origen, destino, margen_mm=0)
        ancho, alto = _tamano_pdfium(destino)
        # Girado 90° el dibujo se ve de 40 de ancho por 100 de alto.
        assert _cerca(ancho, 40) and _cerca(alto, 100)

    def test_el_margen_fuera_de_rango_se_rechaza(self, tmp_path):
        with pytest.raises(tamano.ComposicionInvalida):
            tamano.recortar_al_contenido(
                _pdf_con_rectangulo(tmp_path), tmp_path / "x.pdf", margen_mm=80
            )


class TestAMano:
    def test_quita_los_milimetros_pedidos_de_cada_lado(self, tmp_path):
        destino = tmp_path / "recortado.pdf"
        tamano.recortar_a_mano(
            _pdf_con_rectangulo(tmp_path),
            destino,
            arriba_mm=10,
            derecha_mm=20,
            abajo_mm=30,
            izquierda_mm=40,
        )
        ancho, alto = _tamano_pdfium(destino)
        assert _cerca(ancho, A4[0] - 60 * MM) and _cerca(alto, A4[1] - 40 * MM)

    def test_el_dibujo_se_corre_lo_que_se_recorta_a_la_izquierda(self, tmp_path):
        destino = tmp_path / "recortado.pdf"
        tamano.recortar_a_mano(_pdf_con_rectangulo(tmp_path), destino, izquierda_mm=20)
        (x0, _, _, _), _ = _caja_oscura(destino)
        assert _cerca(x0, 100 - 20 * MM)

    def test_dejar_la_pagina_sin_nada_se_rechaza(self, tmp_path):
        with pytest.raises(tamano.ComposicionInvalida, match="sin nada"):
            tamano.recortar_a_mano(
                _pdf_con_rectangulo(tmp_path), tmp_path / "x.pdf", izquierda_mm=300, derecha_mm=100
            )

    def test_sin_ningun_lado_se_rechaza(self, tmp_path):
        with pytest.raises(tamano.ComposicionInvalida, match="al menos uno"):
            tamano.recortar_a_mano(_pdf_con_rectangulo(tmp_path), tmp_path / "x.pdf")


class TestCambiarTamano:
    @pytest.mark.parametrize("hoja", ["a3", "a4", "carta", "oficio"])
    def test_la_hoja_sale_del_tamano_pedido(self, tmp_path, hoja):
        destino = tmp_path / "otra.pdf"
        tamano.cambiar_tamano(_pdf_con_rectangulo(tmp_path), destino, hoja)
        corto, largo = sorted(tamano.TAMANOS_MM[hoja])
        ancho, alto = _tamano_pdfium(destino)
        assert _cerca(ancho, corto * MM) and _cerca(alto, largo * MM)

    def test_el_contenido_se_escala_sin_deformarse_y_queda_centrado(self, tmp_path):
        # Un A4 con un cuadrado de 200: a A3 todo crece por el mismo factor.
        destino = tmp_path / "a3.pdf"
        tamano.cambiar_tamano(_pdf_con_rectangulo(tmp_path), destino, "a3")
        (x0, y0, x1, y1), (ancho, alto) = _caja_oscura(destino)
        factor = (297 * MM) / A4[0]
        assert _cerca(x1 - x0, 200 * factor, 2) and _cerca(y1 - y0, 200 * factor, 2)
        assert _cerca(x0, 100 * factor, 2)  # el dibujo no se movió respecto de su hoja

    def test_una_lamina_apaisada_sigue_apaisada(self, tmp_path):
        origen = _pdf_con_rectangulo(tmp_path, pagina=(A4[1], A4[0]), caja=(100, 100, 300, 300))
        destino = tmp_path / "a3.pdf"
        tamano.cambiar_tamano(origen, destino, "a3")
        ancho, alto = _tamano_pdfium(destino)
        assert ancho > alto and _cerca(ancho, 420 * MM)

    def test_una_pagina_girada_tambien_sale_del_tamano_pedido(self, tmp_path):
        origen = _pdf_con_rectangulo(tmp_path, giro=90)
        destino = tmp_path / "a3.pdf"
        tamano.cambiar_tamano(origen, destino, "a3")
        ancho, alto = _tamano_pdfium(destino)
        assert ancho > alto and _cerca(ancho, 420 * MM) and _cerca(alto, 297 * MM)

    def test_un_tamano_que_no_existe_se_rechaza(self, tmp_path):
        with pytest.raises(tamano.ComposicionInvalida):
            tamano.cambiar_tamano(_pdf_con_rectangulo(tmp_path), tmp_path / "x.pdf", "a9")

    def test_conserva_todas_las_paginas(self, tmp_path):
        destino = tmp_path / "a3.pdf"
        tamano.cambiar_tamano(_pdf_con_rectangulo(tmp_path, paginas=3), destino, "a3")
        assert len(PdfReader(str(destino)).pages) == 3


def test_el_original_no_se_toca(tmp_path):
    origen = _pdf_con_rectangulo(tmp_path)
    antes = (hashlib.sha256(origen.read_bytes()).hexdigest(), origen.stat().st_mtime_ns)
    tamano.recortar_al_contenido(origen, tmp_path / "a.pdf")
    tamano.recortar_a_mano(origen, tmp_path / "b.pdf", izquierda_mm=5)
    tamano.cambiar_tamano(origen, tmp_path / "c.pdf", "a3")
    assert (hashlib.sha256(origen.read_bytes()).hexdigest(), origen.stat().st_mtime_ns) == antes


class TestEnLaTareaYLaPantalla:
    def test_la_tarea_cambia_de_hoja(self, tmp_path):
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "tamano",
            {
                "entradas": [{"ruta": str(_pdf_con_rectangulo(tmp_path))}],
                "opciones": {"modo": "hoja", "hoja": "a3"},
            },
            parcial,
        )
        assert "codigo" not in informe
        assert _cerca(_tamano_pdfium(parcial)[0], 297 * MM)

    def test_un_modo_que_no_existe_falla_con_su_codigo(self, tmp_path):
        informe = tarea.ejecutar(
            "tamano",
            {
                "entradas": [{"ruta": str(_pdf_con_rectangulo(tmp_path))}],
                "opciones": {"modo": "otro"},
            },
            tmp_path / "salida.parcial",
        )
        assert informe["codigo"] == "documento-invalido"

    @pytest.fixture
    def sesion(self, client, tmp_path, settings):
        settings.RAICES_PERMITIDAS = str(tmp_path)
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def test_pide_sesion(self, client):
        assert client.get(reverse("documents:tamano")).status_code == 302

    def test_a_mano_sin_ningun_lado_avisa(self, sesion, tmp_path):
        respuesta = sesion.post(
            reverse("documents:tamano"),
            {"ruta": str(_pdf_con_rectangulo(tmp_path)), "accion": "hacer", "modo": "mano"},
        )
        assert respuesta.status_code == 200
        assert "Escriba cuántos milímetros" in respuesta.content.decode()

    def test_recortar_al_contenido_encola_y_el_resultado_es_mas_chico(self, sesion, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        respuesta = sesion.post(
            reverse("documents:tamano"),
            {
                "ruta": str(_pdf_con_rectangulo(tmp_path)),
                "accion": "hacer",
                "modo": "contenido",
                "margen_mm": "5",
            },
        )
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        ancho, alto = _tamano_pdfium(Path(trabajo.output_path))
        assert ancho < A4[0] / 2 and alto < A4[1] / 2
