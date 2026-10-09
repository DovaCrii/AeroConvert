"""Lo que comparten las pruebas de varias capas y de mapa base (F19.3 y F19.5)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.engines.base import Disponibilidad
from apps.visor import motor
from apps.visor.testing import GdalDeMentira


@pytest.fixture
def raiz_de_obra(tmp_path, settings):
    """Una carpeta de obra dentro de las raíces permitidas, con la caché del visor aparte."""
    settings.RAICES_PERMITIDAS = str(tmp_path / "obra")
    settings.MODO = settings.MODO_TALLER
    settings.VISOR_CACHE = str(tmp_path / "cache-visor")
    settings.VISOR_CACHE_MAX_MB = 64
    settings.VISOR_MAPA_BASE = ""
    carpeta = tmp_path / "obra"
    carpeta.mkdir()
    return carpeta


@pytest.fixture
def tif_de_obra(raiz_de_obra):
    ruta = raiz_de_obra / "ortofoto.tif"
    ruta.write_bytes(b"II*\x00" + b"ortofoto sintetica" * 200)
    return ruta


@pytest.fixture
def persona(db):
    return get_user_model().objects.create_user("ana")


@pytest.fixture
def otra_persona(db):
    return get_user_model().objects.create_user("beto")


@pytest.fixture
def con_sesion(client, persona):
    client.force_login(persona)
    return client


@pytest.fixture
def gdal_de_mentira(monkeypatch):
    """GDAL de mentira, y presente: lo que miden estas pruebas es el pegamento, no GDAL."""
    mentira = GdalDeMentira()
    monkeypatch.setattr(motor, "correr", mentira)
    monkeypatch.setattr(motor, "disponibilidad", lambda: Disponibilidad.si("GDAL de mentira"))
    return mentira
