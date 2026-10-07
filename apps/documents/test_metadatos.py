"""Ver, editar y limpiar los metadatos de un PDF (F14.2).

**El oráculo es `pikepdf` (qpdf)**, que no comparte código con `pypdf`, el que escribe: el PDF de
partida lo arma `pikepdf` con `Info` y XMP, y lo que sale se reabre con `pikepdf` para comprobar
que de verdad no queda ni `/Author` ni el paquete `/Metadata`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pikepdf
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.documents import metadatos, tarea

pytestmark = pytest.mark.django_db


def _pdf_con_datos(carpeta: Path, nombre: str = "plano.pdf") -> Path:
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.add_blank_page(page_size=(200, 200))
    pdf.docinfo["/Title"] = "Plano reservado"
    pdf.docinfo["/Author"] = "Ana Pérez"
    pdf.docinfo["/Creator"] = "AutoCAD 2024"
    pdf.docinfo["/Subject"] = "Cliente X"
    # Con `update_docinfo=False`: por omisión pikepdf reescribe el Info desde el XMP y se lo come.
    with pdf.open_metadata(update_docinfo=False) as xmp:
        xmp["dc:title"] = "Plano reservado"
        xmp["dc:creator"] = ["Ana Pérez"]
    ruta = carpeta / nombre
    pdf.save(ruta)
    return ruta


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


class TestLeer:
    def test_lee_los_campos_y_el_xmp(self, tmp_path):
        datos = metadatos.leer(_pdf_con_datos(tmp_path))
        assert datos.campos["autor"] == "Ana Pérez"
        assert datos.campos["titulo"] == "Plano reservado"
        assert datos.tiene_xmp is True
        assert not datos.vacio

    def test_un_pdf_sin_nada_se_dice_vacio(self, tmp_path):
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(100, 100))
        ruta = tmp_path / "limpio.pdf"
        pdf.save(ruta)
        # pikepdf pone `/Producer`: se quita para tener un PDF de verdad sin datos.
        with pikepdf.open(ruta, allow_overwriting_input=True) as p:
            for clave in list(p.docinfo.keys()):
                del p.docinfo[clave]
            p.save(ruta)
        assert metadatos.leer(ruta).vacio

    def test_un_pdf_cifrado_se_rechaza(self, tmp_path):
        ruta = tmp_path / "cifrado.pdf"
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(100, 100))
        pdf.save(ruta, encryption=pikepdf.Encryption(user="u", owner="o"))
        with pytest.raises(metadatos.ComposicionInvalida, match="contraseña"):
            metadatos.leer(ruta)


class TestLimpiar:
    def test_no_queda_ni_info_ni_xmp(self, tmp_path):
        origen = _pdf_con_datos(tmp_path)
        destino = tmp_path / "limpio.pdf"
        paginas = metadatos.escribir(origen, destino, limpiar=True)

        assert paginas == 2
        with pikepdf.open(destino) as p:
            assert {str(k) for k in p.docinfo.keys()} == set()
            assert "/Metadata" not in p.Root
            assert len(p.pages) == 2
        # Y ningún rastro del nombre en los bytes del archivo.
        assert b"Ana" not in destino.read_bytes()
        assert b"AutoCAD" not in destino.read_bytes()

    def test_el_original_no_se_toca(self, tmp_path):
        origen = _pdf_con_datos(tmp_path)
        antes = _huella(origen)
        metadatos.escribir(origen, tmp_path / "limpio.pdf", limpiar=True)
        assert _huella(origen) == antes


class TestEditar:
    def test_cambia_lo_pedido_y_deja_el_resto(self, tmp_path):
        origen = _pdf_con_datos(tmp_path)
        destino = tmp_path / "nuevo.pdf"
        metadatos.escribir(origen, destino, cambios={"titulo": "Plano de obra", "autor": ""})

        with pikepdf.open(destino) as p:
            assert str(p.docinfo["/Title"]) == "Plano de obra"
            assert str(p.docinfo["/Author"]) == ""
            assert str(p.docinfo["/Subject"]) == "Cliente X"

    def test_retira_el_xmp_que_diria_lo_de_antes(self, tmp_path):
        origen = _pdf_con_datos(tmp_path)
        destino = tmp_path / "nuevo.pdf"
        metadatos.escribir(origen, destino, cambios={"titulo": "Otro"})
        with pikepdf.open(destino) as p:
            assert "/Metadata" not in p.Root

    def test_un_campo_que_no_se_edita_se_rechaza(self, tmp_path):
        with pytest.raises(metadatos.ComposicionInvalida):
            metadatos.escribir(
                _pdf_con_datos(tmp_path), tmp_path / "x.pdf", cambios={"fechas": "hoy"}
            )


class TestEnLaTareaYLaPantalla:
    def test_la_tarea_limpia(self, tmp_path):
        origen = _pdf_con_datos(tmp_path)
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "metadatos",
            {"entradas": [{"ruta": str(origen)}], "opciones": {"limpiar": True}},
            parcial,
        )
        assert "codigo" not in informe and informe["detalles"]["limpiado"] is True
        with pikepdf.open(parcial) as p:
            assert "/Author" not in p.docinfo

    @pytest.fixture
    def sesion(self, client, tmp_path, settings):
        settings.RAICES_PERMITIDAS = str(tmp_path)
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def test_pide_sesion(self, client):
        assert client.get(reverse("documents:metadatos")).status_code == 302

    def test_mirar_enseña_lo_que_lleva(self, sesion, tmp_path):
        origen = _pdf_con_datos(tmp_path)
        cuerpo = sesion.post(
            reverse("documents:metadatos"), {"ruta": str(origen), "accion": "mirar"}
        ).content.decode()
        assert "Ana Pérez" in cuerpo and "Limpiar todo" in cuerpo

    def test_guardar_sin_cambios_avisa_y_no_encola(self, sesion, tmp_path):
        origen = _pdf_con_datos(tmp_path)
        respuesta = sesion.post(
            reverse("documents:metadatos"), {"ruta": str(origen), "accion": "guardar"}
        )
        assert respuesta.status_code == 200
        assert "No cambió ningún campo" in respuesta.content.decode()

    def test_limpiar_encola_y_el_resultado_no_trae_autor(self, sesion, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        origen = _pdf_con_datos(tmp_path)
        respuesta = sesion.post(
            reverse("documents:metadatos"), {"ruta": str(origen), "accion": "limpiar"}
        )
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        with pikepdf.open(trabajo.output_path) as p:
            assert "/Author" not in p.docinfo and "/Metadata" not in p.Root
