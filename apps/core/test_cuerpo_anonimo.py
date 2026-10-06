"""A-01 de la auditoría de seguridad del 2026-10-05: un anónimo no puede hacer que el servidor
reciba y escriba 2 GB por petición.

`CsrfViewMiddleware` lee `request.POST`, y eso analiza el cuerpo multipart entero **antes** del
login. El middleware nuevo decide con `Content-Length` y no lee nada.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def entorno(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.TOPE_MB = 5
    settings.LIMITE_DE_CUERPO_ANONIMO_BYTES = 100_000


def _cuerpo(bytes_: int) -> bytes:
    return b"x" * bytes_


class TestAnonimo:
    def test_un_cuerpo_grande_sin_sesion_se_corta_con_413(self, client):
        respuesta = client.post(
            "/entrar/", data=_cuerpo(200_000), content_type="application/octet-stream"
        )
        assert respuesta.status_code == 413

    def test_y_tambien_contra_la_subida(self, client):
        respuesta = client.post(
            "/subir/", data={"archivo": SimpleUploadedFile("a.bin", _cuerpo(200_000))}
        )
        assert respuesta.status_code == 413

    def test_un_formulario_de_entrada_normal_pasa(self, client):
        respuesta = client.post("/entrar/", {"username": "a@b.cl", "password": "mala"})
        assert respuesta.status_code != 413

    def test_un_content_length_que_no_es_numero_se_rechaza(self, client):
        respuesta = client.post("/entrar/", {"a": "b"}, CONTENT_LENGTH="abc")
        assert respuesta.status_code == 413

    def test_un_get_nunca_se_corta(self, client):
        assert client.get("/entrar/").status_code == 200


class TestConSesion:
    @pytest.fixture
    def sesion(self, client):
        client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
        return client

    def test_una_subida_dentro_del_tope_pasa(self, sesion):
        respuesta = sesion.post(
            "/subir/", {"archivo": SimpleUploadedFile("a.bin", _cuerpo(200_000))}
        )
        assert respuesta.status_code != 413

    def test_un_cuerpo_muy_por_encima_del_tope_se_corta_antes_de_leerlo(self, sesion):
        """TOPE_MB 5 más 10 MiB de margen: 20 MiB declarados ya no entran."""
        respuesta = sesion.post(
            "/subir/",
            data=_cuerpo(100),
            content_type="application/octet-stream",
            CONTENT_LENGTH=str(20 * 1_048_576),
        )
        assert respuesta.status_code == 413
