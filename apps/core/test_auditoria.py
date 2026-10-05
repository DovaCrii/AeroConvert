"""Los hallazgos de integridad de la auditoría de seguridad del 2026-10-05 (F11.9).

Cada prueba reproduce un hallazgo y falla sin su arreglo. Los identificadores (A-02, C-01...)
son los del informe de la auditoría.
"""

from __future__ import annotations

import math
import time
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.documents import dividir
from apps.documents.composicion import ComposicionInvalida
from apps.formats import deteccion, las, tiff
from apps.jobs import runner
from apps.jobs.models import ConversionJob, EntradaDeTrabajo
from apps.presets.models import ConversionPreset

pytestmark = pytest.mark.django_db


@pytest.fixture
def entorno(tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    settings.MEDIA_ROOT = str(tmp_path / "media")
    return tmp_path


@pytest.fixture
def ana(entorno):
    return get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106


@pytest.fixture
def sesion(client, ana):
    client.force_login(ana)
    return client


class TestC06RangosSinTope:
    def test_el_maximo_pasa_y_uno_mas_no(self):
        justo = ",".join(["1"] * dividir.MAXIMO_TROZOS)
        assert len(dividir.analizar_rangos(justo, 5)) == dividir.MAXIMO_TROZOS
        with pytest.raises(ComposicionInvalida, match="demasiados trozos"):
            dividir.analizar_rangos(justo + ",1", 5)

    def test_cien_mil_rangos_se_rechazan_enseguida(self):
        """Antes se analizaban todos y los repetidos se contaban en cuadrático."""
        texto = ",".join(["1-1"] * 100_000)
        empezo = time.perf_counter()
        with pytest.raises(ComposicionInvalida):
            dividir.analizar_rangos(texto, 5)
        assert time.perf_counter() - empezo < 2


class TestA02PreajusteAjeno:
    def test_el_slug_de_otra_persona_no_se_aplica(self, sesion, entorno):
        otra = get_user_model().objects.create_user("beto", password="y" * 20)  # nosec B106
        ajeno = ConversionPreset.objects.create(
            slug="cliente-secreto",
            nombre="Entrega para el cliente secreto",
            target_format_code="geotiff",
            owner=otra,
        )
        origen = entorno / "orto.tif"
        origen.write_bytes(b"II*\x00" + bytes(64))
        sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(origen), "preajuste": ajeno.slug},
        )
        ajeno.refresh_from_db()
        assert ajeno.veces_usado == 0, "no se suma uso en la fila de otra persona"
        assert not ConversionJob.objects.exists()


class TestC01NoPisarElOriginal:
    def test_markdown_a_pdf_rechaza_un_pdf_de_entrada(self, sesion, entorno):
        original = entorno / "acta.pdf"
        original.write_bytes(b"%PDF-1.4 firmado")
        antes = (original.read_bytes(), original.stat().st_mtime_ns)
        sesion.post(reverse("documents:de_markdown"), {"ruta": str(original)})
        assert not ConversionJob.objects.exists()
        assert (original.read_bytes(), original.stat().st_mtime_ns) == antes

    def test_un_md_si_se_acepta(self, sesion, entorno):
        texto = entorno / "acta.md"
        texto.write_text("# Acta\n", encoding="utf-8")
        sesion.post(reverse("documents:de_markdown"), {"ruta": str(texto)})
        assert ConversionJob.objects.count() == 1

    def test_el_destino_nunca_es_el_propio_original(self, ana, entorno):
        """La red de seguridad del corredor, además de la de la pantalla."""
        original = entorno / "acta.pdf"
        original.write_bytes(b"%PDF-1.4 firmado")
        trabajo = ConversionJob.objects.create(
            owner=ana,
            source_path=str(original),
            source_name="acta.pdf",
            target_format_code="pdf",
            output_path=str(original),
        )
        EntradaDeTrabajo.objects.create(job=trabajo, ruta=str(original), orden=0)
        libre = runner._destino_libre(trabajo, original)
        assert libre != original
        assert libre.name == "acta_2.pdf"


class TestD04EpsgNoNumerico:
    @pytest.mark.parametrize("valor", ["abc", "EPSG:no-es", "32719.0", "  "])
    def test_un_epsgcode_ilegible_avisa_y_no_revienta(self, entorno, valor):
        xml = entorno / "obra.xml"
        xml.write_text(
            '<?xml version="1.0"?><LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" '
            'version="1.2"><CoordinateSystem epsgCode="' + valor + '"/><Surfaces/></LandXML>',
            encoding="utf-8",
        )
        inspeccion = deteccion.inspeccionar(xml)
        assert inspeccion.codigo_formato == "landxml"
        assert not inspeccion.crs.conocido
        if valor.strip():
            assert any("no es un número de EPSG" in aviso for aviso in inspeccion.avisos)

    def test_epsg_con_prefijo_se_entiende(self, entorno):
        xml = entorno / "obra.xml"
        xml.write_text(
            '<?xml version="1.0"?><LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" '
            'version="1.2"><CoordinateSystem epsgCode="EPSG:32719"/><Surfaces/></LandXML>',
            encoding="utf-8",
        )
        assert deteccion.inspeccionar(xml).crs.codigo == "32719"


class TestD05ValoresNoFinitos:
    def test_un_overflow_al_leer_el_tiff_no_rompe_la_inspeccion(self, entorno, monkeypatch):
        def explota(_ruta):
            raise OverflowError("cannot convert float infinity to integer")

        monkeypatch.setattr(tiff, "leer_cabecera", explota)
        archivo = entorno / "x.tif"
        archivo.write_bytes(b"II*\x00" + bytes(64))
        inspeccion = deteccion.inspeccionar(archivo)
        assert any("no se pudo leer" in aviso for aviso in inspeccion.avisos)

    @pytest.mark.parametrize("valor", [math.inf, -math.inf, math.nan])
    def test_un_bbox_no_finito_no_levanta(self, valor):
        cabecera = SimpleNamespace(
            minimo=(valor, 0.0, 0.0), maximo=(1.0, 1.0, 1.0), escala=(0.01, 0.01, 0.01)
        )
        propiedad = las.CabeceraLas.precision_suficiente_para_float32
        assert propiedad.fget(cabecera) is False
