"""Comparar dos PDF (F14.7).

**El oráculo es la geometría conocida**: dos PDF que `reportlab` dibuja idénticos salvo por un
rectángulo en un sitio **que se sabe**; las regiones informadas tienen que cubrirlo y no tocar el
resto. Lo que se mira con PDFium es lo que se ve, no lo que el archivo dice.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pypdfium2
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from reportlab.pdfgen import canvas

from apps.documents import comparar, tarea

pytestmark = pytest.mark.django_db

A4 = (595.2756, 841.8898)
FIJO = (100, 200, 300, 400)  # x0, y0, x1, y1 en puntos, origen abajo a la izquierda
NUEVO = (400, 600, 450, 650)


def _pdf(carpeta: Path, nombre: str, rectangulos, paginas: int = 1, pagina=A4) -> Path:
    ruta = carpeta / nombre
    lienzo = canvas.Canvas(str(ruta), pagesize=pagina)
    for _ in range(paginas):
        for x0, y0, x1, y1 in rectangulos:
            lienzo.setFillGray(0)
            lienzo.rect(x0, y0, x1 - x0, y1 - y0, stroke=0, fill=1)
        lienzo.showPage()
    lienzo.save()
    return ruta


def _arriba(caja, alto=A4[1]):
    """La misma caja con la y desde arriba, que es como se informan las regiones."""
    x0, y0, x1, y1 = caja
    return x0, alto - y1, x1, alto - y0


def _cubre(region: comparar.Region, caja) -> bool:
    x0, y0, x1, y1 = caja
    return region.x0 <= x0 and region.y0 <= y0 and region.x1 >= x1 and region.y1 >= y1


def _toca(region: comparar.Region, caja) -> bool:
    x0, y0, x1, y1 = caja
    return not (region.x1 < x0 or region.x0 > x1 or region.y1 < y0 or region.y0 > y1)


class TestRegiones:
    def test_dos_pdf_iguales_no_difieren_en_nada(self, tmp_path):
        a = _pdf(tmp_path, "a.pdf", [FIJO])
        b = _pdf(tmp_path, "b.pdf", [FIJO])
        hecho = comparar.comparar(a, b)
        assert hecho.iguales and hecho.regiones == ()

    def test_la_region_cubre_lo_que_cambio_y_no_toca_lo_que_no(self, tmp_path):
        a = _pdf(tmp_path, "a.pdf", [FIJO])
        b = _pdf(tmp_path, "b.pdf", [FIJO, NUEVO])
        hecho = comparar.comparar(a, b)

        assert hecho.paginas_distintas == (1,)
        assert len(hecho.regiones) == 1
        region = hecho.regiones[0]
        assert _cubre(region, _arriba(NUEVO))
        assert not _toca(region, _arriba(FIJO))
        # Ni mucho más grande que lo que cambió: unas pocas celdas de holgura.
        assert (region.x1 - region.x0) < (NUEVO[2] - NUEVO[0]) + 40

    def test_dos_cambios_lejanos_son_dos_regiones(self, tmp_path):
        a = _pdf(tmp_path, "a.pdf", [FIJO])
        b = _pdf(tmp_path, "b.pdf", [FIJO, NUEVO, (50, 50, 90, 90)])
        assert len(comparar.comparar(a, b).regiones) == 2

    def test_lo_que_se_mueve_cuenta_en_los_dos_sitios(self, tmp_path):
        a = _pdf(tmp_path, "a.pdf", [FIJO])
        b = _pdf(tmp_path, "b.pdf", [(110, 200, 310, 400)])
        regiones = comparar.comparar(a, b).regiones
        assert regiones and all(r.x1 - r.x0 < 40 for r in regiones)

    def test_solo_se_informa_la_pagina_que_cambio(self, tmp_path):
        a = _pdf(tmp_path, "a.pdf", [FIJO], paginas=3)
        b = _pdf(tmp_path, "b.pdf", [FIJO], paginas=3)
        # La página 2 de «después» lleva el rectángulo nuevo.
        lienzo = canvas.Canvas(str(tmp_path / "b2.pdf"), pagesize=A4)
        for numero in (1, 2, 3):
            lienzo.rect(100, 200, 200, 200, stroke=0, fill=1)
            if numero == 2:
                lienzo.rect(400, 600, 50, 50, stroke=0, fill=1)
            lienzo.showPage()
        lienzo.save()
        assert comparar.comparar(a, tmp_path / "b2.pdf").paginas_distintas == (2,)
        assert b.exists()

    def test_una_pagina_que_sobra_se_informa_sin_superponer(self, tmp_path):
        a = _pdf(tmp_path, "a.pdf", [FIJO], paginas=1)
        b = _pdf(tmp_path, "b.pdf", [FIJO], paginas=2)
        hecho = comparar.comparar(a, b)
        assert (hecho.paginas_a, hecho.paginas_b) == (1, 2)
        assert hecho.paginas_distintas == (2,) and hecho.sin_superponer == (2,)

    def test_una_pagina_de_otro_tamano_se_informa_entera(self, tmp_path):
        a = _pdf(tmp_path, "a.pdf", [FIJO])
        b = _pdf(tmp_path, "b.pdf", [FIJO], pagina=(A4[1], A4[0]))
        hecho = comparar.comparar(a, b)
        assert hecho.sin_superponer == (1,)
        assert hecho.regiones[0].x1 == pytest.approx(A4[1], abs=0.5)


class TestElInforme:
    def _paginas(self, ruta: Path) -> int:
        documento = pypdfium2.PdfDocument(str(ruta))
        try:
            return len(documento)
        finally:
            documento.close()

    def test_solo_trae_las_paginas_que_difieren_y_se_abre_con_otro_lector(self, tmp_path):
        a = _pdf(tmp_path, "a.pdf", [FIJO], paginas=3)
        lienzo = canvas.Canvas(str(tmp_path / "b.pdf"), pagesize=A4)
        for numero in (1, 2, 3):
            lienzo.rect(100, 200, 200, 200, stroke=0, fill=1)
            if numero == 3:
                lienzo.rect(400, 600, 50, 50, stroke=0, fill=1)
            lienzo.showPage()
        lienzo.save()
        informe = tmp_path / "informe.pdf"
        hecho = comparar.comparar(a, tmp_path / "b.pdf", informe)

        assert hecho.paginas_distintas == (3,)
        assert self._paginas(informe) == 1

    def test_el_informe_marca_en_rojo_lo_que_cambio(self, tmp_path):
        a = _pdf(tmp_path, "a.pdf", [FIJO])
        b = _pdf(tmp_path, "b.pdf", [FIJO, NUEVO])
        informe = tmp_path / "informe.pdf"
        comparar.comparar(a, b, informe)

        documento = pypdfium2.PdfDocument(str(informe))
        try:
            hoja = documento[0]
            try:
                imagen = hoja.render(scale=1).to_pil().convert("RGB")
            finally:
                hoja.close()
        finally:
            documento.close()
        canales = imagen.tobytes()
        rojos = sum(
            1
            for i in range(0, len(canales), 3)
            if canales[i] > 180 and canales[i + 1] < 90 and canales[i + 2] < 90
        )
        assert rojos > 200

    def test_sin_diferencias_no_se_escribe_nada(self, tmp_path):
        a = _pdf(tmp_path, "a.pdf", [FIJO])
        b = _pdf(tmp_path, "b.pdf", [FIJO])
        informe = tmp_path / "informe.pdf"
        comparar.comparar(a, b, informe)
        assert not informe.exists()

    def test_los_originales_no_se_tocan(self, tmp_path):
        a = _pdf(tmp_path, "a.pdf", [FIJO])
        b = _pdf(tmp_path, "b.pdf", [FIJO, NUEVO])
        antes = [(hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in (a, b)]
        comparar.comparar(a, b, tmp_path / "informe.pdf")
        despues = [
            (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in (a, b)
        ]
        assert antes == despues

    def test_un_archivo_que_no_es_pdf_se_rechaza(self, tmp_path):
        basura = tmp_path / "x.pdf"
        basura.write_bytes(b"no es un pdf")
        with pytest.raises(comparar.ComposicionInvalida):
            comparar.comparar(basura, _pdf(tmp_path, "b.pdf", [FIJO]))


class TestEnLaTareaYLaPantalla:
    def test_la_tarea_escribe_el_informe(self, tmp_path):
        a = _pdf(tmp_path, "a.pdf", [FIJO])
        b = _pdf(tmp_path, "b.pdf", [FIJO, NUEVO])
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "comparar", {"entradas": [{"ruta": str(a)}, {"ruta": str(b)}], "opciones": {}}, parcial
        )
        assert "codigo" not in informe and informe["detalles"]["regiones"] == 1
        assert parcial.stat().st_size > 0

    def test_iguales_termina_sin_archivo_y_se_explica(self, tmp_path):
        a = _pdf(tmp_path, "a.pdf", [FIJO])
        b = _pdf(tmp_path, "b.pdf", [FIJO])
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "comparar", {"entradas": [{"ruta": str(a)}, {"ruta": str(b)}], "opciones": {}}, parcial
        )
        assert informe["desenlace"] == "sin-diferencias"
        assert not parcial.exists()

    def test_con_un_solo_pdf_falla_con_su_codigo(self, tmp_path):
        informe = tarea.ejecutar(
            "comparar",
            {"entradas": [{"ruta": str(_pdf(tmp_path, "a.pdf", [FIJO]))}], "opciones": {}},
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
        assert client.get(reverse("documents:comparar")).status_code == 302

    def test_la_pantalla_pide_los_dos_en_orden(self, sesion):
        cuerpo = sesion.get(reverse("documents:comparar")).content.decode()
        assert "versión de antes" in cuerpo and "versión de después" in cuerpo

    def test_comparar_encola_y_el_informe_se_abre(self, sesion, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        a = _pdf(tmp_path, "a.pdf", [FIJO])
        b = _pdf(tmp_path, "b.pdf", [FIJO, NUEVO])
        respuesta = sesion.post(reverse("documents:comparar"), {"ruta": str(a), "despues": str(b)})
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        assert self._abre(Path(trabajo.output_path))

    @staticmethod
    def _abre(ruta: Path) -> bool:
        documento = pypdfium2.PdfDocument(str(ruta))
        try:
            return len(documento) == 1
        finally:
            documento.close()
