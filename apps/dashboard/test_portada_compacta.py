"""La portada deja de ser una pared: los grupos se pliegan y solo el primero nace abierto.

Eran veintiséis tarjetas con su descripción y su «Sale:» a la vez. Un `<details>` nativo por
grupo, con teclado y táctil y sin JavaScript; `plegable.js` recuerda lo que cada persona abrió.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db

GRUPO = re.compile(r"<details class=\"grupo-herramientas\"(?P<atributos>[^>]*)>", re.S)


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    return client


def _grupos(cuerpo: str) -> list[str]:
    return [m.group("atributos") for m in GRUPO.finditer(cuerpo)]


class TestSinBusqueda:
    def test_hay_un_details_por_grupo_y_solo_el_primero_esta_abierto(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        atributos = _grupos(cuerpo)
        assert len(atributos) >= 3
        assert re.search(r"\bopen\b", atributos[0])
        assert not any(re.search(r"\bopen\b", a) for a in atributos[1:])

    def test_cada_grupo_recuerda_lo_que_la_persona_hizo_con_una_clave_propia(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        claves = [re.search(r'data-recuerda="([^"]+)"', a).group(1) for a in _grupos(cuerpo)]
        assert len(set(claves)) == len(claves), "dos grupos no pueden compartir clave"
        assert all(c.startswith("grupo-") for c in claves)

    def test_el_resumen_dice_cuantas_herramientas_trae_cada_grupo(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert re.search(r"grupo-cuenta\">\d+ herramienta", cuerpo)

    def test_plegar_un_grupo_no_lo_quita_del_html(self, sesion):
        """Un grupo cerrado sigue en la página con todas sus herramientas, para el lector de
        pantalla y para quien lo abra. Que las apagadas salgan con su motivo es otra cosa y
        depende de la máquina: lo cubren las pruebas del buscador."""
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert cuerpo.count('<details class="grupo-herramientas"') >= 3
        assert cuerpo.count('class="herramienta') >= 10


class TestBuscando:
    def test_todo_abierto_y_sin_recordar_nada(self, sesion):
        """Lo que se encontró no puede quedar tras un grupo que alguien cerró ayer."""
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer"), {"q": "pdf"}).content.decode()
        atributos = _grupos(cuerpo)
        assert atributos, "una búsqueda de «pdf» tiene que encontrar algo"
        assert all(re.search(r"\bopen\b", a) for a in atributos)
        assert not any("data-recuerda" in a for a in atributos)


class TestLaCabecera:
    def test_el_proposito_es_una_linea(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert "Hola, ana. Escriba lo que necesita conseguir, o elija un grupo." in cuerpo


class TestElPanelLateral:
    """La portada tiene un panel a la izquierda: convertir, el índice de grupos y lo reciente."""

    def test_hay_un_enlace_por_grupo_y_cada_uno_lleva_a_un_grupo_que_existe(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        enlaces = re.findall(r'class="lateral-enlace" href="#(grupo-[^"]+)" data-abre', cuerpo)
        ids = re.findall(r'<details class="grupo-herramientas" id="(grupo-[^"]+)"', cuerpo)
        assert len(enlaces) >= 3
        assert enlaces == ids

    def test_trae_el_boton_de_convertir(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert "portada-lateral" in cuerpo
        assert f'href="{reverse("dashboard:convertir")}">Convertir un archivo' in cuerpo

    def test_buscando_el_indice_solo_trae_los_grupos_con_resultados(self, sesion):
        todos = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        buscado = sesion.get(reverse("dashboard:que_puedo_hacer"), {"q": "contraseña"}).content
        assert buscado.decode().count("lateral-enlace") < todos.count("lateral-enlace")

    def test_el_fragmento_de_htmx_lleva_tambien_el_panel(self, sesion):
        cuerpo = sesion.get(
            reverse("dashboard:que_puedo_hacer"), {"q": "pdf"}, HTTP_HX_REQUEST="true"
        ).content.decode()
        assert "portada-lateral" in cuerpo
        assert "<html" not in cuerpo
