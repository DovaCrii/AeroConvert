"""Los motores vectoriales, probados por el comando que construyen.

Es la capa 1 del plan de pruebas: sin OGR instalado, comparando el `argv` contra el que se
esperaba. Suena poco, y es donde están los errores caros — los tres que se cobraron una
tarde en esta fase salieron todos de aquí:

1. `-a_srs` y `-t_srs` juntos. `ogr2ogr` los rechaza y no convierte nada.
2. Un KML sin reproyectar. Ese sí convierte, y deja la obra fuera del planeta.
3. `GDAL_DATA` sin poner. El controlador DXF no arranca.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from apps.engines.base import ParDeFormatos
from apps.formats import puntos as puntos_mod
from apps.vector import motores

CRUCE_MINERO = """P1,7318729.036,495279.406,3042.641,pr
P2,7318700.292,495137.090,3045.004,pr
P3,7318656.894,495192.496,3046.322,pr
P4,7318609.156,495087.401,3045.287,pr
P5,7318567.524,495195.695,3045.963,pr
"""


@dataclass
class TrabajoDeMentira:
    """Lo justo que `plan()` mira. Un modelo de verdad ataría la prueba a la base."""

    source_path: str
    output_path: str
    target_format_code: str
    source_crs_authority: str = "EPSG"
    source_crs_code: str = "32719"
    target_crs_authority: str = ""
    target_crs_code: str = ""
    source_size_bytes: int = 195
    options: dict = field(default_factory=dict)


@pytest.fixture
def libreta(tmp_path):
    ruta = tmp_path / "puntos control cruce minero.csv"
    ruta.write_text(CRUCE_MINERO, encoding="utf-8")
    return ruta


def _trabajo(libreta, tmp_path, formato, **extra):
    extensiones = {"gpkg": ".gpkg", "shp": ".shp", "kml": ".kml", "dxf": ".dxf"}
    return TrabajoDeMentira(
        source_path=str(libreta),
        output_path=str(tmp_path / f"control{extensiones[formato]}"),
        target_format_code=formato,
        **extra,
    )


def _pares(argv, bandera):
    """Todos los valores que acompañan a esa bandera. `-oo` aparece ocho veces."""
    return [argv[i + 1] for i, x in enumerate(argv) if x == bandera and i + 1 < len(argv)]


class TestElComandoDeUnaLibreta:
    @pytest.fixture
    def argv(self, libreta, tmp_path):
        return motores.MotorPuntosTopograficos().plan(_trabajo(libreta, tmp_path, "gpkg")).argv

    def test_le_dice_a_ogr_que_columna_es_cada_cosa(self, argv):
        """El dato que resuelve el problema: el este es la tercera columna y el norte la
        segunda. Lo deduce `apps.formats.puntos` del rango UTM."""
        opciones = _pares(argv, "-oo")
        assert "X_POSSIBLE_NAMES=field_3" in opciones
        assert "Y_POSSIBLE_NAMES=field_2" in opciones
        assert "Z_POSSIBLE_NAMES=field_4" in opciones

    def test_no_deja_el_este_y_el_norte_tambien_como_texto(self, argv):
        """Sin `KEEP_GEOM_COLUMNS=NO` el mismo dato sale dos veces, y en un DXF eso son
        etiquetas encima de cada punto."""
        assert "KEEP_GEOM_COLUMNS=NO" in _pares(argv, "-oo")

    def test_dice_que_no_hay_encabezado(self, argv):
        assert "HEADERS=NO" in _pares(argv, "-oo")

    def test_renombra_las_columnas_que_sobreviven(self, argv):
        """`field_1` y `field_5` no es lo que se le manda a un cliente."""
        consulta = _pares(argv, "-sql")[0]
        assert f"AS {motores.CAMPO_PUNTO}" in consulta
        assert f"AS {motores.CAMPO_DESCRIPCION}" in consulta

    def test_la_capa_del_csv_se_cita_entre_comillas(self, argv):
        """Su nombre es el del archivo sin extensión, y lleva espacios muy a menudo."""
        assert '"puntos control cruce minero"' in _pares(argv, "-sql")[0]

    def test_una_comilla_en_el_nombre_del_archivo_no_rompe_la_consulta(self):
        """El nombre del archivo lo elige quien usa la aplicación.

        En Windows no se puede poner una comilla doble en un nombre —de ahí que esto llame
        a la función y no escriba un archivo— pero en Linux sí, y ahí corre el gate. Un
        `foo".csv` cerraría la cita y dejaría el resto del nombre como SQL. No es una base
        de datos, es el SQL de OGR; pero el resultado sería una consulta distinta de la
        pedida: una conversión que devuelve otras columnas sin avisar.
        """
        campos = puntos_mod.CamposOgr(
            delimitador=",",
            tiene_encabezado=False,
            orden="pnezd",
            campo_este="field_3",
            campo_norte="field_2",
            campo_cota="field_4",
            campo_punto="field_1",
            campo_descripcion="field_5",
        )
        consulta = motores.MotorPuntosTopograficos()._renombrado(Path('raro".csv'), campos)
        # La comilla va doblada, que es como se escapa dentro de un identificador citado.
        assert 'FROM "raro"""' in consulta

    def test_solo_entran_en_el_sql_los_nombres_que_generamos(self):
        assert motores._es_campo_generado("field_3") is True
        assert motores._es_campo_generado("Norte") is False
        assert motores._es_campo_generado('x" OR 1=1') is False
        assert motores._es_campo_generado("") is False

    def test_escribe_en_el_parcial_y_no_en_el_destino(self, argv, tmp_path):
        assert str(tmp_path / "control.parcial.gpkg") in argv
        assert str(tmp_path / "control.gpkg") not in argv

    def test_el_nombre_de_capa_va_limpio(self, argv):
        assert "-nln" in argv
        assert argv[argv.index("-nln") + 1] == "control"


