"""Cuando el archivo ya no está, pero el recibo sí.

Era un `Http404` con un texto que nadie veía, y en una carpeta compartida este camino **no es
raro**: cualquiera puede mover la salida desde su Explorador, y la retención se lleva las
efímeras por diseño.

410 y no 404 a propósito: un 404 dice «esto nunca existió». Aquí existió, se verificó, y
desapareció por una razón que sabemos nombrar.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.jobs.models import HECHO, ConversionJob

pytestmark = pytest.mark.django_db


@pytest.fixture
def ana(client):
    usuaria = get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
    client.force_login(usuaria)
    return usuaria


@pytest.fixture
def trabajo(ana, tmp_path):
    return ConversionJob.objects.create(
        owner=ana,
        source_path=str(tmp_path / "orto.tif"),
        source_name="orto.tif",
        source_size_bytes=466_200_000,
        source_sha256="9f3a" * 16,
        target_format_code="cog",
        engine_id="gdal-translate",
        engine_version="GDAL 3.12.4",
        status=HECHO,
        output_path=str(tmp_path / "orto_civil3d.tif"),
        output_size_bytes=41_300_000,
    )


def _descargar(client, trabajo):
    return client.get(reverse("jobs:descargar", kwargs={"pk": trabajo.pk}))


class TestLosTresMotivos:
    def test_una_salida_barrida(self, client, trabajo):
        trabajo.output_path = ""
        trabajo.save(update_fields=["output_path"])
        respuesta = _descargar(client, trabajo)
        assert respuesta.status_code == 410
        assert "caducó" in respuesta.content.decode()

    def test_una_que_alguien_movio(self, client, trabajo):
        """El archivo nunca llegó a existir en el disco de la prueba: es el mismo caso."""
        respuesta = _descargar(client, trabajo)
        assert respuesta.status_code == 410
        assert "ya no está donde quedó" in respuesta.content.decode()

    def test_una_que_alguien_reemplazo(self, client, trabajo, tmp_path):
        (tmp_path / "orto_civil3d.tif").write_bytes(b"otra cosa")
        respuesta = _descargar(client, trabajo)
        assert respuesta.status_code == 410
        assert "no es el que se generó" in respuesta.content.decode()

    def test_los_tres_dicen_cosas_distintas(self, client, trabajo, tmp_path):
        """Si alguien los unifica en un mensaje genérico, esto falla."""
        sin_ruta = _descargar(client, trabajo).content.decode()
        (tmp_path / "orto_civil3d.tif").write_bytes(b"otra cosa")
        reemplazada = _descargar(client, trabajo).content.decode()
        assert sin_ruta != reemplazada


class TestElReciboSobrevive:
    def test_se_sigue_viendo_lo_que_se_hizo(self, client, trabajo):
        cuerpo = _descargar(client, trabajo).content.decode()
        assert "orto.tif" in cuerpo
        assert "GDAL 3.12.4" in cuerpo
        assert trabajo.source_sha256[:32] in cuerpo

    def test_y_ofrece_rehacerla(self, client, trabajo):
        """Rehacerla es un clic: `reencolar` crea una fila nueva conservando origen, destino
        y opciones."""
        cuerpo = _descargar(client, trabajo).content.decode()
        assert reverse("jobs:reencolar", kwargs={"pk": trabajo.pk}) in cuerpo

    def test_no_se_ensena_la_ruta_entera(self, client, trabajo):
        """En una carpeta compartida una ruta ocupa media pantalla y no le dice nada a
        nadie. Con el nombre de la carpeta basta."""
        cuerpo = _descargar(client, trabajo).content.decode()
        assert trabajo.output_path not in cuerpo

    def test_dice_que_el_original_esta_intacto(self, client, trabajo):
        assert "no se tocó nunca" in _descargar(client, trabajo).content.decode()


class TestSigueSiendoDeSuDueno:
    def test_la_de_otra_persona_no_se_ve(self, client, trabajo):
        otra = get_user_model().objects.create_user("beto", password="x" * 20)  # nosec B106
        client.force_login(otra)
        assert _descargar(client, trabajo).status_code == 404
