"""La libreta de puntos vista desde el navegador: la ficha, el dibujo y el CRS declarado.

Estas pruebas cubren el camino que de verdad recorre una persona, y en particular las dos
cosas sin las que la fase vectorial no sirve de nada:

- Que el dibujo llegue a la página. Es lo que convierte «elige el orden de columnas» en una
  decisión que se toma mirando.
- Que se pueda **declarar** el sistema de referencia. Una libreta no lo lleva dentro nunca,
  así que sin este campo no hay ninguna conversión posible desde la interfaz.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.jobs.models import ConversionJob

pytestmark = pytest.mark.django_db

CRUCE_MINERO = """P1,7318729.036,495279.406,3042.641,pr
P2,7318700.292,495137.090,3045.004,pr
P3,7318656.894,495192.496,3046.322,pr
P4,7318609.156,495087.401,3045.287,pr
P5,7318567.524,495195.695,3045.963,pr
"""

#: Un archivo cuyas dos columnas de coordenadas caben las dos como este UTM: el detector no
#: puede decidir y tiene que preguntar.
AMBIGUO = "\n".join(f"P{i},4{500 + i}00.10,5{100 + i}00.20,120.5,pr" for i in range(1, 6)) + "\n"


@pytest.fixture
def usuario(db):
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


@pytest.fixture
def sesion(client, usuario):
    client.force_login(usuario)
    return client


@pytest.fixture
def libreta(tmp_path, settings):
    # Es una **cadena** separada por `;`, no una lista: en Windows los dos puntos aparecen
    # dentro de cada ruta (`D:\`).
    settings.RAICES_PERMITIDAS = str(tmp_path)
    ruta = tmp_path / "puntos control cruce minero.csv"
    ruta.write_text(CRUCE_MINERO, encoding="utf-8")
    return ruta


def _inspeccionar(sesion, ruta):
    return sesion.get(reverse("dashboard:inspeccionar"), {"ruta": str(ruta)})


class TestLaFichaDeUnaLibreta:
    def test_dice_el_orden_que_dedujo(self, sesion, libreta):
        cuerpo = _inspeccionar(sesion, libreta).content.decode()
        assert "PNEZD" in cuerpo
        assert "rango UTM" in cuerpo

    def test_dice_cuantos_puntos_ha_leido(self, sesion, libreta):
        cuerpo = _inspeccionar(sesion, libreta).content.decode()
        assert "Puntos" in cuerpo
        assert "192,0 m ×" in cuerpo or "192.0 m ×" in cuerpo

    def test_pinta_el_dibujo(self, sesion, libreta):
        cuerpo = _inspeccionar(sesion, libreta).content.decode()
        assert 'class="dibujo-puntos"' in cuerpo
        assert cuerpo.count('class="dibujo-punto"') == 5

    def test_cada_punto_lleva_su_titulo(self, sesion, libreta):
        """Es la alternativa textual del dibujo: sin ella es una imagen sin `alt`."""
        cuerpo = _inspeccionar(sesion, libreta).content.decode()
        assert "7318729.036" in cuerpo
        assert "<title>" in cuerpo

    def test_el_dibujo_no_pide_nada_de_fuera(self, sesion, libreta):
        """La CSP es 'self'. Un mapa base serían teselas de un servidor ajeno, y aquí lo
        que se dibuja es la geometría propia."""
        cuerpo = _inspeccionar(sesion, libreta).content.decode()
        assert "http://" not in cuerpo
        assert "https://" not in cuerpo


class TestElFormularioLlegaADondeConvierte:
    """El botón de convertir tiene que apuntar a la vista que convierte.

    Existe por un fallo que estuvo suelto y **no daba ningún error**: el formulario de la
    ficha enviaba a `dashboard:convertir`, que es la vista que **pinta la pantalla**, no la
    que encola. Pulsar cualquier destino recargaba la página y no pasaba nada. Se colló al
    renombrar «Mesa» a «Convertir»: el nombre de la URL de la página y el del envío se
    parecen lo bastante para intercambiarlos sin notarlo.

    Ninguna prueba lo cazaba porque todas las que encolaban llamaban a la vista
    directamente, sin pasar por la plantilla.
    """

    def test_la_ficha_envia_a_encolar(self, sesion, libreta):
        cuerpo = _inspeccionar(sesion, libreta).content.decode()
        assert f'action="{reverse("dashboard:encolar")}"' in cuerpo

    def test_y_no_a_la_pantalla_que_solo_pinta(self, sesion, libreta):
        cuerpo = _inspeccionar(sesion, libreta).content.decode()
        assert f'action="{reverse("dashboard:convertir")}"' not in cuerpo

    def test_la_pantalla_no_encola_aunque_le_llegue_un_post(self, sesion, libreta):
        """Y que se sepa: si algún día vuelve a apuntar ahí, esto lo dice."""
        sesion.post(
            reverse("dashboard:convertir"),
            {"ruta": str(libreta), "formato": "gpkg", "crs_declarado": "32719"},
        )
        assert ConversionJob.objects.count() == 0


class TestElOrdenAmbiguo:
    @pytest.fixture
    def dudosa(self, tmp_path, settings):
        settings.RAICES_PERMITIDAS = str(tmp_path)
        ruta = tmp_path / "dudosa.csv"
        ruta.write_text(AMBIGUO, encoding="utf-8")
        return ruta

    def test_avisa_con_la_consecuencia_y_no_con_el_diagnostico(self, sesion, dudosa):
        """«Hay que elegir el orden» no mueve a nadie. «Elegir mal deja los puntos a miles
        de kilómetros» sí, y la cifra sale del propio archivo."""
        cuerpo = _inspeccionar(sesion, dudosa).content.decode()
        assert "PNEZD" in cuerpo and "PENZD" in cuerpo
        assert "km de donde van" in cuerpo

    def test_y_aun_asi_dibuja(self, sesion, dudosa):
        """No enseñar nada dejaría a la persona sin lo único que resolvería su duda."""
        assert 'class="dibujo-puntos"' in _inspeccionar(sesion, dudosa).content.decode()


class TestDeclararElSistemaDeReferencia:
    def test_la_ficha_pide_el_epsg_cuando_no_lo_hay(self, sesion, libreta):
        cuerpo = _inspeccionar(sesion, libreta).content.decode()
        assert 'name="crs_declarado"' in cuerpo
        # Sin valor por omisión: un desplegable que ya viene con 32719 puesto es una forma
        # de adivinar con la firma de otra persona.
        assert 'value="32719"' not in cuerpo

    def test_lo_declarado_queda_en_el_trabajo_y_marcado_como_declarado(self, sesion, libreta):
        respuesta = sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(libreta), "formato": "gpkg", "crs_declarado": "32719", "perfil": ""},
        )
        assert respuesta.status_code == 302

        trabajo = ConversionJob.objects.latest("id")
        assert trabajo.source_crs_code == "32719"
        assert trabajo.source_crs_origin == "declarado"

    def test_y_queda_escrito_quien_lo_declaro(self, sesion, libreta, usuario):
        """La traza del día en que alguien puso la obra en otro país."""
        sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(libreta), "formato": "gpkg", "crs_declarado": "32719", "perfil": ""},
        )
        trabajo = ConversionJob.objects.latest("id")
        mensajes = " ".join(e.message for e in trabajo.eventos.all())
        assert usuario.get_username() in mensajes
        assert "32719" in mensajes

    def test_un_epsg_que_no_existe_se_rechaza(self, sesion, libreta):
        respuesta = sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(libreta), "formato": "gpkg", "crs_declarado": "999999", "perfil": ""},
            follow=True,
        )
        assert ConversionJob.objects.count() == 0
        assert any("999999" in str(m) for m in respuesta.context["messages"])

    def test_lo_que_no_es_un_numero_se_rechaza(self, sesion, libreta):
        sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(libreta), "formato": "gpkg", "crs_declarado": "UTM 19 sur", "perfil": ""},
        )
        assert ConversionJob.objects.count() == 0

    def test_no_declarar_nada_no_impide_encolar(self, sesion, libreta):
        """Encolar sin CRS es legítimo: quien lo para, con su motivo y su explicación, es el
        runner. Rechazarlo aquí daría el mensaje en el sitio equivocado."""
        sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(libreta), "formato": "gpkg", "perfil": ""},
        )
        assert ConversionJob.objects.count() == 1
