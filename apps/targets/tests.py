"""Los veredictos, contra el caso que origino la aplicacion.

La ortofoto de BHP abria en la maquina de quien la genero y no en la de al lado. La prueba
reconstruye ese archivo -- BigTIFF, cuatro bandas con alfa, EPSG:32719 -- en 400 bytes, y
comprueba que el veredicto de Civil 3D lo diga.
"""

import pytest

from apps.formats.deteccion import inspeccionar
from apps.formats.tests.constructor import bigtiff_minimo, geotiff_minimo
from apps.targets import perfiles


def _inspeccion(tmp_path, nombre, contenido):
    ruta = tmp_path / nombre
    ruta.write_bytes(contenido)
    return inspeccionar(ruta)


def _de(veredictos, perfil_id):
    return next(v for v in veredictos if v.perfil_id == perfil_id)


class TestElCasoDeBhp:
    """BigTIFF con alfa en UTM 19S: el archivo que no abria."""

    @pytest.fixture
    def ortofoto(self, tmp_path):
        contenido = bigtiff_minimo(bandas=4, alfa=True, compresion=5)
        return _inspeccion(tmp_path, "Cruce Minero.tif", contenido)

    def test_se_reconoce_como_bigtiff(self, ortofoto):
        assert ortofoto.codigo_formato == "bigtiff"
        assert ortofoto.crs.codigo == "32719"

    def test_civil3d_dice_que_no_abre_y_dice_por_que(self, ortofoto):
        veredicto = _de(perfiles.veredictos(ortofoto), "civil3d")
        assert veredicto.severidad == perfiles.NO_ABRE
        assert "BigTIFF" in veredicto.motivo
        # El remedio no es opcional: un veredicto sin salida es una queja.
        assert veredicto.remedio

    def test_qgis_y_arcgis_lo_abren(self, ortofoto):
        veredictos = perfiles.veredictos(ortofoto)
        assert _de(veredictos, "qgis").severidad == perfiles.ABRE
        assert _de(veredictos, "arcgis").severidad == perfiles.ABRE

    def test_el_aviso_dice_que_bigtiff_no_hacia_falta(self, ortofoto):
        assert any("sin necesitarlo" in aviso for aviso in ortofoto.avisos)

    def test_el_aviso_de_la_banda_alfa_esta(self, ortofoto):
        assert any("alfa" in aviso for aviso in ortofoto.avisos)


class TestElArchivoConvertido:
    """El mismo raster como TIFF clasico de tres bandas: lo que la aplicacion produce."""

    @pytest.fixture
    def convertido(self, tmp_path):
        return _inspeccion(tmp_path, "salida.tif", geotiff_minimo(bandas=3, compresion=5))

    def test_civil3d_lo_abre(self, convertido):
        veredicto = _de(perfiles.veredictos(convertido), "civil3d")
        assert veredicto.severidad == perfiles.ABRE

    def test_hay_un_veredicto_por_cada_perfil(self, convertido):
        veredictos = perfiles.veredictos(convertido)
        assert {v.perfil_id for v in veredictos} == set(perfiles.PERFILES)


class TestSinGeorreferencia:
    def test_un_tiff_sin_crs_abre_con_reparos_y_no_se_rechaza(self, tmp_path):
        """Convertir un raster sin georreferencia es legitimo. Negarlo convertiria la
        herramienta en un estorbo; callarlo la volveria peligrosa."""
        contenido = geotiff_minimo(bandas=3, epsg=None, escala_m=None, origen=None)
        inspeccion = _inspeccion(tmp_path, "sin_crs.tif", contenido)
        veredicto = _de(perfiles.veredictos(inspeccion), "civil3d")
        assert veredicto.severidad == perfiles.CON_REPAROS
        assert "referencia" in veredicto.motivo


