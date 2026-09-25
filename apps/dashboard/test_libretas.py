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

from apps.engines import registry
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


@pytest.fixture
def con_ogr(monkeypatch):
    """Finge que OGR está en esta máquina.

    **El gate corre sin GDAL ni PDAL instalados**, que es la regla de la familia, y sin esto
    la vista rechazaba el envío con «ningún motor sabe hacer esa conversión»: `motor_para()`
    solo devuelve motores *disponibles*. Estas pruebas van del camino del formulario —el
    CRS declarado, la bitácora, el rechazo de un EPSG inventado— y no de si la herramienta
    está instalada, que ya lo comprueba la sonda con sus propias pruebas.

    Se descubrió porque pasaban en Windows y fallaban en CI, que es la peor forma de pasar.
    """
    from apps.engines.base import Disponibilidad
    from apps.vector import motores

    monkeypatch.setattr(motores, "_sonda_ogr", lambda: Disponibilidad.si("OGR de mentira 1.0"))


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


class TestElDestinoQueSeOfrece:
    """Un perfil es «dónde tiene que abrir», no «a qué formato».

    Civil 3D quiere un GeoTIFF si le llega una ortofoto y un **LandXML** si le llega una
    libreta de puntos, y son la misma respuesta a la misma pregunta. Antes de esto el botón
    de Civil 3D salía apagado delante de una libreta —diciendo que no se puede— porque el
    único destino que sabía ofrecer era el ráster.
    """

    def test_civil3d_ofrece_landxml_para_una_libreta(self, sesion, libreta):
        cuerpo = _inspeccionar(sesion, libreta).content.decode()
        assert "LandXML" in cuerpo

    def test_y_el_boton_no_sale_apagado(self, sesion, libreta):
        """LandXML lo escribimos nosotros, así que no depende de nada instalado: en una
        máquina sin GDAL este botón tiene que seguir vivo."""
        from apps.engines.base import ParDeFormatos
        from apps.targets import perfiles as perfiles_mod

        assert perfiles_mod.CIVIL3D.destino_para("vector") == "landxml"
        assert registry.celda(ParDeFormatos("puntos", "landxml")).se_puede is True

    def test_para_una_ortofoto_sigue_siendo_geotiff(self):
        """El cambio no puede mover el caso que originó la aplicación."""
        from apps.targets import perfiles as perfiles_mod

        assert perfiles_mod.CIVIL3D.destino_para("raster") == "geotiff"
        assert perfiles_mod.CIVIL3D.destino_para("") == "geotiff"

    def test_lo_que_se_ofrece_es_lo_que_se_encola(self, sesion, libreta):
        """Tener el destino por familia en dos sitios con criterios distintos haría que el
        botón dijera «LandXML» y el trabajo saliera como GeoTIFF."""
        sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(libreta), "perfil": "civil3d", "crs_declarado": "32719"},
        )
        assert ConversionJob.objects.latest("id").target_format_code == "landxml"


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

    def test_lo_declarado_queda_en_el_trabajo_y_marcado_como_declarado(
        self, sesion, libreta, con_ogr
    ):
        respuesta = sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(libreta), "formato": "gpkg", "crs_declarado": "32719", "perfil": ""},
        )
        assert respuesta.status_code == 302

        trabajo = ConversionJob.objects.latest("id")
        assert trabajo.source_crs_code == "32719"
        assert trabajo.source_crs_origin == "declarado"

    def test_y_queda_escrito_quien_lo_declaro(self, sesion, libreta, usuario, con_ogr):
        """La traza del día en que alguien puso la obra en otro país."""
        sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(libreta), "formato": "gpkg", "crs_declarado": "32719", "perfil": ""},
        )
        trabajo = ConversionJob.objects.latest("id")
        mensajes = " ".join(e.message for e in trabajo.eventos.all())
        assert usuario.get_username() in mensajes
        assert "32719" in mensajes

    def test_un_epsg_que_no_existe_se_rechaza(self, sesion, libreta, con_ogr):
        """Se rechaza **sin tirar el archivo elegido**.

        Antes redirigía a la pantalla vacía con el mensaje arriba: el archivo se perdía, y una
        subida había que repetirla entera por un dígito mal tecleado. Ahora vuelve la pantalla
        con la ficha dentro, el error junto al campo y lo tecleado todavía puesto.
        """
        respuesta = sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(libreta), "formato": "gpkg", "crs_declarado": "999999", "perfil": ""},
        )
        assert ConversionJob.objects.count() == 0
        assert respuesta.status_code == 200, "no redirige: vuelve la ficha"
        cuerpo = respuesta.content.decode()
        assert 'id="error-crs"' in cuerpo, "el error va junto al campo del EPSG"
        assert "999999" in cuerpo
        assert 'value="999999"' in cuerpo, "lo tecleado se conserva"
        assert 'name="ruta"' in cuerpo and str(libreta) in cuerpo, "el archivo sigue elegido"

    def test_pulsar_un_programa_no_abre_el_ajuste_a_mano(self, sesion, libreta, con_ogr):
        """El desplegable de formato viaja en el mismo formulario **siempre**, también al pulsar
        un programa. Tomarlo por una elección abría «Ajustar a mano» a quien había pulsado
        «Civil 3D». Se vio en el navegador; ninguna prueba lo cazaba."""
        cuerpo = sesion.post(
            reverse("dashboard:encolar"),
            {
                "ruta": str(libreta),
                "formato": "shp",
                "crs_declarado": "999999",
                "perfil": "civil3d",
            },
        ).content.decode()
        assert "<details open>" not in cuerpo

    def test_convertir_a_mano_si_lo_deja_abierto(self, sesion, libreta, con_ogr):
        cuerpo = sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(libreta), "formato": "shp", "crs_declarado": "999999", "perfil": ""},
        ).content.decode()
        assert "<details open>" in cuerpo

    def test_lo_que_no_es_un_numero_se_rechaza(self, sesion, libreta, con_ogr):
        sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(libreta), "formato": "gpkg", "crs_declarado": "UTM 19 sur", "perfil": ""},
        )
        assert ConversionJob.objects.count() == 0

    def test_no_declarar_nada_no_impide_encolar(self, sesion, libreta, con_ogr):
        """Encolar sin CRS es legítimo: quien lo para, con su motivo y su explicación, es el
        runner. Rechazarlo aquí daría el mensaje en el sitio equivocado."""
        sesion.post(
            reverse("dashboard:encolar"),
            {"ruta": str(libreta), "formato": "gpkg", "perfil": ""},
        )
        assert ConversionJob.objects.count() == 1
