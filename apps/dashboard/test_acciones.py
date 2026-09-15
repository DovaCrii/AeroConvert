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


class TestQueLaTarjetaNoTireLaEleccion:
    """**El defecto que traía este catálogo desde que se escribió.**

    Las seis tarjetas geoespaciales apuntaban a `dashboard:convertir` a secas. O sea que
    pulsar «Llevarlo a QGIS» —una tarjeta cuyo único contenido es esa elección— llevaba a la
    pantalla genérica a elegir otra vez. Resolvía bien la URL y por eso no fallaba nada.
    """

    def _planos(self):
        return [a for a in acciones_mod.todas() if a.categoria == "planos"]

    def test_cada_destino_lleva_el_suyo_en_el_enlace(self):
        for accion in self._planos():
            assert accion.consulta.get("destino"), accion.nombre
            assert f"destino={accion.consulta['destino']}" in accion.enlace

    def test_y_por_eso_los_seis_enlaces_son_distintos(self):
        enlaces = {a.enlace for a in self._planos()}
        assert len(enlaces) == len(self._planos())

    def test_una_accion_sin_consulta_no_arrastra_interrogacion(self):
        """Las de PDF no llevan parámetros: un `?` suelto al final es basura en la barra."""
        pdf = [a for a in acciones_mod.todas() if a.categoria == "documentos" and a.url]
        assert pdf
        assert all("?" not in a.enlace for a in pdf)

    def test_una_apagada_no_tiene_a_donde_ir(self):
        for accion in acciones_mod.todas():
            if not accion.disponible:
                assert accion.enlace == ""


class TestQueLasSeisNoSeanLaMismaTarjeta:
    """Icono, color y «Sale:» distinguían cero: los seis compartían los tres."""

    def _planos(self):
        return [a for a in acciones_mod.todas() if a.categoria == "planos"]

    def test_cada_una_con_su_icono(self):
        iconos = {a.icono for a in self._planos()}
        assert len(iconos) == len(self._planos())

    def test_y_ninguna_dice_ya_el_formato_que_ese_programa_abre(self):
        """Una línea igual en las seis no informa: ocupa dos renglones y no distingue nada."""
        for accion in self._planos():
            assert "el formato que ese programa abre" not in accion.sale

    def test_el_sale_nombra_formatos_de_verdad(self):
        salidas = {a.sale for a in self._planos()}
        assert len(salidas) > 1, "Si todas dicen lo mismo, seguimos igual."
        qgis = next(a for a in self._planos() if a.consulta["destino"] == "qgis")
        # COG para ráster, GeoPackage para vectorial y COPC para nubes: los tres destinos
        # que el perfil declara en `destinos_por_familia`.
        assert "COG" in qgis.sale
        assert "GeoPackage" in qgis.sale

    def test_no_repite_un_formato_cuando_coincide_con_el_de_por_omision(self):
        """Google Earth va a KMZ y solo a KMZ: «KMZ · KMZ» sería un fallo visible."""
        tierra = next(a for a in self._planos() if a.consulta["destino"] == "google-earth")
        assert tierra.sale == "KMZ"

    def test_las_seis_llevan_la_familia_de_color_propia(self):
        assert {a.familia for a in self._planos()} == {"destino"}


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


class TestElViajeCompleto:
    """De la tarjeta a la pantalla de convertir **sin perder por el camino lo elegido**.

    Es el trozo que no comprueba ninguna prueba de unidad: `Accion.enlace` puede ser perfecto
    y la pantalla de destino ignorar el parámetro, que es exactamente lo que pasaba.
    """

    def test_convertir_reconoce_el_destino_y_lo_dice(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:convertir"), {"destino": "qgis"}).content.decode()
        assert "Vas a llevarlo a" in cuerpo
        assert "QGIS" in cuerpo

    def test_y_lo_lleva_escondido_para_que_la_ficha_lo_marque(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:convertir"), {"destino": "civil3d"}).content.decode()
        assert 'name="destino" value="civil3d"' in cuerpo

    def test_sin_destino_no_aparece_la_linea_ni_el_campo(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:convertir")).content.decode()
        assert "Vas a llevarlo a" not in cuerpo
        assert 'name="destino"' not in cuerpo

    def test_un_destino_inventado_se_ignora_en_silencio(self, sesion):
        """Lo escribe cualquiera en la barra. La pantalla sin preferencia funciona igual, así
        que no hay nada que avisar — y un mensaje de error aquí sería ruido."""
        respuesta = sesion.get(reverse("dashboard:convertir"), {"destino": "xilofono"})
        assert respuesta.status_code == 200
        assert 'name="destino"' not in respuesta.content.decode()


class TestLaPantalla:
    def test_abre(self, sesion):
        respuesta = sesion.get(reverse("dashboard:que_puedo_hacer"))
        assert respuesta.status_code == 200
        assert "¿Qué necesitas hacer?" in respuesta.content.decode()

    def test_filtra_con_lo_escrito(self, sesion):
        """**Se mira el fragmento, no la página.**

        La página entera trae ahora el desplegable de la barra, que lista todas las
        herramientas en todas las pantallas: buscar «Marca de agua» en el HTML completo la
        encuentra siempre, y la prueba pasaría dijera lo que dijera el buscador.
        """
        cuerpo = sesion.get(
            reverse("dashboard:que_puedo_hacer"),
            {"q": "contrasena"},
            headers={"HX-Request": "true"},
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

    def test_es_la_portada(self):
        """**Estaba escrita como «la puerta que faltaba» y vivía en `/que-hacer/`.**

        O sea que solo llegaba quien ya sabía que existía, que es justo lo contrario de una
        puerta. Es la única pantalla que empieza preguntando la intención, y quien entra trae
        una intención, no un formato.
        """
        assert reverse("dashboard:que_puedo_hacer") == "/"

    def test_y_es_a_donde_lleva_entrar(self, client, db, settings):
        settings.MODO = "taller"
        get_user_model().objects.create_user("bea", password=CLAVE)  # nosec B106
        respuesta = client.post(reverse("login"), {"username": "bea", "password": CLAVE})
        assert respuesta.status_code == 302
        assert respuesta["Location"] == reverse("dashboard:que_puedo_hacer")

    def test_el_rotulo_no_dice_TODO(self, sesion):
        """El CSS lo pone en mayúsculas, y «TODO» a secas es el marcador de pendiente que
        dejamos los programadores — delante de un equipo que sabe lo que es."""
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert ">TODO<" not in cuerpo.replace(" ", "").replace("\n", "")
        assert "Todas las herramientas" in cuerpo
