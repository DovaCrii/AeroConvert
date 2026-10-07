"""Rellenar y aplanar formularios PDF (F14.3).

**El oráculo es `pikepdf` y PDFium**, no `pypdf`, que es quien escribe: el formulario de partida lo
arma `pikepdf` con un campo de texto y una casilla; lo rellenado se lee con `pikepdf` y lo aplanado
se comprueba con `pikepdf` (ni `AcroForm` ni widgets) y con PDFium (el texto está en la página).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pikepdf
import pypdfium2
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from pikepdf import Array, Dictionary, Name, String

from apps.documents import formularios, tarea

pytestmark = pytest.mark.django_db


def _formulario(carpeta: Path, nombre: str = "form.pdf") -> Path:
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(300, 300))
    pagina = pdf.pages[0]
    helv = pdf.make_indirect(
        Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica)
    )
    texto = pdf.make_indirect(
        Dictionary(
            FT=Name.Tx,
            T=String("nombre"),
            V=String(""),
            Rect=Array([50, 200, 250, 222]),
            Subtype=Name.Widget,
            Type=Name.Annot,
            F=4,
            DA=String("/Helv 12 Tf 0 g"),
            P=pagina.obj,
        )
    )
    si = pdf.make_stream(b"0 0 20 20 re S")
    si.Type, si.Subtype, si.BBox = Name.XObject, Name.Form, Array([0, 0, 20, 20])
    no = pdf.make_stream(b"")
    no.Type, no.Subtype, no.BBox = Name.XObject, Name.Form, Array([0, 0, 20, 20])
    casilla = pdf.make_indirect(
        Dictionary(
            FT=Name.Btn,
            T=String("acepta"),
            V=Name.Off,
            AS=Name.Off,
            Rect=Array([50, 150, 70, 170]),
            Subtype=Name.Widget,
            Type=Name.Annot,
            F=4,
            AP=Dictionary(N=Dictionary(Yes=si, Off=no)),
            P=pagina.obj,
        )
    )
    pagina.Annots = Array([texto, casilla])
    pdf.Root.AcroForm = Dictionary(
        Fields=Array([texto, casilla]),
        DA=String("/Helv 12 Tf 0 g"),
        DR=Dictionary(Font=Dictionary(Helv=helv)),
    )
    ruta = carpeta / nombre
    pdf.save(ruta)
    return ruta


def _valores_con_pikepdf(ruta: Path) -> dict[str, str]:
    with pikepdf.open(ruta) as p:
        return {str(c.T): str(c.V) for c in p.Root.AcroForm.Fields}


def _texto_de_pdfium(ruta: Path) -> str:
    documento = pypdfium2.PdfDocument(str(ruta))
    try:
        pagina = documento[0]
        try:
            return pagina.get_textpage().get_text_bounded()
        finally:
            pagina.close()
    finally:
        documento.close()


def _tinta_en_el_campo(ruta: Path) -> int:
    """Píxeles oscuros dentro del campo «nombre», con los formularios dibujados por PDFium.

    Es lo que ve quien abre el PDF: el diccionario puede decir una cosa y la página otra."""
    documento = pypdfium2.PdfDocument(str(ruta))
    try:
        documento.init_forms()
        pagina = documento[0]
        try:
            imagen = pagina.render(scale=1, may_draw_forms=True).to_pil().convert("L")
        finally:
            pagina.close()
    finally:
        documento.close()
    # El campo es x 50–250, y 200–222 en puntos; la imagen cuenta la y desde arriba (alto 300).
    recorte = imagen.crop((50, 300 - 222, 250, 300 - 200))
    return recorte.point(lambda p: 255 if p < 128 else 0).histogram()[255]


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


class TestListar:
    def test_distingue_el_texto_de_la_casilla(self, tmp_path):
        campos = {c.nombre: c for c in formularios.listar(_formulario(tmp_path))}
        assert campos["nombre"].tipo == formularios.TEXTO and campos["nombre"].editable
        assert campos["acepta"].tipo == formularios.CASILLA
        assert campos["acepta"].marcada == "/Yes" and not campos["acepta"].esta_marcada

    def test_un_pdf_sin_formulario_da_lista_vacia(self, tmp_path):
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(100, 100))
        ruta = tmp_path / "plano.pdf"
        pdf.save(ruta)
        assert formularios.listar(ruta) == []
        with pytest.raises(formularios.ComposicionInvalida, match="no tiene campos"):
            formularios.rellenar(ruta, tmp_path / "x.pdf", {"a": "b"})


class TestRellenar:
    def test_el_texto_y_la_casilla_se_leen_con_otro_lector(self, tmp_path):
        origen = _formulario(tmp_path)
        destino = tmp_path / "relleno.pdf"
        puestos = formularios.rellenar(origen, destino, {"nombre": "Ana Pérez", "acepta": True})

        assert puestos == 2
        valores = _valores_con_pikepdf(destino)
        assert valores["nombre"] == "Ana Pérez"
        assert valores["acepta"] == "/Yes"
        # Y el valor se ve en la página, no solo en el diccionario: el campo ya no está en blanco.
        assert _tinta_en_el_campo(origen) == 0
        assert _tinta_en_el_campo(destino) > 20

    def test_un_campo_que_no_existe_se_rechaza(self, tmp_path):
        with pytest.raises(formularios.ComposicionInvalida, match="no tiene un campo"):
            formularios.rellenar(_formulario(tmp_path), tmp_path / "x.pdf", {"otro": "1"})

    def test_el_original_no_se_toca(self, tmp_path):
        origen = _formulario(tmp_path)
        antes = _huella(origen)
        formularios.rellenar(origen, tmp_path / "relleno.pdf", {"nombre": "Ana"})
        assert _huella(origen) == antes


class TestAplanar:
    def test_sin_campos_ni_acroform_y_con_el_texto_en_la_pagina(self, tmp_path):
        origen = _formulario(tmp_path)
        destino = tmp_path / "plano.pdf"
        formularios.rellenar(origen, destino, {"nombre": "Ana Pérez"}, aplanar=True)

        with pikepdf.open(destino) as p:
            assert "/AcroForm" not in p.Root
            anotaciones = p.pages[0].get("/Annots", [])
            assert not [a for a in anotaciones if a.get("/Subtype") == Name.Widget]
            assert len(p.pages) == 1
        assert "Ana Pérez" in _texto_de_pdfium(destino)
        assert formularios.listar(destino) == []

    def test_aplanar_sin_cambios_tambien_quita_los_campos(self, tmp_path):
        destino = tmp_path / "plano.pdf"
        formularios.rellenar(_formulario(tmp_path), destino, {}, aplanar=True)
        with pikepdf.open(destino) as p:
            assert "/AcroForm" not in p.Root


class TestEnLaTareaYLaPantalla:
    def test_la_tarea_rellena(self, tmp_path):
        origen = _formulario(tmp_path)
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "formularios",
            {
                "entradas": [{"ruta": str(origen)}],
                "opciones": {"valores": {"nombre": "Luis"}, "aplanar": False},
            },
            parcial,
        )
        assert "codigo" not in informe and informe["detalles"]["campos"] == 1
        assert _valores_con_pikepdf(parcial)["nombre"] == "Luis"

    @pytest.fixture
    def sesion(self, client, tmp_path, settings):
        settings.RAICES_PERMITIDAS = str(tmp_path)
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def test_pide_sesion(self, client):
        assert client.get(reverse("documents:formularios")).status_code == 302

    def test_mirar_lista_los_campos(self, sesion, tmp_path):
        cuerpo = sesion.post(
            reverse("documents:formularios"),
            {"ruta": str(_formulario(tmp_path)), "accion": "mirar"},
        ).content.decode()
        assert "nombre" in cuerpo and "acepta" in cuerpo and 'value="rellenar"' in cuerpo

    def test_un_pdf_sin_formulario_se_dice(self, sesion, tmp_path):
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(100, 100))
        ruta = tmp_path / "plano.pdf"
        pdf.save(ruta)
        cuerpo = sesion.post(
            reverse("documents:formularios"), {"ruta": str(ruta), "accion": "mirar"}
        ).content.decode()
        assert "no tiene campos de formulario" in cuerpo

    def test_rellenar_sin_cambios_ni_aplanar_avisa(self, sesion, tmp_path):
        respuesta = sesion.post(
            reverse("documents:formularios"),
            {
                "ruta": str(_formulario(tmp_path)),
                "accion": "rellenar",
                "visto_nombre": "1",
                "campo_nombre": "",
                "visto_acepta": "1",
            },
        )
        assert respuesta.status_code == 200
        assert "No cambió ningún campo" in respuesta.content.decode()

    def test_rellenar_aplanado_encola_y_el_resultado_es_plano(self, sesion, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        respuesta = sesion.post(
            reverse("documents:formularios"),
            {
                "ruta": str(_formulario(tmp_path)),
                "accion": "rellenar",
                "aplanar": "si",
                "visto_nombre": "1",
                "campo_nombre": "Marta Soto",
                "visto_acepta": "1",
                "campo_acepta": "si",
            },
        )
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        with pikepdf.open(trabajo.output_path) as p:
            assert "/AcroForm" not in p.Root
        assert "Marta Soto" in _texto_de_pdfium(Path(trabajo.output_path))
