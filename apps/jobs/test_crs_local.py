"""El corredor y las coordenadas locales. Ver `apps/dashboard/test_crs_local.py`.

Aquí se vigila lo que decide el corredor con un trabajo que **ya trae** la declaración: que
convierta avisando, que se niegue a reproyectar, y que sin la declaración la regla de siempre
siga en pie.
"""

import pytest
from django.contrib.auth import get_user_model

from apps.formats import crs as crs_mod
from apps.jobs import runner
from apps.jobs.models import ConversionJob, JobEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


class _Inspeccion:
    """Lo único que mira `_exigir_crs`: que el archivo no declara sistema."""

    crs = crs_mod.SIN_CRS
    #: La inspección real la trae siempre; `_exigir_crs` la mira para dejar pasar a GNSS.
    familia = ""


def _nube(usuario, **campos):
    return ConversionJob.objects.create(
        owner=usuario,
        source_path="/x/escaneo.las",
        source_name="escaneo.las",
        source_format_code="las",
        target_format_code="copc",
        **campos,
    )


class TestSinLaDeclaracion:
    def test_una_nube_sin_sistema_se_detiene(self, usuario):
        """La regla de siempre: sin declarar nada, no se adivina."""
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._exigir_crs(_nube(usuario), _Inspeccion())
        assert fallo.value.codigo == "crs-ausente"


class TestConLaDeclaracion:
    def test_convierte_y_avisa(self, usuario):
        job = _nube(usuario, source_crs_origin=crs_mod.LOCAL)
        runner._exigir_crs(job, _Inspeccion())  # no levanta
        avisos = JobEvent.objects.filter(job=job, level=JobEvent.AVISO)
        assert any("locales" in e.message for e in avisos)

    def test_pero_no_reproyecta(self, usuario):
        """Pasar de «local» a UTM no es una conversión, es georreferenciar, y sin puntos de
        control no hay de dónde partir."""
        job = _nube(usuario, source_crs_origin=crs_mod.LOCAL, target_crs_code="32719")
        with pytest.raises(runner.TrabajoFallido) as fallo:
            runner._exigir_crs(job, _Inspeccion())
        assert fallo.value.codigo == "crs-ausente"
        assert "georreferenciar" in fallo.value.mensaje

    def test_un_epsg_declarado_sigue_valiendo_como_antes(self, usuario):
        job = _nube(
            usuario,
            source_crs_origin=crs_mod.DECLARADO,
            source_crs_authority="EPSG",
            source_crs_code="32719",
        )
        runner._exigir_crs(job, _Inspeccion())


class TestElTipo:
    def test_local_no_cuenta_como_sistema_conocido(self):
        """No hay autoridad ni código: `conocido` sigue siendo falso, porque no hay sistema
        que conocer. Si no, todo el código que pregunta `conocido` lo trataría como un EPSG."""
        assert not crs_mod.LOCAL_DECLARADO.conocido
        assert crs_mod.LOCAL_DECLARADO.es_local
        assert not crs_mod.SIN_CRS.es_local

    def test_se_explica_con_su_procedencia(self):
        assert "locales" in crs_mod.LOCAL_DECLARADO.procedencia
