"""Reparar un PDF dañado (F14.20).

**El oráculo es `pypdf` en modo estricto**, que se niega a abrir lo roto: primero se comprueba que
el archivo de partida de verdad no abre (si abriera, la prueba no mediría nada) y después que el
reparado sí, con el número de páginas que había y el texto de cada una. El daño se hace cortando
el archivo donde empieza la tabla `xref`, que es como se rompe una descarga.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pypdfium2
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from apps.documents import reparar, tarea

pytestmark = pytest.mark.django_db

HOJAS = ("Hoja uno del juego", "Hoja dos del juego", "Hoja tres del juego")


def _sano(carpeta: Path, nombre: str = "juego.pdf") -> Path:
    ruta = carpeta / nombre
    lienzo = canvas.Canvas(str(ruta), pagesize=(300, 300), pageCompression=0)
    for texto in HOJAS:
        lienzo.setFont("Helvetica", 14)
        lienzo.drawString(30, 150, texto)
        lienzo.showPage()
    lienzo.save()
    return ruta


def _cortado(carpeta: Path) -> Path:
    """Sin la tabla `xref` ni el final: como una descarga que se interrumpió justo ahí."""
    original = _sano(carpeta, "entero.pdf").read_bytes()
    punto = original.rfind(b"xref\n")
    assert punto > 0
    roto = carpeta / "roto.pdf"
    roto.write_bytes(original[:punto])
    return roto


def _abre_estricto(ruta: Path) -> int | None:
    try:
        return len(PdfReader(str(ruta), strict=True).pages)
    except Exception:
        return None


class TestReparar:
    def test_el_archivo_de_partida_de_verdad_no_abre(self, tmp_path):
        # El control: sin esto, la prueba de abajo mediría un archivo que ya abría.
        assert _abre_estricto(_cortado(tmp_path)) is None

    def test_el_reparado_abre_con_todas_las_paginas_y_su_texto(self, tmp_path):
        roto = _cortado(tmp_path)
        destino = tmp_path / "reparado.pdf"
        hecho = reparar.reparar(roto, destino)

        assert hecho.paginas == 3 and not hecho.estaba_sano
        assert _abre_estricto(destino) == 3
        lector = PdfReader(str(destino), strict=True)
        for pagina, texto in zip(lector.pages, HOJAS, strict=True):
            assert texto in pagina.extract_text()

    def test_el_reparado_lo_dibuja_PDFium_con_el_tamano_original(self, tmp_path):
        destino = tmp_path / "reparado.pdf"
        reparar.reparar(_cortado(tmp_path), destino)
        documento = pypdfium2.PdfDocument(str(destino))
        try:
            assert len(documento) == 3
            hoja = documento[0]
            try:
                assert hoja.get_size() == pytest.approx((300, 300), abs=0.5)
            finally:
                hoja.close()
        finally:
            documento.close()

    def test_un_pdf_sano_se_reescribe_y_lo_dice(self, tmp_path):
        hecho = reparar.reparar(_sano(tmp_path), tmp_path / "x.pdf")
        assert hecho.estaba_sano and hecho.paginas == 3

    def test_lo_que_no_es_un_pdf_se_rechaza_con_su_motivo(self, tmp_path):
        basura = tmp_path / "x.pdf"
        basura.write_bytes(b"esto no es un pdf, ni cerca")
        with pytest.raises(reparar.ComposicionInvalida, match="ni siquiera se reconoce"):
            reparar.reparar(basura, tmp_path / "y.pdf")
        assert not (tmp_path / "y.pdf").exists()

    def test_el_original_no_se_toca(self, tmp_path):
        roto = _cortado(tmp_path)
        antes = (hashlib.sha256(roto.read_bytes()).hexdigest(), roto.stat().st_mtime_ns)
        reparar.reparar(roto, tmp_path / "reparado.pdf")
        assert (hashlib.sha256(roto.read_bytes()).hexdigest(), roto.stat().st_mtime_ns) == antes


class TestEnLaTareaYLaPantalla:
    def test_la_tarea_repara(self, tmp_path):
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "reparar", {"entradas": [{"ruta": str(_cortado(tmp_path))}], "opciones": {}}, parcial
        )
        assert "codigo" not in informe and informe["detalles"]["paginas"] == 3
        assert _abre_estricto(parcial) == 3

    @pytest.fixture
    def sesion(self, client, tmp_path, settings):
        settings.RAICES_PERMITIDAS = str(tmp_path)
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def test_pide_sesion(self, client):
        assert client.get(reverse("documents:reparar")).status_code == 302

    def test_acepta_un_pdf_que_la_cabecera_no_puede_leer(self, sesion, tmp_path):
        """Las demás pantallas se niegan a un PDF roto: esta es justo para él."""
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        respuesta = sesion.post(reverse("documents:reparar"), {"ruta": str(_cortado(tmp_path))})
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        assert _abre_estricto(Path(trabajo.output_path)) == 3

    def test_rechaza_lo_que_no_es_pdf_antes_de_encolar(self, sesion, tmp_path):
        otro = tmp_path / "foto.png"
        otro.write_bytes(b"\x89PNG")
        respuesta = sesion.post(reverse("documents:reparar"), {"ruta": str(otro)})
        assert respuesta.status_code == 200 and "no es un PDF" in respuesta.content.decode()
