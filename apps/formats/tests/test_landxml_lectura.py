"""El lector de LandXML: qué trae dentro un archivo del proyectista.

**No hay ningún LandXML real con el que contrastar**: se buscó en la unidad entera y no
aparece ninguno. Así que las pruebas se apoyan en dos cosas honestas:

1. Un archivo **escrito a mano** contra la especificación 1.2, con las tres cosas que puede
   traer —puntos, una superficie y un alineamiento— y con las cifras a la vista.
2. La **ida y vuelta** contra nuestro propio escritor, que sí prueba algo: lo que
   `apps/vector/landxml.py` escribe se vuelve a leer con los mismos números.

Lo que **no** se prueba aquí, porque no se puede: que un LandXML de Civil 3D se lea bien.
Contar `<Surface>` y `<Alignment>` es inequívoco y por eso se hace; interpretar el
triangulado no lo es, y por eso no se hace todavía.
"""

from datetime import UTC, datetime

import pytest

from apps.formats import landxml
from apps.formats import puntos as puntos_mod
from apps.vector import landxml as escritor

#: Un LandXML con las tres cosas dentro. Las cifras están a la vista: 3 puntos, una
#: superficie de 4 vértices y 2 caras, y un alineamiento de 1.250,5 m.
COMPLETO = """<?xml version="1.0" encoding="UTF-8"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2">
  <Units><Metric linearUnit="meter" /></Units>
  <CoordinateSystem epsgCode="32719" name="WGS 84 / UTM zone 19S" />
  <Application name="Civil 3D" />
  <CgPoints name="Control">
    <CgPoint name="P1" code="pr">7318729.036 495279.406 3042.641</CgPoint>
    <CgPoint name="P2" code="pr">7318700.292 495137.090 3045.004</CgPoint>
    <CgPoint name="P3">7318656.894 495192.496 3046.322</CgPoint>
  </CgPoints>
  <Surfaces>
    <Surface name="Terreno natural">
      <Definition surfType="TIN">
        <Pnts>
          <P id="1">7318700 495100 3040</P>
          <P id="2">7318700 495200 3041</P>
          <P id="3">7318800 495100 3042</P>
          <P id="4">7318800 495200 3043</P>
        </Pnts>
        <Faces>
          <F>1 2 3</F>
          <F>2 4 3</F>
        </Faces>
      </Definition>
    </Surface>
  </Surfaces>
  <Alignments>
    <Alignment name="Eje camino" length="1250.5" staStart="0" />
  </Alignments>
</LandXML>
"""


def _escribir(tmp_path, contenido, nombre="proyecto.xml"):
    ruta = tmp_path / nombre
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


@pytest.fixture
def leido(tmp_path):
    return landxml.leer_cabecera(_escribir(tmp_path, COMPLETO))


class TestQueTraeDentro:
    def test_cuenta_los_puntos(self, leido):
        assert leido.puntos_leidos == 3

    def test_cuenta_las_superficies_con_sus_vertices_y_caras(self, leido):
        """Contar etiquetas es inequívoco; interpretar el triangulado no lo es."""
        assert len(leido.superficies) == 1
        superficie = leido.superficies[0]
        assert superficie.nombre == "Terreno natural"
        assert superficie.puntos == 4
        assert superficie.caras == 2

    def test_no_cuenta_dos_veces(self, leido):
        """Con eventos `start` y `end` cada elemento llega dos veces. Contar sin mirar el
        evento daría 8 vértices y 4 caras — cifras plausibles que nadie comprobaría."""
        assert leido.superficies[0].caras == 2

    def test_los_vertices_de_la_superficie_no_son_puntos_del_archivo(self, leido):
        """Los `<P>` de un TIN son la malla, no topografía. Sumarlos a los `CgPoint` daría
        7 puntos y convertiría la nube de vértices en puntos de control."""
        assert leido.puntos_leidos == 3

    def test_cuenta_los_alineamientos(self, leido):
        assert len(leido.alineamientos) == 1
        assert leido.alineamientos[0].nombre == "Eje camino"
        assert leido.alineamientos[0].longitud_m == pytest.approx(1250.5)

    def test_lee_el_sistema_de_referencia(self, leido):
        assert leido.epsg == "32719"
        assert "UTM zone 19S" in leido.nombre_crs

    def test_dice_quien_lo_escribio(self, leido):
        """Un `Application name="Civil 3D"` dice mucho de qué esperar del archivo."""
        assert leido.aplicacion == "Civil 3D"

    def test_lee_el_nombre_del_grupo_de_puntos(self, leido):
        assert leido.grupos_de_puntos == ("Control",)

    def test_el_resumen_cabe_en_una_linea(self, leido):
        assert leido.resumen == "3 puntos · 1 superficie(s) con 2 caras · 1 alineamiento(s)"


