"""La barra superior en tres zonas (F13.9): marca, buscador y cuenta.

La explicación del modo pasó al lateral, donde sigue siempre visible; y el buscador ya no
desaparece en pantallas estrechas: mide al menos 160 px (10 rem).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db

CSS = (Path(settings.BASE_DIR) / "static" / "css" / "app.css").read_text(encoding="utf-8")


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    return client


def test_con_sesion_la_explicacion_vive_en_el_lateral(sesion):
    cuerpo = sesion.get(reverse("dashboard:convertir")).content.decode()
    barra = cuerpo[cuerpo.index('<header class="barra">') : cuerpo.index("</header>")]
    lateral = cuerpo[cuerpo.index('<aside class="lateral"') : cuerpo.index("</aside>")]
    assert "barra-explicacion" not in barra
    assert "lateral-modo-texto" in lateral


def test_sin_sesion_la_barra_conserva_la_explicacion(client):
    cuerpo = client.get(reverse("login")).content.decode()
    assert "barra-explicacion" in cuerpo


def test_el_buscador_no_baja_de_160_px_ni_se_oculta():
    bloque = CSS[CSS.index(".buscador-barra {") :]
    bloque = bloque[: bloque.index("}")]
    minimo = float(re.search(r"min-width:\s*([\d.]+)rem", bloque).group(1))
    assert minimo * 16 >= 160
    assert not re.search(r"\.buscador-barra\s*\{[^}]*display:\s*none", CSS)
    # Medido a 375 px: un `width: 8.5rem` en el campo lo dejaba en 136 px.
    for regla in re.findall(r"\.buscador-barra input\s*\{([^}]*)\}", CSS):
        ancho = re.search(r"(?<![-\w])width:\s*([\d.]+)rem", regla)
        assert not ancho or float(ancho.group(1)) * 16 >= 160
