"""Que quede escrito quién entra y por qué puerta.

Esta instalación está publicada en internet. Una entrada desde la red privada y una desde
internet abierto llegan por el mismo puerto, y sin anotarlo el registro no las distingue.
"""

import logging

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db

CLAVE = "clave-larga-de-verdad-2026"


@pytest.fixture
def ana(db):
    return get_user_model().objects.create_user("ana", password=CLAVE)  # nosec B106


class TestLaEntrada:
    def test_queda_anotada(self, client, ana, caplog):
        with caplog.at_level(logging.INFO, logger="apps.core.senales"):
            client.post(reverse("login"), {"username": "ana", "password": CLAVE})
        assert any("Entró ana" in r.getMessage() for r in caplog.records)

    def test_con_la_direccion_de_quien_entra(self, client, ana, caplog):
        with caplog.at_level(logging.INFO, logger="apps.core.senales"):
            client.post(
                reverse("login"),
                {"username": "ana", "password": CLAVE},
                HTTP_X_FORWARDED_FOR="200.1.2.3",
            )
        assert any("200.1.2.3" in r.getMessage() for r in caplog.records)

    def test_y_diciendo_si_vino_de_internet(self, client, ana, caplog):
        """La distinción que importa, y que no se puede sacar de ningún otro sitio."""
        with caplog.at_level(logging.INFO, logger="apps.core.senales"):
            client.post(
                reverse("login"),
                {"username": "ana", "password": CLAVE},
                HTTP_TAILSCALE_FUNNEL_REQUEST="?1",
            )
        assert any("por internet" in r.getMessage() for r in caplog.records)

    def test_o_de_la_red_privada(self, client, ana, caplog):
        with caplog.at_level(logging.INFO, logger="apps.core.senales"):
            client.post(reverse("login"), {"username": "ana", "password": CLAVE})
        assert any("por red privada" in r.getMessage() for r in caplog.records)


class TestElIntentoFallido:
    def test_se_anota_con_el_nombre_que_se_probo(self, client, ana, caplog):
        """Saber **qué nombres** se están probando es lo que distingue «alguien tecleó mal»
        de «alguien recorre un diccionario»."""
        with caplog.at_level(logging.WARNING, logger="apps.core.senales"):
            client.post(reverse("login"), {"username": "administrador", "password": "1234"})
        assert any("administrador" in r.getMessage() for r in caplog.records)

    def test_pero_nunca_la_contrasena(self, client, ana, caplog):
        """Un registro con contraseñas dentro es peor que no tener registro."""
        centinela = "Qzx9w-esta-no-puede-salir"
        with caplog.at_level(logging.WARNING, logger="apps.core.senales"):
            client.post(reverse("login"), {"username": "ana", "password": centinela})
        for registro in caplog.records:
            assert centinela not in registro.getMessage()


class TestLaSalida:
    def test_tambien_queda(self, client, ana, caplog):
        client.force_login(ana)
        with caplog.at_level(logging.INFO, logger="apps.core.senales"):
            client.post(reverse("logout"))
        assert any("Salió ana" in r.getMessage() for r in caplog.records)
