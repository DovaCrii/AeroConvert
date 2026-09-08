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
        inspeccion = _inspeccion(tmp_path, "x.tif", bigtiff_minimo(bandas=4, alfa=True))
        for veredicto in perfiles.veredictos(inspeccion):
            assert len(veredicto.motivo) <= 120, veredicto
