"""El informe de verificación en PDF (F16.3).

Dos lectores que no lo escribieron (`reportlab`): **PDFium** lo renderiza y **pypdf** tiene que
encontrar cada `sha256` en el texto, entera y sin cortes. Lo que el informe no debe llevar
—contraseñas, términos de tachado— se busca en los bytes del PDF.
"""

from __future__ import annotations

import io
from datetime import timedelta

import pypdf
import pypdfium2
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.jobs import informe
from apps.jobs.models import ConversionJob, EntradaDeTrabajo, JobEvent

pytestmark = pytest.mark.django_db

SHA_ORIGEN = "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801"
SHA_SALIDA = "0b9e8d7c6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa9988776655"


@pytest.fixture
def usuario():
    return get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106


def _trabajo(usuario, tmp_path, **extra) -> ConversionJob:
    ahora = timezone.now()
    campos = {
        "owner": usuario,
        "source_path": str(tmp_path / "orto.tif"),
        "source_name": "orto_bhp.tif",
        "source_size_bytes": 123_456_789,
        "source_sha256": SHA_ORIGEN,
        "source_format_code": "geotiff",
        "source_format_confidence": "alta",
        "source_crs_authority": "EPSG",
        "source_crs_code": "32719",
        "source_crs_origin": "archivo",
        "target_format_code": "cog",
        "engine_id": "gdal-raster",
        "engine_version": "GDAL 3.12.4",
        "output_path": str(tmp_path / "orto_bhp.cog.tif"),
        "output_size_bytes": 98_765_432,
        "output_sha256": SHA_SALIDA,
        "status": "done",
        "queued_at": ahora - timedelta(minutes=5),
        "started_at": ahora - timedelta(minutes=4),
        "finished_at": ahora - timedelta(minutes=2),
        "verified_at": ahora - timedelta(minutes=2),
        "verification": {"epsg": "32719", "ancho_px": 14526, "alto_px": 14443, "bandas": 4},
        "options": {"compresion": "DEFLATE", "tamano_tesela": "512"},
    }
    campos.update(extra)
    return ConversionJob.objects.create(**campos)


def _texto_pypdf(datos: bytes) -> str:
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(datos)).pages)


def _texto_pdfium(datos: bytes) -> str:
    documento = pypdfium2.PdfDocument(datos)
    return "\n".join(documento[i].get_textpage().get_text_bounded() for i in range(len(documento)))


class TestContenido:
    def test_pdfium_lo_abre_y_lo_pinta(self, usuario, tmp_path):
        datos = informe.construir(_trabajo(usuario, tmp_path))
        documento = pypdfium2.PdfDocument(datos)
        assert len(documento) >= 1
        imagen = documento[0].render(scale=1).to_pil().convert("L")
        assert imagen.point(lambda v: 255 if v < 200 else 0).getbbox() is not None

    def test_pypdf_encuentra_cada_sha256_entero(self, usuario, tmp_path):
        texto = _texto_pypdf(informe.construir(_trabajo(usuario, tmp_path)))
        assert SHA_ORIGEN in texto and SHA_SALIDA in texto

    def test_pdfium_tambien_encuentra_las_huellas(self, usuario, tmp_path):
        texto = _texto_pdfium(informe.construir(_trabajo(usuario, tmp_path)))
        assert SHA_ORIGEN in texto and SHA_SALIDA in texto

    def test_dice_el_programa_el_crs_y_lo_que_se_midio(self, usuario, tmp_path):
        texto = _texto_pypdf(informe.construir(_trabajo(usuario, tmp_path)))
        for esperado in ("orto_bhp.tif", "GDAL 3.12.4", "EPSG:32719", "14526", "14443", "DEFLATE"):
            assert esperado in texto, esperado
        assert "geotiff a cog" in texto and "Terminado" in texto

    def test_un_crs_sin_declarar_se_dice_asi(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, source_crs_code="", source_crs_authority="")
        assert "no declarado" in _texto_pypdf(informe.construir(job))

    def test_lo_que_no_se_calculo_no_se_inventa(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, output_sha256="", verification={})
        texto = _texto_pypdf(informe.construir(job))
        assert "no calculado" in texto
        assert "no guardó mediciones" in texto

    def test_un_trabajo_fallido_dice_su_motivo_y_no_promete_entrega(self, usuario, tmp_path):
        job = _trabajo(
            usuario,
            tmp_path,
            status="error",
            reason_code="crs-ausente",
            reason_detail="El archivo no declara su sistema de coordenadas.",
            output_path="",
            output_sha256="",
        )
        texto = _texto_pypdf(informe.construir(job))
        assert "Falló" in texto and "crs-ausente" in texto
        assert "no hay entrega que acompañe" in texto
        assert "comprobó al terminar" not in texto

    def test_un_original_modificado_se_cuenta_tal_cual_y_no_promete_nada(self, usuario, tmp_path):
        job = _trabajo(
            usuario,
            tmp_path,
            status="error",
            reason_code="original-modificado",
            reason_detail="El archivo de origen a.tif cambió durante el trabajo.",
            output_path="",
            output_sha256="",
        )
        texto = _texto_pypdf(informe.construir(job))
        assert "original-modificado" in texto
        assert "El original cambió mientras se trabajaba" in texto
        assert "la salida no se entregó" in texto
        assert "comprobó al terminar" not in texto

    def test_los_avisos_del_trabajo_salen(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path)
        JobEvent.objects.create(job=job, sequence=1, level=JobEvent.AVISO, message="Sin banda alfa")
        JobEvent.objects.create(job=job, sequence=2, level="info", message="Todo bien aquí")
        texto = _texto_pypdf(informe.construir(job))
        assert "Sin banda alfa" in texto and "Todo bien aquí" not in texto

    def test_varias_entradas_listan_cada_huella(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, target_format_code="pdf")
        otra = "f" * 64
        for orden, (nombre, sha) in enumerate((("a.pdf", SHA_ORIGEN), ("b.pdf", otra))):
            EntradaDeTrabajo.objects.create(
                job=job,
                orden=orden,
                ruta=str(tmp_path / nombre),
                nombre=nombre,
                sha256=sha,
                bytes=10,
            )
        texto = _texto_pypdf(informe.construir(job))
        assert "Entrada 1" in texto and "Entrada 2" in texto and otra in texto

    def test_un_nombre_con_caracteres_raros_no_rompe_el_informe(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, source_name="plano <A&B> ñandú 🛰.tif")
        datos = informe.construir(job)
        assert len(pypdfium2.PdfDocument(datos)) >= 1
        assert "ñandú" in _texto_pypdf(datos)


