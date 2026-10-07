"""Poner una firma visible en un PDF (F14.4).

**El oráculo es PDFium dibujando la página**: la firma es una imagen negra maciza y el recuadro
de píxeles oscuros que aparece tiene que caer donde se pidió, con ±2 px. Las cotas esperadas se
calculan aquí **desde la regla** (12 mm de margen en un A4, 45 mm de ancho), no desde lo que
devuelve la función.
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from PIL import Image
from pypdf import PdfReader, PdfWriter

from apps.documents import firma_visible, tarea

pytestmark = pytest.mark.django_db

A4 = (595.28, 841.89)
MARGEN_A4 = 12.0 / (25.4 / 72)  # 12 mm en puntos
TOLERANCIA_PX = 2


def _pdf(carpeta: Path, paginas: int = 2, giro: int = 0, nombre: str = "doc.pdf") -> Path:
    escritor = PdfWriter()
    for _ in range(paginas):
        pagina = escritor.add_blank_page(width=A4[0], height=A4[1])
        if giro:
            pagina.rotate(giro)
    ruta = carpeta / nombre
    with open(ruta, "wb") as salida:
        escritor.write(salida)
    return ruta


def _firma(carpeta: Path, tamano=(200, 80), color=(0, 0, 0)) -> Path:
    ruta = carpeta / "firma.png"
    Image.new("RGB", tamano, color).save(ruta)
    return ruta


def _caja_oscura(ruta: Path, pagina: int = 1) -> tuple[int, int, int, int, int, int]:
    """(x0, y0, x1, y1, ancho_img, alto_img) de lo oscuro, con PDFium y la y desde arriba."""
    documento = pypdfium2.PdfDocument(str(ruta))
    try:
        hoja = documento[pagina - 1]
        try:
            imagen = hoja.render(scale=1).to_pil().convert("L")
        finally:
            hoja.close()
    finally:
        documento.close()
    caja = imagen.point(lambda p: 255 if p < 128 else 0).getbbox()
    assert caja is not None, "no hay nada oscuro: la firma no se dibujó"
    return (*caja, *imagen.size)


def _cerca(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCIA_PX


class TestDondeCae:
    def test_pie_a_la_derecha_en_un_a4(self, tmp_path):
        destino = tmp_path / "firmado.pdf"
        firma_visible.estampar(
            _pdf(tmp_path), _firma(tmp_path), destino, pagina=1, posicion="pie-derecha", ancho_mm=45
        )
        x0, y0, x1, y1, ancho, alto = _caja_oscura(destino)
        ancho_firma = 45 / (25.4 / 72)
        alto_firma = ancho_firma * 80 / 200
        assert _cerca(x1, ancho - MARGEN_A4)
        assert _cerca(x1 - x0, ancho_firma)
        assert _cerca(y1, alto - MARGEN_A4)  # el pie: a un margen del borde de abajo
        assert _cerca(y1 - y0, alto_firma)

    def test_cabecera_a_la_izquierda(self, tmp_path):
        destino = tmp_path / "firmado.pdf"
        firma_visible.estampar(
            _pdf(tmp_path),
            _firma(tmp_path),
            destino,
            pagina=1,
            posicion="cabecera-izquierda",
            ancho_mm=30,
        )
        x0, y0, _, _, _, _ = _caja_oscura(destino)
        assert _cerca(x0, MARGEN_A4) and _cerca(y0, MARGEN_A4)

    def test_centrada(self, tmp_path):
        destino = tmp_path / "firmado.pdf"
        firma_visible.estampar(
            _pdf(tmp_path), _firma(tmp_path), destino, pagina=1, posicion="pie-centro"
        )
        x0, _, x1, _, ancho, _ = _caja_oscura(destino)
        assert _cerca((x0 + x1) / 2, ancho / 2)

    def test_solo_la_pagina_pedida_lleva_firma(self, tmp_path):
        destino = tmp_path / "firmado.pdf"
        firma_visible.estampar(_pdf(tmp_path), _firma(tmp_path), destino, pagina=2)
        _caja_oscura(destino, pagina=2)
        with pytest.raises(AssertionError, match="no hay nada oscuro"):
            _caja_oscura(destino, pagina=1)

    def test_en_una_pagina_girada_cae_en_la_esquina_que_se_ve(self, tmp_path):
        destino = tmp_path / "firmado.pdf"
        firma_visible.estampar(
            _pdf(tmp_path, paginas=1, giro=90), _firma(tmp_path), destino, pagina=1
        )
        _, _, x1, y1, ancho, alto = _caja_oscura(destino)
        assert ancho > alto  # PDFium la dibuja apaisada
        assert _cerca(x1, ancho - MARGEN_A4) and _cerca(y1, alto - MARGEN_A4)

    def test_la_leyenda_se_lee_con_otro_lector(self, tmp_path):
        destino = tmp_path / "firmado.pdf"
        firma_visible.estampar(
            _pdf(tmp_path), _firma(tmp_path), destino, pagina=1, leyenda="Ana Pérez · 07-10-2026"
        )
        texto = PdfReader(str(destino)).pages[0].extract_text()
        assert "07-10-2026" in texto


class TestRechazos:
    def test_una_imagen_que_no_es_imagen(self, tmp_path):
        falsa = tmp_path / "firma.png"
        falsa.write_bytes(b"esto no es una imagen")
        with pytest.raises(firma_visible.ComposicionInvalida, match="no es una imagen"):
            firma_visible.estampar(_pdf(tmp_path), falsa, tmp_path / "x.pdf", pagina=1)

    def test_una_pagina_que_no_existe(self, tmp_path):
        with pytest.raises(firma_visible.ComposicionInvalida, match="no existe la 9"):
            firma_visible.estampar(_pdf(tmp_path), _firma(tmp_path), tmp_path / "x.pdf", pagina=9)

    def test_una_firma_que_no_cabe(self, tmp_path):
        ancha = _firma(tmp_path, tamano=(100, 1200))
        with pytest.raises(firma_visible.ComposicionInvalida, match="no cabe"):
            firma_visible.estampar(_pdf(tmp_path), ancha, tmp_path / "x.pdf", pagina=1, ancho_mm=70)

    def test_el_original_no_se_toca(self, tmp_path):
        import hashlib

        origen = _pdf(tmp_path)
        antes = (hashlib.sha256(origen.read_bytes()).hexdigest(), origen.stat().st_mtime_ns)
        firma_visible.estampar(origen, _firma(tmp_path), tmp_path / "x.pdf", pagina=1)
        assert (hashlib.sha256(origen.read_bytes()).hexdigest(), origen.stat().st_mtime_ns) == antes


class TestEnLaTareaYLaPantalla:
    def test_la_tarea_estampa(self, tmp_path):
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "firma_visible",
            {
                "entradas": [{"ruta": str(_pdf(tmp_path))}, {"ruta": str(_firma(tmp_path))}],
                "opciones": {"pagina": 1, "posicion": "pie-derecha", "ancho_mm": 45},
            },
            parcial,
        )
        assert "codigo" not in informe
        _caja_oscura(parcial)

    def test_la_tarea_sin_imagen_dice_que_falta(self, tmp_path):
        informe = tarea.ejecutar(
            "firma_visible",
            {"entradas": [{"ruta": str(_pdf(tmp_path))}], "opciones": {}},
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
        assert client.get(reverse("documents:firma_visible")).status_code == 302

    def test_la_pantalla_avisa_que_no_es_firma_digital(self, sesion):
        cuerpo = sesion.get(reverse("documents:firma_visible")).content.decode()
        assert "No es una firma digital" in cuerpo or "no es una firma digital" in cuerpo

    def test_firmar_sin_imagen_avisa(self, sesion, tmp_path):
        respuesta = sesion.post(
            reverse("documents:firma_visible"),
            {"ruta": str(_pdf(tmp_path)), "accion": "firmar", "pagina": "1"},
        )
        assert respuesta.status_code == 200

    def test_firmar_encola_y_la_firma_cae_donde_se_pidio(self, sesion, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        with open(_firma(tmp_path), "rb") as imagen:
            respuesta = sesion.post(
                reverse("documents:firma_visible"),
                {
                    "ruta": str(_pdf(tmp_path)),
                    "accion": "firmar",
                    "pagina": "1",
                    "posicion": "pie-derecha",
                    "ancho_mm": "45",
                    "firma_subida": imagen,
                },
            )
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        _, _, x1, y1, ancho, alto = _caja_oscura(Path(trabajo.output_path))
        assert _cerca(x1, ancho - MARGEN_A4) and _cerca(y1, alto - MARGEN_A4)