class TestLosDosSistemasDeReferencia:
    """El fallo 1 y el 2 de la cabecera del módulo, cada uno con su prueba."""

    def test_sin_reproyectar_se_etiqueta(self, libreta, tmp_path):
        argv = motores.MotorPuntosTopograficos().plan(_trabajo(libreta, tmp_path, "gpkg")).argv
        assert "-a_srs" in argv
        assert argv[argv.index("-a_srs") + 1] == "EPSG:32719"
        assert "-t_srs" not in argv

    def test_a_kml_se_reproyecta_a_4326(self, libreta, tmp_path):
        """El controlador escribe las coordenadas tal cual se le den. Un KML con estes y
        nortes UTM dentro es válido, abre en Google Earth, y pone la obra fuera del
        planeta: los números se leen como grados."""
        argv = motores.MotorPuntosTopograficos().plan(_trabajo(libreta, tmp_path, "kml")).argv
        assert argv[argv.index("-t_srs") + 1] == "EPSG:4326"
        assert argv[argv.index("-s_srs") + 1] == "EPSG:32719"

    def test_y_nunca_los_dos_a_la_vez(self, libreta, tmp_path):
        """`ogr2ogr` responde «Argument '-t_srs' not allowed with '-a_srs'» y no convierte
        nada. Pasó con KML."""
        for formato in ("gpkg", "shp", "kml", "dxf"):
            argv = motores.MotorPuntosTopograficos().plan(_trabajo(libreta, tmp_path, formato)).argv
            assert not ("-a_srs" in argv and "-t_srs" in argv), formato

    def test_sin_crs_no_se_etiqueta_nada(self, libreta, tmp_path):
        """Que no haya CRS lo para el runner. Si llegara aquí, el comando no debe inventarlo."""
        argv = (
            motores.MotorPuntosTopograficos()
            .plan(_trabajo(libreta, tmp_path, "gpkg", source_crs_code=""))
            .argv
        )
        assert "-a_srs" not in argv
        assert "-t_srs" not in argv


class TestElOrdenSeRespeta:
    def test_lo_elegido_a_mano_manda_sobre_lo_deducido(self, libreta, tmp_path):
        """La salida cuando el detector se equivoca. Con `penzd`, el este pasa a ser la
        segunda columna y el norte la tercera — intercambiados respecto de lo deducido."""
        argv = (
            motores.MotorPuntosTopograficos()
            .plan(_trabajo(libreta, tmp_path, "gpkg", options={"orden": "penzd"}))
            .argv
        )
        opciones = _pares(argv, "-oo")
        assert "X_POSSIBLE_NAMES=field_2" in opciones
        assert "Y_POSSIBLE_NAMES=field_3" in opciones

    def test_el_formulario_ofrece_todos_los_ordenes(self):
        opcion = motores.MotorPuntosTopograficos().opciones(ParDeFormatos("puntos", "gpkg"))[0]
        assert opcion.nombre == "orden"
        assert {codigo for codigo, _ in opcion.elecciones} == set(puntos_mod.ORDENES)


class TestElEncabezado:
    def test_con_encabezado_no_se_renombra_nada(self, tmp_path):
        """Los rótulos los puso quien hizo el archivo; no se le cambian los nombres a los
        datos de otro."""
        ruta = tmp_path / "con_rotulos.csv"
        ruta.write_text("Punto,Norte,Este,Cota,Desc\n" + CRUCE_MINERO, encoding="utf-8")
        argv = motores.MotorPuntosTopograficos().plan(_trabajo(ruta, tmp_path, "gpkg")).argv

        assert "HEADERS=YES" in _pares(argv, "-oo")
        assert "-sql" not in argv
        assert "X_POSSIBLE_NAMES=Este" in _pares(argv, "-oo")
        assert "Y_POSSIBLE_NAMES=Norte" in _pares(argv, "-oo")