class TestLoQueNoDebeLlevar:
    def test_las_opciones_secretas_no_salen(self, usuario, tmp_path):
        job = _trabajo(
            usuario,
            tmp_path,
            options={
                "contrasena": "S3cr3to-no-debe-salir",
                "pide_contrasena": True,
                "terminos": ["cliente-confidencial"],
                "valores": {"titulo": "dato-del-cliente"},
                "compresion": "LZW",
            },
        )
        datos = informe.construir(job)
        texto = _texto_pypdf(datos)
        for oculto in ("S3cr3to", "cliente-confidencial", "dato-del-cliente"):
            assert oculto not in texto and oculto.encode() not in datos
        assert "LZW" in texto

    def test_las_opciones_que_no_son_escalares_se_omiten(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, options={"lista": [1, 2], "compresion": "DEFLATE"})
        assert "lista" not in _texto_pypdf(informe.construir(job))


class TestPantalla:
    @pytest.fixture
    def sesion(self, client, usuario):
        client.force_login(usuario)
        return client

    def test_sin_sesion_redirige(self, client, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path)
        assert client.get(reverse("jobs:informe", args=[job.pk])).status_code == 302

    def test_baja_un_pdf_con_las_huellas(self, sesion, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path)
        respuesta = sesion.get(reverse("jobs:informe", args=[job.pk]))
        assert respuesta.status_code == 200 and respuesta["Content-Type"] == "application/pdf"
        assert "informe_orto_bhp.pdf" in respuesta["Content-Disposition"]
        assert "no-store" in respuesta["Cache-Control"]
        assert SHA_SALIDA in _texto_pypdf(respuesta.content)

    def test_el_trabajo_de_otra_persona_es_un_404(self, sesion, tmp_path):
        ajeno = get_user_model().objects.create_user("beto", password="x" * 20)  # nosec B106
        job = _trabajo(ajeno, tmp_path)
        assert sesion.get(reverse("jobs:informe", args=[job.pk])).status_code == 404

    def test_un_trabajo_sin_terminar_no_da_informe(self, sesion, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, status="queued", output_path="", output_sha256="")
        respuesta = sesion.get(reverse("jobs:informe", args=[job.pk]))
        assert respuesta.status_code == 302 and str(job.pk) in respuesta["Location"]

    def test_la_ficha_ofrece_el_informe(self, sesion, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path)
        cuerpo = sesion.get(reverse("jobs:ficha", args=[job.pk])).content.decode()
        assert reverse("jobs:informe", args=[job.pk]) in cuerpo and "Informe en PDF" in cuerpo
