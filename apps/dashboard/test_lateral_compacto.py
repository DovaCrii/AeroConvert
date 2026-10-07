"""El lateral reducido: un icono por grupo, con su cuenta, que lleva al grupo de la portada."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.dashboard import taxonomia

pytestmark = pytest.mark.django_db

SPRITE = (Path(settings.BASE_DIR) / "static" / "img" / "icons.svg").read_text(encoding="utf-8")


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    return client


def test_cada_grupo_tiene_un_icono_que_existe_en_el_sprite():
    for grupo in taxonomia.GRUPOS:
        assert f'id="{grupo.icono}"' in SPRITE, grupo.id


def test_dos_grupos_no_comparten_icono():
    iconos = [g.icono for g in taxonomia.GRUPOS]
    assert len(iconos) == len(set(iconos))


def test_el_lateral_trae_un_enlace_compacto_por_grupo_con_su_cuenta(sesion):
    cuerpo = sesion.get(reverse("dashboard:convertir")).content.decode()
    lateral = cuerpo[cuerpo.index('<aside class="lateral"') : cuerpo.index("</aside>")]
    enlaces = re.findall(
        r'class="[^"]*lateral-grupo-compacto[^"]*"\s+href="[^"]*#grupo-(\w+)"', lateral
    )
    assert set(enlaces) >= {g.id for g in taxonomia.GRUPOS if g.id in {"entregar", "organizar"}}
    assert "lateral-insignia" in lateral
    # El nombre y la cuenta, también para quien no ve el icono.
    assert re.search(r'title="Organizar PDF: \d+ herramientas?"', lateral)


def test_la_portada_tiene_el_ancla_de_cada_grupo(sesion):
    cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
    for grupo in ("entregar", "organizar"):
        assert f'id="grupo-{grupo}"' in cuerpo


def test_un_enlace_con_ancla_abre_el_grupo():
    js = (Path(settings.BASE_DIR) / "static" / "js" / "plegable.js").read_text(encoding="utf-8")
    assert "location.hash" in js and ".open = true" in js
