"""La contraseña de «Proteger» entre la pantalla y el obrero. Ver `secretos.py`."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from apps.documents import secretos

CLAVE = "obra-2026-bhp-centinela"


@pytest.fixture(autouse=True)
def carpeta(tmp_path, settings):
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    return tmp_path / "trabajo"


@pytest.fixture
def job():
    # `secretos` solo lee `pk`: no hace falta la base para esto.
    return SimpleNamespace(pk="0f5a")


class TestIdaYVuelta:
    def test_se_toma_lo_que_se_guardo(self, job):
        secretos.guardar(job, CLAVE)
        assert secretos.tomar(job) == CLAVE

    def test_tomarla_la_borra(self, job):
        secretos.guardar(job, CLAVE)
        secretos.tomar(job)
        assert not secretos.ruta(job).exists()
        with pytest.raises(secretos.SinSecreto):
            secretos.tomar(job)

    def test_sin_guardar_no_hay(self, job):
        with pytest.raises(secretos.SinSecreto):
            secretos.tomar(job)

    def test_en_disco_no_se_lee(self, job):
        """Lo que protege el cifrado: una copia de la carpeta de trabajo no la enseña."""
        secretos.guardar(job, CLAVE)
        assert CLAVE.encode() not in secretos.ruta(job).read_bytes()

    def test_lleva_la_marca_del_barrido(self, job):
        """Así se la lleva aunque el trabajo no llegue a correr nunca."""
        from apps.jobs import retencion

        assert any(m in secretos.ruta(job).name for m in retencion.MARCAS_DE_TRABAJO)

    def test_no_pisa_una_que_ya_estuviera(self, job):
        secretos.guardar(job, CLAVE)
        with pytest.raises(FileExistsError):
            secretos.guardar(job, "otra-distinta")


class TestLoQueNoSeDebeLeer:
    def test_una_de_mas_de_una_hora_no_vale(self, job):
        vieja = secretos._fernet().encrypt_at_time(
            CLAVE.encode(), int(time.time()) - secretos.VIGENCIA_S - 60
        )
        secretos.ruta(job).parent.mkdir(parents=True, exist_ok=True)
        secretos.ruta(job).write_bytes(vieja)
        with pytest.raises(secretos.SinSecreto):
            secretos.tomar(job)
        assert not secretos.ruta(job).exists(), "caducada, pero se borra igual"

    def test_una_cifrada_con_otra_clave_no_vale(self, job, settings):
        secretos.guardar(job, CLAVE)
        settings.SECRET_KEY = "otra-clave-de-otro-despliegue-" + "x" * 30
        with pytest.raises(secretos.SinSecreto):
            secretos.tomar(job)

    def test_olvidar_sin_nada_no_falla(self, job):
        secretos.olvidar(job)