class TestElEntornoDelHijo:
    """El fallo 3: sin `GDAL_DATA` el controlador DXF no arranca."""

    def test_el_plan_lleva_entorno(self, libreta, tmp_path, settings):
        settings.GDAL_BIN = ""
        plan = motores.MotorPuntosTopograficos().plan(_trabajo(libreta, tmp_path, "dxf"))
        # Sin carpeta configurada no hay nada que poner, y eso es correcto: inventar una
        # ruta haría que GDAL dejara de buscar por su cuenta.
        assert plan.env == {}

    def test_con_carpeta_de_binarios_se_busca_por_archivo_testigo(self, tmp_path, settings):
        """Y no por la existencia de la carpeta: una `share/gdal` vacía existe y no sirve."""
        from apps.engines import entorno

        binarios = tmp_path / "bin"
        binarios.mkdir()
        vacia = tmp_path / "share" / "gdal"
        vacia.mkdir(parents=True)

        settings.GDAL_BIN = str(binarios)
        assert "GDAL_DATA" not in entorno.entorno_de_gdal()

        (vacia / entorno.TESTIGO_GDAL).write_text("x", encoding="utf-8")
        assert entorno.entorno_de_gdal()["GDAL_DATA"] == str(vacia.resolve())

    def test_lo_que_anade_el_motor_puede_sobrescribir(self, settings):
        from apps.engines import entorno

        settings.GDAL_BIN = ""
        assert entorno.entorno_de_gdal(GDAL_CACHEMAX="512")["GDAL_CACHEMAX"] == "512"


class TestLaMatriz:
    def test_una_libreta_de_puntos_declara_sus_destinos(self):
        pares = motores.MotorPuntosTopograficos().pares()
        assert ParDeFormatos("puntos", "gpkg") in pares
        assert ParDeFormatos("puntos", "kml") in pares
        # Nunca a sí mismo, y nunca a lo que el catálogo dice que no se escribe.
        assert ParDeFormatos("puntos", "puntos") not in pares
        assert ParDeFormatos("puntos", "dwg") not in pares

    def test_el_motor_general_no_convierte_un_formato_en_si_mismo(self):
        for par in motores.MotorOgrVector().pares():
            assert par.origen != par.destino

    def test_todo_destino_declarado_tiene_controlador(self):
        """Un par declarado sin controlador daría un `-f GPKG` silencioso hacia otro
        formato: el trabajo diría «hecho» y el archivo sería de otro tipo."""
        for motor in (motores.MotorPuntosTopograficos(), motores.MotorOgrVector()):
            for par in motor.pares():
                assert par.destino in motores.CONTROLADOR, f"{motor.id}: {par}"

    def test_los_controladores_son_los_nombres_cortos_de_ogr(self):
        """`ESRI Shapefile` lleva espacio, y es así como lo espera `-f`."""
        assert motores.CONTROLADOR["shp"] == "ESRI Shapefile"