class TestLasCoordenadas:
    def test_el_contenido_es_norte_este_cota(self, leido):
        """La misma trampa que en PNEZD y en el mismo sitio."""
        primero = leido.muestra[0]
        assert primero.norte_m == pytest.approx(7318729.036)
        assert primero.este_m == pytest.approx(495279.406)
        assert primero.cota_m == pytest.approx(3042.641)

    def test_conserva_el_numero_y_la_descripcion(self, leido):
        assert leido.muestra[0].identificador == "P1"
        assert leido.muestra[0].descripcion == "pr"

    def test_un_punto_sin_descripcion_no_inventa_una(self, leido):
        assert leido.muestra[2].descripcion == ""

    def test_la_extension_es_de_metros_no_de_millones(self, leido):
        """Si el orden estuviera invertido, saldría de millones. Delata la lectura mala sin
        mirar el orden."""
        norte, este, _ = leido.extension_m
        assert norte < 200
        assert este < 200


class TestSoloConLoQueNoSeConvierte:
    """El caso que hay que decir en voz alta: se reconoce, se sabe qué trae, y no hay
    conversión que ofrecer."""

    @pytest.fixture
    def solo_superficie(self, tmp_path):
        sin_puntos = COMPLETO.replace(
            COMPLETO[COMPLETO.index("  <CgPoints") : COMPLETO.index("  <Surfaces>")], ""
        )
        return landxml.leer_cabecera(_escribir(tmp_path, sin_puntos, "superficie.xml"))

    def test_no_trae_puntos(self, solo_superficie):
        assert solo_superficie.tiene_puntos is False

    def test_y_se_puede_preguntar(self, solo_superficie):
        assert solo_superficie.solo_trae_lo_que_no_se_convierte is True

    def test_pero_sigue_diciendo_que_hay_dentro(self, solo_superficie):
        assert "superficie" in solo_superficie.resumen
        assert "alineamiento" in solo_superficie.resumen

    def test_un_archivo_con_puntos_no_entra_en_ese_caso(self, leido):
        assert leido.solo_trae_lo_que_no_se_convierte is False


class TestLaIdaYLaVuelta:
    """Lo que nuestro escritor produce, leído de vuelta con los mismos números.

    Es un oráculo débil —el código contra sí mismo— y por eso no sustituye a abrirlo en
    Civil 3D. Pero sí atrapa lo que se rompe de verdad al tocar cualquiera de los dos: que
    uno escriba norte-este y el otro lea este-norte.
    """

    def test_los_puntos_vuelven_iguales(self, tmp_path):
        origen = tmp_path / "libreta.csv"
        origen.write_text(
            "P1,7318729.036,495279.406,3042.641,pr\nP2,7318700.292,495137.090,3045.004,mo\n",
            encoding="utf-8",
        )
        destino = tmp_path / "salida.xml"
        escritor.escribir(
            puntos_mod.iterar(origen),
            destino,
            epsg="32719",
            cuando=datetime(2026, 1, 1, tzinfo=UTC),
        )

        vuelta = landxml.leer_cabecera(destino)
        assert vuelta.puntos_leidos == 2
        assert vuelta.epsg == "32719"
        assert vuelta.muestra[0].norte_m == pytest.approx(7318729.036)
        assert vuelta.muestra[0].este_m == pytest.approx(495279.406)
        assert vuelta.muestra[1].descripcion == "mo"

    def test_el_iterador_recorre_los_mismos(self, tmp_path):
        origen = tmp_path / "libreta.csv"
        origen.write_text("P1,7318729.036,495279.406,3042.641,pr\n" * 4, encoding="utf-8")
        destino = tmp_path / "salida.xml"
        escritor.escribir(puntos_mod.iterar(origen), destino, epsg="32719")

        recorridos = list(landxml.iterar_puntos(destino))
        assert len(recorridos) == 4
        assert recorridos[0].norte_m == pytest.approx(7318729.036)


class TestLoQueNoEsUnLandXml:
    def test_un_xml_de_otra_cosa(self, tmp_path):
        with pytest.raises(landxml.NoEsLandXml):
            landxml.leer_cabecera(_escribir(tmp_path, "<recibo><total>3</total></recibo>"))

    def test_un_xml_roto(self, tmp_path):
        with pytest.raises(landxml.NoEsLandXml):
            landxml.leer_cabecera(_escribir(tmp_path, "<LandXML><CgPoints>"))

    def test_una_bomba_de_entidades_no_se_expande(self, tmp_path):
        """El archivo lo escribió otro programa y lo mandó otra oficina.

        Con `xml.etree` de la biblioteca estándar, estas pocas líneas de DTD se comen la
        memoria de la máquina antes de que nadie haya decidido nada sobre el archivo.
        `defusedxml` se niega en vez de expandirlas.
        """
        bomba = (
            '<?xml version="1.0"?>\n'
            "<!DOCTYPE LandXML [\n"
            '  <!ENTITY a "aaaaaaaaaa">\n'
            '  <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">\n'
            '  <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">\n'
            "]>\n"
            "<LandXML><CgPoints><CgPoint>&c;</CgPoint></CgPoints></LandXML>\n"
        )
        with pytest.raises(Exception) as fallo:  # noqa: B017 - defusedxml levanta lo suyo
            landxml.leer_cabecera(_escribir(tmp_path, bomba, "bomba.xml"))
        assert "Entit" in type(fallo.value).__name__ or isinstance(fallo.value, landxml.NoEsLandXml)
