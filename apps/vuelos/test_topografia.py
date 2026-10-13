"""El grupo «Topografía» (F20.1): una sola portada para los datos GNSS y los vuelos de dron.

«Coordenadas y datos GNSS» y «Vuelos de dron» eran dos grupos. Se funden en uno que **conserva el
`id` `gnss`**, porque con él el navegador recuerda qué grupos dejó abiertos cada persona: cambiarlo
borraría esa memoria. Lo que cambia es el título y lo que contiene.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.dashboard import taxonomia

pytestmark = pytest.mark.django_db


@pytest.fixture
def sesion(client):
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    return client


class TestElGrupo:
    def test_el_id_sigue_siendo_gnss_y_el_titulo_es_topografia(self):
        grupo = taxonomia.POR_ID["gnss"]
        assert grupo.id == "gnss"
        assert grupo.titulo == "Topografía"

    def test_ya_no_hay_un_grupo_de_vuelos_aparte(self):
        assert "vuelos" not in taxonomia.POR_ID
        assert "Vuelos de dron" not in [g.titulo for g in taxonomia.GRUPOS]
        assert "Coordenadas y datos GNSS" not in [g.titulo for g in taxonomia.GRUPOS]

    @pytest.mark.parametrize("herramienta", ["vuelo_dron", "telemetria", "fotos_dron", "video"])
    def test_las_herramientas_de_vuelos_estan_en_topografia(self, herramienta):
        assert taxonomia.grupo_de_documento(herramienta) == "gnss"

    def test_el_indice_de_vuelos_lee_el_grupo_topografia(self):
        assert taxonomia.INDICES["vuelos"] == ("gnss",)


class TestLaPortada:
    def test_conserva_la_ruta_y_su_nombre(self):
        assert reverse("documents:vuelos") == "/documentos/vuelos/"

    def test_sin_sesion_redirige(self, client):
        assert client.get(reverse("documents:vuelos")).status_code == 302

    def test_tiene_sus_tres_secciones_en_orden(self, sesion):
        cuerpo = sesion.get(reverse("documents:vuelos")).content.decode()
        titulos = re.findall(r'<h2 class="bloque-titulo"[^>]*>([^<]+)</h2>', cuerpo)
        assert titulos == ["Procesamiento GNSS", "Procesamiento de trayectoria"]
        assert "Utilidades del dron" in cuerpo
        assert cuerpo.index("Procesamiento GNSS") < cuerpo.index("Procesamiento de trayectoria")
        assert cuerpo.index("Procesamiento de trayectoria") < cuerpo.index("Utilidades del dron")

    def test_enlaza_la_conversion_de_crudos_y_la_trayectoria(self, sesion):
        cuerpo = sesion.get(reverse("documents:vuelos")).content.decode()
        assert reverse("dashboard:convertir") in cuerpo
        assert reverse("documents:vuelo_dron") in cuerpo

    def test_las_utilidades_estan_plegadas_pero_a_la_vista(self, sesion):
        cuerpo = sesion.get(reverse("documents:vuelos")).content.decode()
        bloque = cuerpo[cuerpo.index('<details class="topografia-utilidades"') :]
        assert "<details" in bloque and "open" not in bloque.split(">", 1)[0]
        for nombre in (
            "Sacar la traza de un dron",
            "Limpiar fotos de dron",
            "Trabajar un video de dron",
        ):
            assert nombre in bloque