class TestElMotorDeLandXml:
    def _trabajo_landxml(self, libreta, tmp_path, **extra):
        return TrabajoDeMentira(
            source_path=str(libreta),
            output_path=str(tmp_path / "control.xml"),
            target_format_code="landxml",
            **extra,
        )

    def test_esta_disponible_sin_nada_instalado(self):
        """Es la única celda verde de la matriz que no necesita nada en la máquina, y eso
        es parte de su valor: funciona en una VM pelada."""
        assert motores.MotorLandXml().disponibilidad().disponible is True

    def test_corre_como_proceso_hijo_y_no_como_llamada(self, libreta, tmp_path):
        """No es ceremonia: es lo que permite cancelarlo, ponerle presupuesto de tiempo, y
        que un archivo enorme que agote la memoria no se lleve por delante el servidor."""
        plan = motores.MotorLandXml().plan(self._trabajo_landxml(libreta, tmp_path))
        assert plan.argv[0] == sys.executable
        assert plan.argv[1:3] == ("-m", "apps.vector.landxml")

    def test_arranca_en_la_raiz_del_repositorio(self, libreta, tmp_path):
        """`-m` resuelve el paquete desde el directorio de trabajo: en cualquier otro sitio
        el hijo no encontraría `apps` y fallaría con un ImportError sin relación aparente."""
        from django.conf import settings

        plan = motores.MotorLandXml().plan(self._trabajo_landxml(libreta, tmp_path))
        assert plan.cwd == Path(settings.BASE_DIR)

    def test_escribe_en_el_parcial(self, libreta, tmp_path):
        plan = motores.MotorLandXml().plan(self._trabajo_landxml(libreta, tmp_path))
        assert str(tmp_path / "control.parcial.xml") in plan.argv

    def test_le_pasa_el_epsg_y_el_orden(self, libreta, tmp_path):
        plan = motores.MotorLandXml().plan(
            self._trabajo_landxml(libreta, tmp_path, options={"orden": "penzd"})
        )
        assert plan.argv[plan.argv.index("--epsg") + 1] == "32719"
        assert plan.argv[plan.argv.index("--orden") + 1] == "penzd"

    def test_ofrece_el_orden_y_el_nombre_del_grupo(self):
        nombres = {
            o.nombre for o in motores.MotorLandXml().opciones(ParDeFormatos("puntos", "landxml"))
        }
        assert nombres == {"orden", "grupo"}

    def test_solo_declara_el_par_que_sabe_hacer(self):
        assert motores.MotorLandXml().pares() == frozenset({ParDeFormatos("puntos", "landxml")})

    def test_un_landxml_sin_puntos_no_pasa_la_verificacion(self, libreta, tmp_path):
        """Es un archivo válido y bien formado que Civil 3D abre sin protestar y sin
        enseñar nada. Creerle al código de salida es el error más caro que hay aquí."""
        vacio = tmp_path / "vacio.xml"
        vacio.write_text(
            '<?xml version="1.0"?><LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2">'
            "<CgPoints/></LandXML>",
            encoding="utf-8",
        )
        veredicto = motores.MotorLandXml().verificar(
            self._trabajo_landxml(libreta, tmp_path), vacio
        )
        assert veredicto.correcta is False
        assert veredicto.codigo_motivo == "salida-invalida"

    def test_un_xml_a_medias_no_pasa(self, libreta, tmp_path):
        """Pasa si el proceso muere a mitad de escritura. El parcial existe y tiene bytes."""
        roto = tmp_path / "roto.xml"
        roto.write_text("<LandXML><CgPoints><CgPoint>1 2 3</CgPoint>", encoding="utf-8")
        veredicto = motores.MotorLandXml().verificar(self._trabajo_landxml(libreta, tmp_path), roto)
        assert veredicto.correcta is False
        assert "bien formado" in veredicto.motivo


class TestLaVerificacion:
    def test_un_archivo_sin_entidades_no_pasa(self, libreta, tmp_path, monkeypatch):
        """`ogr2ogr` devuelve 0 y escribe un GPKG de 98 KB perfectamente válido y
        completamente vacío cuando el `X_POSSIBLE_NAMES` no coincidió con ninguna columna.
        Creerle al código de salida es el error más caro que hay aquí."""
        salida = tmp_path / "vacio.gpkg"
        salida.write_bytes(b"x" * 100)
        monkeypatch.setattr(motores, "_ogrinfo", lambda ruta: {"layers": [{"featureCount": 0}]})

        veredicto = motores.MotorPuntosTopograficos().verificar(
            _trabajo(libreta, tmp_path, "gpkg"), salida
        )
        assert veredicto.correcta is False
        assert veredicto.codigo_motivo == "salida-invalida"
        assert "orden de columnas" in veredicto.motivo

    def test_con_entidades_pasa_y_anota_el_epsg(self, libreta, tmp_path, monkeypatch):
        salida = tmp_path / "bien.gpkg"
        salida.write_bytes(b"x" * 100)
        monkeypatch.setattr(
            motores,
            "_ogrinfo",
            lambda ruta: {
                "driverShortName": "GPKG",
                "layers": [
                    {
                        "featureCount": 5,
                        "geometryFields": [
                            {
                                "type": "PointZ",
                                "coordinateSystem": {"wkt": 'ID["EPSG",32719]'},
                            }
                        ],
                    }
                ],
            },
        )

        veredicto = motores.MotorPuntosTopograficos().verificar(
            _trabajo(libreta, tmp_path, "gpkg"), salida
        )
        assert veredicto.correcta is True
        assert veredicto.detalles["entidades"] == 5
        assert veredicto.detalles["epsg"] == "32719"

    def test_si_ogr_no_puede_leer_su_propia_salida_no_pasa(self, libreta, tmp_path, monkeypatch):
        salida = tmp_path / "roto.gpkg"
        salida.write_bytes(b"x" * 100)
        monkeypatch.setattr(motores, "_ogrinfo", lambda ruta: None)

        veredicto = motores.MotorPuntosTopograficos().verificar(
            _trabajo(libreta, tmp_path, "gpkg"), salida
        )
        assert veredicto.correcta is False

    def test_el_archivo_que_no_existe_se_detecta_antes(self, libreta, tmp_path):
        veredicto = motores.MotorPuntosTopograficos().verificar(
            _trabajo(libreta, tmp_path, "gpkg"), Path(tmp_path / "no_esta.gpkg")
        )
        assert veredicto.correcta is False
        assert veredicto.codigo_motivo == "sin-salida"
