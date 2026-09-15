"""El catálogo de todo lo que se puede hacer, y su buscador.

Las capacidades vivían en tres pantallas que no se hablan: «Convertir» para lo geoespacial,
«PDF» para los once de documentos, y «Compatibilidad» para la matriz. Quien llega con un
archivo y una intención —«juntar estos planos y numerarlos»— tenía que saber de antemano en
cuál mirar.

Lo que estas pruebas fijan es lo que hace útil al buscador: **que encuentre por la palabra que
usa quien busca, no por la que eligió quien programó.**
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from . import acciones as acciones_mod

pytestmark = pytest.mark.django_db

CLAVE = "clave-larga-de-verdad-2026"


@pytest.fixture
def sesion(client, db, settings):
    settings.MODO = "taller"
    usuario = get_user_model().objects.create_user("ana", password=CLAVE)  # nosec B106
    client.force_login(usuario)
    return client


def _nombres(grupos):
    return [a.nombre for g in grupos for a in g["acciones"]]


class TestElCatalogo:
    def test_estan_las_de_pdf_y_las_geoespaciales(self):
        categorias = {a.categoria for a in acciones_mod.todas()}
        assert "documentos" in categorias
        assert "planos" in categorias

    def test_lo_geoespacial_entra_por_destino_y_no_por_par_de_formatos(self):
        """La matriz tiene 189 celdas. Esto contesta «¿qué quiero hacer?», que es una
        pregunta con veinte respuestas, no con ciento ochenta y nueve."""
        planos = [a for a in acciones_mod.todas() if a.categoria == "planos"]
        assert 0 < len(planos) <= 12
        assert all(a.nombre.startswith("Llevarlo a") for a in planos)

    def test_cada_una_dice_que_sale(self):
        assert all(a.sale for a in acciones_mod.todas())


class TestElBuscador:
    def test_sin_texto_salen_todas(self):
        assert len(_nombres(acciones_mod.por_categoria())) == len(acciones_mod.todas())

    def test_encuentra_por_el_nombre(self):
        assert "Unir PDF" in _nombres(acciones_mod.por_categoria("unir"))

    def test_y_por_una_palabra_que_no_esta_en_el_nombre(self):
        """**Lo que hace útil a un buscador.** Nadie escribe «unir»: escribe «juntar»."""
        assert "Unir PDF" in _nombres(acciones_mod.por_categoria("juntar"))

    def test_encuentra_la_marca_de_agua_por_lo_que_estampa(self):
        assert "Marca de agua" in _nombres(acciones_mod.por_categoria("confidencial"))

    def test_encuentra_proteger_por_contrasena(self):
        assert "Proteger PDF" in _nombres(acciones_mod.por_categoria("clave"))

    def test_varias_palabras_en_cualquier_orden(self):
        """«Todas tienen que aparecer», y da igual el orden y en qué campo estén."""
        assert _nombres(acciones_mod.por_categoria("pdf juntar"))
        assert _nombres(acciones_mod.por_categoria("juntar pdf"))

    def test_lo_que_no_existe_no_devuelve_nada(self):
        assert acciones_mod.por_categoria("xilofono") == []

    def test_una_categoria_vacia_no_se_pinta(self):
        """Un encabezado sobre un hueco hace pensar que algo se rompió."""
        grupos = acciones_mod.por_categoria("contrasena")
        assert all(g["acciones"] for g in grupos)


class TestLaPantalla:
    def test_abre(self, sesion):
        respuesta = sesion.get(reverse("dashboard:que_puedo_hacer"))
        assert respuesta.status_code == 200
        assert "¿Qué necesitas hacer?" in respuesta.content.decode()

    def test_filtra_con_lo_escrito(self, sesion):
        cuerpo = sesion.get(
            reverse("dashboard:que_puedo_hacer"), {"q": "contrasena"}
        ).content.decode()
        assert "Proteger PDF" in cuerpo
        assert "Marca de agua" not in cuerpo

    def test_htmx_devuelve_solo_el_fragmento(self, sesion):
        """Sin la página entera: es lo que se reemplaza con cada tecla."""
        respuesta = sesion.get(
            reverse("dashboard:que_puedo_hacer"), {"q": "unir"}, headers={"HX-Request": "true"}
        )
        cuerpo = respuesta.content.decode()
        assert "Unir PDF" in cuerpo
        assert "<!doctype html>" not in cuerpo.lower()

    def test_sin_resultados_lo_dice_y_ofrece_donde_mirar(self, sesion):
        cuerpo = sesion.get(
            reverse("dashboard:que_puedo_hacer"), {"q": "xilofono"}
        ).content.decode()
        assert "Nada coincide" in cuerpo
        assert reverse("engines:matriz") in cuerpo

    def test_hay_que_haber_entrado(self, client):
        assert client.get(reverse("dashboard:que_puedo_hacer")).status_code == 302