class TestLosPerfilesHablanElIdiomaDelMotor:
    """La invariante que faltaba, y que costó un bug silencioso.

    Los perfiles se escribieron con las claves de GDAL —`COMPRESS`, `BLOCKXSIZE`— porque es
    lo que acaba en el comando. Pero el motor lee `compresion` y `tamano_tesela`, así que
    **el perfil no fijaba nada**: el trabajo salía con los valores por omisión, y el perfil
    de Civil 3D prometía descartar la banda alfa sin hacerlo.

    Es exactamente el fallo que la regla de «las opciones las declara el motor» existe para
    impedir. Esta prueba la hace cumplir.
    """

    def _declaradas_por_el_motor(self, codigo_destino: str) -> set[str]:
        from apps.engines.base import ParDeFormatos
        from apps.raster.motores import MotorEcw, MotorGdalRaster

        motor = MotorEcw() if codigo_destino == "ecw" else MotorGdalRaster()
        par = ParDeFormatos("geotiff", codigo_destino)
        # `bigtiff` es un ajuste interno del motor que el formulario no ofrece pero el plan
        # sí honra; se admite explícitamente para no obligar a exponerlo.
        return {o.nombre for o in motor.opciones(par)} | {"bigtiff"}

    @pytest.mark.parametrize("identificador", list(perfiles.PERFILES))
    def test_toda_opcion_de_un_perfil_la_entiende_el_motor(self, identificador):
        perfil = perfiles.PERFILES[identificador]
        if perfil.formato_destino not in ("geotiff", "bigtiff", "cog", "jp2", "img", "ecw"):
            pytest.skip(f"{perfil.formato_destino} lo sirve un motor de otra fase.")

        declaradas = self._declaradas_por_el_motor(perfil.formato_destino)
        desconocidas = set(perfil.opciones) - declaradas

        assert not desconocidas, (
            f"El perfil «{perfil.nombre}» fija {sorted(desconocidas)}, que el motor no lee. "
            f"El motor entiende: {sorted(declaradas)}."
        )

    def test_civil3d_de_verdad_descarta_la_banda_alfa(self):
        """La promesa concreta del perfil que originó todo."""
        assert perfiles.CIVIL3D.opciones["solo_rgb"] is True

    def test_civil3d_de_verdad_fuerza_el_tiff_clasico(self):
        assert perfiles.CIVIL3D.opciones["bigtiff"] == "NO"


class TestFormaDeLosVeredictos:
    def test_ninguno_se_apoya_solo_en_el_color(self, tmp_path):
        """Color + icono distinguible + texto. Uno de cada doce hombres no distingue el
        rojo del verde, y este producto se lee de un vistazo."""
        inspeccion = _inspeccion(tmp_path, "x.tif", bigtiff_minimo(bandas=4, alfa=True))
        for veredicto in perfiles.veredictos(inspeccion):
            assert veredicto.icono
            assert veredicto.etiqueta
            assert veredicto.motivo

    def test_cada_motivo_cabe_en_una_linea(self, tmp_path):
        """Y se comprueba sobre **varios** archivos, no sobre uno diminuto.

        Con un solo TIFF de juguete esta prueba pasaba por suerte: ninguna de las ramas que
        alargan el motivo —la ortofoto grande que hay que teselar, la libreta de puntos— se
        llegaba a ejecutar. Un motivo de 200 caracteres rompe la tira de veredictos, que es
        una línea por destino.
        """
        libreta = tmp_path / "control.csv"
        libreta.write_text(
            "P1,7318729.036,495279.406,3042.641,pr\nP2,7318700.292,495137.090,3045.004,pr\n",
            encoding="utf-8",
        )
        casos = [
            _inspeccion(tmp_path, "x.tif", bigtiff_minimo(bandas=4, alfa=True)),
            _inspeccion(tmp_path, "g.tif", bigtiff_minimo(ancho=14526, alto=14443, bandas=3)),
            _inspeccion(tmp_path, "s.tif", geotiff_minimo(bandas=3)),
            inspeccionar(libreta),
        ]
        for inspeccion in casos:
            for veredicto in perfiles.veredictos(inspeccion):
                assert len(veredicto.motivo) <= 120, (inspeccion.nombre, veredicto)


