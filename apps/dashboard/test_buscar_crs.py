"""El buscador de sistemas de referencia de la ficha, para quien no sabe su EPSG."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def sesion(client):
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    return client


def test_pide_sesion(client):
    assert client.get(reverse("dashboard:buscar_crs"), {"q": "utm"}).status_code == 302


def test_devuelve_botones_con_el_codigo_y_el_nombre(sesion):
    cuerpo = sesion.get(reverse("dashboard:buscar_crs"), {"q": "sirgas chile utm 19 sur"}).content
    cuerpo = cuerpo.decode()
    assert 'data-crs-codigo="5361"' in cuerpo
    assert "SIRGAS-Chile 2002 / UTM zone 19S" in cuerpo


def test_con_la_caja_vacia_no_ofrece_ninguno(sesion):
    cuerpo = sesion.get(reverse("dashboard:buscar_crs"), {"q": ""}).content.decode()
    assert "data-crs-codigo" not in cuerpo


def test_si_no_hay_nada_lo_dice_y_explica_como_buscar(sesion):
    cuerpo = sesion.get(reverse("dashboard:buscar_crs"), {"q": "zzzz inexistente"}).content
    cuerpo = cuerpo.decode()
    assert "No hay ningún sistema" in cuerpo and "data-crs-codigo" not in cuerpo


def test_la_ficha_lo_ofrece_sin_enviar_la_busqueda_con_el_formulario():
    plantilla = (Path(settings.BASE_DIR) / "templates" / "dashboard" / "_ficha.html").read_text(
        encoding="utf-8"
    )
    assert "dashboard:buscar_crs" in plantilla
    assert 'form="sin-formulario"' in plantilla
    # El campo que valida el servidor sigue siendo el EPSG, sin valor por omisión.
    assert 'id="id_crs_declarado"' in plantilla


def test_elegir_solo_escribe_el_codigo_en_el_campo_que_valida_el_servidor():
    js = (Path(settings.BASE_DIR) / "static" / "js" / "crs.js").read_text(encoding="utf-8")
    assert "id_crs_declarado" in js and "data-crs-codigo" in js
    assert ".submit(" not in js
