"""Qué se está haciendo, bajo la barra de avance (F18.4).

La barra decía el porcentaje y la etapa (una de cuatro). Una herramienta que sabe decir qué hace
(«Sincronizando las fotos») ahora lo dice, y las que no, siguen igual.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.engines import registry
from apps.engines.testing import MotorDeMentira
from apps.formats.tests.constructor import geotiff_minimo
from apps.jobs import runner
from apps.jobs.models import CONVERSION, ConversionJob

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario():
    return get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106


@pytest.fixture
def registro_limpio():
    guardado = registry.todos()
    registry.limpiar()
    yield
    registry.limpiar()
    for motor in guardado:
        registry.registrar(motor)


def _trabajo(usuario, tmp_path, **extra) -> ConversionJob:
    origen = tmp_path / "orto.tif"
    origen.write_bytes(geotiff_minimo(bandas=3))
    return ConversionJob.objects.create(
        owner=usuario,
        source_path=str(origen),
        source_name=origen.name,
        target_format_code="cog",
        output_path=str(tmp_path / "salida.tif"),
        **extra,
    )


class TestMarcarProgreso:
    def test_guarda_la_etiqueta(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path)
        job.marcar_progreso(CONVERSION, 0.5, "Sincronizando las fotos")
        job.refresh_from_db()
        assert job.progress_label == "Sincronizando las fotos" and job.progress_percent > 0

    def test_sin_etiqueta_deja_la_que_habia(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path)
        job.marcar_progreso(CONVERSION, 0.2, "Leyendo la trayectoria")
        job.marcar_progreso(CONVERSION, 0.4)
        job.refresh_from_db()
        assert job.progress_label == "Leyendo la trayectoria"

    def test_una_cadena_vacia_la_borra(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path)
        job.marcar_progreso(CONVERSION, 0.2, "algo")
        job.marcar_progreso(CONVERSION, 0.4, "")
        job.refresh_from_db()
        assert job.progress_label == ""

    def test_se_corta_a_lo_que_cabe_en_la_columna(self, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path)
        job.marcar_progreso(CONVERSION, 0.2, "x" * 500)
        job.refresh_from_db()
        assert len(job.progress_label) == 140


class TestElCorredor:
    def test_un_analizador_que_devuelve_fraccion_y_etiqueta_llega_a_la_fila(
        self, usuario, tmp_path, registro_limpio
    ):
        class MotorQueHabla(MotorDeMentira):
            def plan(self, trabajo):
                plan = super().plan(trabajo)

                def analizar(linea: str):
                    numeros = [t for t in linea.replace(".", " ").split() if t.isdigit()]
                    if not numeros:
                        return None
                    return (int(numeros[-1]) / 100, f"Paso al {numeros[-1]} %")

                object.__setattr__(plan, "analizador_de_progreso", analizar)
                return plan

        registry.registrar(MotorQueHabla(escribe="listo", pasos=4))
        job = _trabajo(usuario, tmp_path)
        runner.ejecutar(job)
        job.refresh_from_db()
        assert job.status == "done"
        assert job.progress_label.startswith("Paso al ")

    def test_un_analizador_de_siempre_no_toca_la_etiqueta(self, usuario, tmp_path, registro_limpio):
        registry.registrar(MotorDeMentira(escribe="listo", pasos=4))
        job = _trabajo(usuario, tmp_path)
        runner.ejecutar(job)
        job.refresh_from_db()
        assert job.status == "done" and job.progress_label == ""


class TestLaFicha:
    @pytest.fixture
    def sesion(self, client, usuario):
        client.force_login(usuario)
        return client

    def test_se_ve_mientras_corre(self, sesion, usuario, tmp_path):
        job = _trabajo(
            usuario, tmp_path, status="running", progress_stage="conversion", progress_percent=55
        )
        job.progress_label = "Sincronizando las fotos"
        job.save(update_fields=["progress_label"])
        cuerpo = sesion.get(reverse("jobs:ficha", args=[job.pk])).content.decode()
        assert "55 %" in cuerpo and "Sincronizando las fotos" in cuerpo

    def test_no_se_ve_si_el_trabajo_ya_termino(self, sesion, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, status="done", progress_percent=100)
        job.progress_label = "Listo"
        job.save(update_fields=["progress_label"])
        cuerpo = sesion.get(reverse("jobs:ficha", args=[job.pk])).content.decode()
        assert "avance-etiqueta" not in cuerpo

    def test_el_texto_va_escapado(self, sesion, usuario, tmp_path):
        job = _trabajo(usuario, tmp_path, status="running", progress_stage="conversion")
        job.progress_label = "<script>alert(1)</script>"
        job.save(update_fields=["progress_label"])
        cuerpo = sesion.get(reverse("jobs:ficha", args=[job.pk])).content.decode()
        assert "<script>alert(1)</script>" not in cuerpo and "&lt;script&gt;" in cuerpo