class TestUnaLibretaDePuntos:
    """El caso donde el veredicto tiene que decir lo contrario de lo obvio.

    Un PNEZD **lo abren** Civil 3D, QGIS y ArcGIS: es texto delimitado. Decir «no abre»
    sería falso, y decir «abre tal cual» sería tranquilizar a alguien justo antes del único
    paso donde se puede equivocar — elegir qué columna es cada coordenada.
    """

    @pytest.fixture
    def libreta(self, tmp_path):
        ruta = tmp_path / "control.csv"
        ruta.write_text(
            "P1,7318729.036,495279.406,3042.641,pr\n"
            "P2,7318700.292,495137.090,3045.004,pr\n"
            "P3,7318656.894,495192.496,3046.322,pr\n",
            encoding="utf-8",
        )
        return inspeccionar(ruta)

    def test_civil3d_no_dice_que_no_abre(self, libreta):
        """Es su formato nativo de puntos. Decir que no lo abre sería absurdo."""
        assert _de(perfiles.veredictos(libreta), "civil3d").severidad == perfiles.CON_REPAROS

    def test_y_su_remedio_es_landxml(self, libreta):
        """No DXF, que también se podría: en LandXML no hay lista de formatos que elegir."""
        assert "LandXML" in _de(perfiles.veredictos(libreta), "civil3d").remedio

    def test_qgis_y_arcgis_tampoco_dicen_que_no(self, libreta):
        for identificador in ("qgis", "arcgis"):
            veredicto = _de(perfiles.veredictos(libreta), identificador)
            assert veredicto.severidad == perfiles.CON_REPAROS, identificador
            assert "orden de columnas" in veredicto.motivo

    def test_el_remedio_es_el_destino_que_ofrece_el_boton(self, libreta):
        """Antes se leía `formato_destino` a secas y el veredicto de QGIS decía «convertir a
        Cloud Optimized GeoTIFF» —un ráster, a partir de un archivo de texto— mientras el
        botón de al lado ofrecía GeoPackage. Dos respuestas en la misma pantalla."""
        assert "GeoPackage" in _de(perfiles.veredictos(libreta), "qgis").remedio
        assert "Shapefile" in _de(perfiles.veredictos(libreta), "arcgis").remedio
        assert "GeoJSON" in _de(perfiles.veredictos(libreta), "web").remedio

    def test_ninguno_promete_que_abre_tal_cual(self, libreta):
        for veredicto in perfiles.veredictos(libreta):
            assert veredicto.severidad != perfiles.ABRE, veredicto


class TestGoogleEarthDiceLasTresCondiciones:
    """Son tres —KMZ, EPSG:4326 y teselar— y normalmente se descubren de una en una."""

    def test_avisa_de_la_reproyeccion(self, tmp_path):
        inspeccion = _inspeccion(tmp_path, "orto.tif", bigtiff_minimo(bandas=3))
        assert "EPSG:4326" in _de(perfiles.veredictos(inspeccion), "google-earth").remedio

    def test_avisa_de_teselar_solo_cuando_la_imagen_es_grande(self, tmp_path):
        """Una ortofoto de 210 Mpx en una sola superposición se ve borrosa entera: Google
        Earth la remuestrea a la textura que admita la tarjeta."""
        grande = _inspeccion(
            tmp_path, "grande.tif", bigtiff_minimo(ancho=14526, alto=14443, bandas=3)
        )
        assert "teselar" in _de(perfiles.veredictos(grande), "google-earth").remedio

        pequena = _inspeccion(tmp_path, "chica.tif", bigtiff_minimo(ancho=100, alto=100))
        assert "teselar" not in _de(perfiles.veredictos(pequena), "google-earth").remedio
