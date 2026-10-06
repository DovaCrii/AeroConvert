"""El lateral de navegación, al estilo de AeroControl.

Sustituyó al desplegable «Herramientas» de la barra. Lo que se vigila aquí es lo que no puede
fallar sin que nadie lo note: que llegue ya escrito (la navegación no depende de JavaScript),
que lleve a los mismos sitios que llevaba la barra, y que la barra no vuelva a crecer.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    return client


def _lateral(cuerpo: str) -> str:
    return cuerpo[cuerpo.index('<aside class="lateral"') : cuerpo.index("</aside>")]


class TestElLateralLlegaEscrito:
    def test_esta_en_toda_pantalla_con_sesion(self, sesion):
        for nombre in ("dashboard:que_puedo_hacer", "dashboard:convertir", "jobs:lista"):
            cuerpo = sesion.get(reverse(nombre)).content.decode()
            assert 'class="lateral"' in cuerpo and "con-lateral" in cuerpo, nombre

    def test_la_pantalla_de_entrada_no_lo_tiene(self, client):
        cuerpo = client.get(reverse("login")).content.decode()
        assert 'class="lateral"' not in cuerpo
        assert "con-lateral" not in cuerpo

    def test_lleva_a_lo_mismo_que_llevaba_la_barra(self, sesion):
        lateral = _lateral(sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode())
        for nombre in (
            "dashboard:que_puedo_hacer",
            "dashboard:convertir",
            "jobs:lista",
            "engines:matriz",
            "presets:lista",
        ):
            assert f'href="{reverse(nombre)}"' in lateral, nombre

    def test_los_grupos_son_details_con_las_herramientas_dentro(self, sesion):
        """Sin JavaScript tienen que abrir: si el panel viniera vacío para rellenarlo después,
        sería un botón que abre un hueco."""
        lateral = _lateral(sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode())
        assert len(re.findall(r'<details class="lateral-grupo"', lateral)) >= 3
        assert lateral.count("<summary") >= 3
        assert lateral.count("menu-enlace") >= 5, "el lateral llega sin sus herramientas"

    def test_cada_grupo_recuerda_lo_que_la_persona_hizo_con_su_propia_clave(self, sesion):
        lateral = _lateral(sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode())
        claves = re.findall(r'class="lateral-grupo" data-recuerda="([^"]+)"', lateral)
        assert len(claves) >= 3 and len(set(claves)) == len(claves)
        assert all(c.startswith("lateral-") for c in claves)

    def test_solo_salen_las_herramientas_que_se_pueden_hacer(self, sesion):
        """Las apagadas viven en el catálogo y en Compatibilidad, con su motivo."""
        lateral = _lateral(sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode())
        assert "herramienta-apagada" not in lateral
        assert "Aquí no se puede" not in lateral


class TestLaPaginaDondeSeEsta:
    @pytest.mark.parametrize(
        ("nombre", "texto"),
        [
            ("dashboard:que_puedo_hacer", "Inicio"),
            ("dashboard:convertir", "Convertir"),
            ("jobs:lista", "Historial"),
            ("engines:matriz", "Compatibilidad"),
        ],
    )
    def test_la_entrada_actual_lo_dice_con_aria_current(self, sesion, nombre, texto):
        """El color no va solo: además de la barra de color, el atributo para el lector."""
        lateral = _lateral(sesion.get(reverse(nombre)).content.decode())
        actuales = re.findall(
            r'aria-current="page"[^>]*>\s*<svg.*?</svg>\s*<span>([^<]+)', lateral, re.S
        )
        assert actuales == [texto]


class TestLaBarra:
    def test_la_barra_ya_no_lleva_secciones_solo_cuenta_y_apariencia(self, sesion):
        """Las secciones se mudaron al lateral. Lo que queda en la barra es el tema, las cuentas
        (si se administra) y salir: una barra corta no se parte en dos líneas."""
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        barra = cuerpo[cuerpo.index('<nav class="barra-nav"') : cuerpo.index("</header>")]
        assert 'aria-label="Cuenta y apariencia"' in barra
        assert "Convertir" not in barra and "Historial" not in barra
        assert "menu-panel" not in cuerpo and 'id="menu-herramientas"' not in cuerpo

    def test_el_boton_del_lateral_esta_en_la_barra_y_apunta_al_lateral(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        boton = cuerpo[cuerpo.index('id="lateral-alternar"') - 80 : cuerpo.index("</button>")]
        assert 'aria-controls="lateral"' in boton
        assert 'aria-label="Mostrar u ocultar el menú"' in boton
        assert 'id="lateral"' in cuerpo

    def test_el_script_del_lateral_se_carga_y_el_del_menu_ya_no(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert "js/lateral.js" in cuerpo
        assert "js/menu.js" not in cuerpo
