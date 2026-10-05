"""Coordenadas locales: una nube de escáner sin GNSS no tiene EPSG, y eso es una respuesta.

## Por qué existe

La regla de la casa es que el CRS no se adivina: sin él, una conversión que lo necesita se
detiene y se pregunta. Para una nube eso era absoluto, y dejaba sin salida a quien trae un
levantamiento de escáner en el sistema de la estación, con el origen en 0 — no hay EPSG que
poner, y obligar a escribir uno es exactamente lo que la regla prohíbe.

Lo que se vigila aquí es que esa salida **no se convierta en un hueco**:

- solo existe si una persona la marca (desmarcada por omisión);
- solo vale para nubes;
- no vale junto a un EPSG, porque las dos a la vez son una contradicción;
- queda en la bitácora con el nombre de quien la declaró;
- y unas coordenadas locales **no se reproyectan**.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.engines import sondas
from apps.engines.base import Disponibilidad
from apps.formats.tests.constructor import las_minimo
from apps.jobs.models import ConversionJob, JobEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    client.force_login(
        get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    )
    return client


@pytest.fixture
def con_pdal(monkeypatch):
    """Finge PDAL: el gate corre sin él, y aquí se prueba el formulario, no la herramienta."""
    monkeypatch.setattr(sondas, "sondar_pdal", lambda: Disponibilidad.si("PDAL de mentira"))


@pytest.fixture
def nube_sin_crs(tmp_path):
    ruta = tmp_path / "escaneo estacion 3.las"
    ruta.write_bytes(las_minimo(epsg=None))
    return ruta


@pytest.fixture
def nube_con_crs(tmp_path):
    ruta = tmp_path / "vuelo.las"
    ruta.write_bytes(las_minimo(epsg=32719))
    return ruta


def _encolar(sesion, ruta, **extra):
    return sesion.post(
        reverse("dashboard:encolar"), {"ruta": str(ruta), "formato": "copc", **extra}
    )


class TestLaCasilla:
    def _ficha(self, sesion, ruta):
        return sesion.get(reverse("dashboard:inspeccionar"), {"ruta": str(ruta)}).content.decode()

    def test_sale_en_una_nube_sin_sistema(self, sesion, nube_sin_crs):
        assert 'name="crs_local"' in self._ficha(sesion, nube_sin_crs)

    def test_y_desmarcada_por_omision(self, sesion, nube_sin_crs):
        """Marcarla es decir algo. Una casilla que ya viene marcada sería adivinar."""
        cuerpo = self._ficha(sesion, nube_sin_crs)
        casilla = cuerpo[cuerpo.index('name="crs_local"') :].split(">", 1)[0]
        assert "checked" not in casilla

    def test_no_sale_si_la_nube_ya_trae_su_sistema(self, sesion, nube_con_crs):
        assert 'name="crs_local"' not in self._ficha(sesion, nube_con_crs)

    def test_no_sale_en_una_libreta_de_puntos(self, sesion, tmp_path):
        """Una libreta **no es más que coordenadas**: sin EPSG no dicen dónde está nada."""
        libreta = tmp_path / "puntos.csv"
        libreta.write_text("P1,7318729.036,495279.406,3042.641,pr\n" * 5, encoding="utf-8")
        assert 'name="crs_local"' not in self._ficha(sesion, libreta)

    def test_el_veredicto_lo_dice_en_vez_de_mandar_a_inventar_un_epsg(self, sesion, nube_sin_crs):
        assert "coordenadas locales" in self._ficha(sesion, nube_sin_crs)


class TestElEnvio:
    def test_marcada_encola_y_deja_la_traza_con_el_nombre(self, sesion, nube_sin_crs, con_pdal):
        respuesta = _encolar(sesion, nube_sin_crs, crs_local="si")
        assert respuesta.status_code == 302, respuesta.content.decode()[:300]

        trabajo = ConversionJob.objects.get()
        assert trabajo.source_crs_origin == "local"
        assert trabajo.source_crs_code == ""
        # La traza del día en que alguien diga «esto no tiene sistema»: con quién lo dijo.
        mensajes = [e.message for e in JobEvent.objects.filter(job=trabajo)]
        assert any("topografo" in m and "coordenadas locales" in m for m in mensajes)

    def test_sin_marcar_y_sin_epsg_sigue_sin_poder_convertir_una_nube_al_correr(
        self, sesion, nube_sin_crs, con_pdal
    ):
        """La casilla no cambia la regla para quien no la marca: se encola, y el corredor se
        detiene con `crs-ausente` (ver `apps/jobs/test_crs_local.py`)."""
        _encolar(sesion, nube_sin_crs)
        trabajo = ConversionJob.objects.get()
        assert trabajo.source_crs_origin == "desconocido"
        assert trabajo.source_crs_origin != "local"

    def test_con_un_epsg_a_la_vez_es_una_contradiccion(self, sesion, nube_sin_crs, con_pdal):
        respuesta = _encolar(sesion, nube_sin_crs, crs_local="si", crs_declarado="32719")
        assert respuesta.status_code == 200
        cuerpo = respuesta.content.decode()
        assert "Es una cosa o la otra" in cuerpo
        assert not ConversionJob.objects.exists()

    def test_el_error_conserva_lo_marcado(self, sesion, nube_sin_crs, con_pdal):
        cuerpo = _encolar(
            sesion, nube_sin_crs, crs_local="si", crs_declarado="32719"
        ).content.decode()
        casilla = cuerpo[cuerpo.index('name="crs_local"') :].split(">", 1)[0]
        assert "checked" in casilla

    def test_en_un_raster_no_vale(self, sesion, tmp_path):
        """Un ráster sin georreferencia sigue siendo una imagen: no necesita esta salida, y
        aceptarla en cualquier familia la volvería un «no sé» universal."""
        from apps.formats.tests.constructor import geotiff_minimo

        tif = tmp_path / "sin_crs.tif"
        tif.write_bytes(geotiff_minimo(bandas=3, epsg=None, escala_m=None, origen=None))
        respuesta = sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(tif), "formato": "png", "crs_local": "si"},
        )
        assert respuesta.status_code == 200
        assert "solo se admiten en nubes" in respuesta.content.decode()
        assert not ConversionJob.objects.exists()

    def test_si_la_nube_trae_su_sistema_la_casilla_no_lo_pisa(self, sesion, nube_con_crs, con_pdal):
        """Lo incrustado manda: un campo del formulario no puede borrar un CRS que el archivo
        ya declara. Sería una forma silenciosa de mover la obra de sitio."""
        _encolar(sesion, nube_con_crs, crs_local="si")
        trabajo = ConversionJob.objects.get()
        assert trabajo.source_crs_code == "32719"
        assert trabajo.source_crs_origin != "local"
