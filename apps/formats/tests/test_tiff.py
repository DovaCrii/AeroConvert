"""El lector de cabecera TIFF, contra archivos escritos byte a byte en la prueba misma."""

import struct

import pytest

from apps.formats import tiff

from .constructor import ConstructorTiff, bigtiff_minimo, geotiff_minimo


def _escribir(tmp_path, nombre, contenido):
    ruta = tmp_path / nombre
    ruta.write_bytes(contenido)
    return ruta


class TestVariante:
    """Lo que separa un TIFF clasico de un BigTIFF es un byte, y de ese byte depende que
    el archivo abra o no en Civil 3D. Es el diagnostico principal del producto."""

    def test_el_clasico_se_reconoce_como_clasico(self, tmp_path):
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "c.tif", geotiff_minimo()))
        assert cabecera.es_bigtiff is False

    def test_el_bigtiff_se_reconoce_como_bigtiff(self, tmp_path):
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "b.tif", bigtiff_minimo()))
        assert cabecera.es_bigtiff is True

    def test_los_dos_declaran_lo_mismo_salvo_la_variante(self, tmp_path):
        """Se construyen con los mismos parametros: cualquier diferencia que no sea la
        variante es un fallo del lector en una de las dos ramas.

        Es la prueba que importa, porque en BigTIFF los tres anchos de campo valen 8 y en
        el clasico valen 2, 4 y 4. Un error ahi pasa desapercibido con BigTIFF."""
        clasico = tiff.leer_cabecera(_escribir(tmp_path, "c.tif", geotiff_minimo()))
        grande = tiff.leer_cabecera(_escribir(tmp_path, "b.tif", bigtiff_minimo()))

        for atributo in (
            "ancho_px",
            "alto_px",
            "bandas",
            "bits_por_muestra",
            "compresion",
            "fotometria",
            "epsg",
            "escala_pixel",
            "origen",
        ):
            assert getattr(clasico, atributo) == getattr(grande, atributo), atributo

    def test_una_marca_de_version_desconocida_se_rechaza(self, tmp_path):
        datos = bytearray(geotiff_minimo())
        struct.pack_into("<H", datos, 2, 99)
        with pytest.raises(tiff.NoEsTiff, match="99"):
            tiff.leer_cabecera(_escribir(tmp_path, "raro.tif", bytes(datos)))

    def test_lo_que_no_empieza_por_II_ni_MM_no_es_tiff(self, tmp_path):
        with pytest.raises(tiff.NoEsTiff):
            tiff.leer_cabecera(_escribir(tmp_path, "x.tif", b"\x89PNG\r\n\x1a\n" + bytes(64)))

    def test_un_archivo_de_tres_bytes_no_revienta(self, tmp_path):
        with pytest.raises(tiff.NoEsTiff):
            tiff.leer_cabecera(_escribir(tmp_path, "x.tif", b"II*"))


class TestCampos:
    def test_lee_dimensiones_y_bandas(self, tmp_path):
        contenido = geotiff_minimo(ancho=7, alto=5, bandas=3)
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "x.tif", contenido))
        assert (cabecera.ancho_px, cabecera.alto_px, cabecera.bandas) == (7, 5, 3)
        assert cabecera.megapixeles == pytest.approx(35 / 1_000_000)

    def test_detecta_la_banda_alfa(self, tmp_path):
        con = tiff.leer_cabecera(_escribir(tmp_path, "a.tif", geotiff_minimo(bandas=4, alfa=True)))
        sin = tiff.leer_cabecera(_escribir(tmp_path, "b.tif", geotiff_minimo(bandas=3)))
        assert con.tiene_alfa is True
        assert sin.tiene_alfa is False

    def test_nombra_la_compresion(self, tmp_path):
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "x.tif", geotiff_minimo(compresion=5)))
        assert cabecera.nombre_compresion == "LZW"

    def test_una_compresion_desconocida_no_miente(self, tmp_path):
        """Inventar un nombre seria peor que decir el numero."""
        cabecera = tiff.leer_cabecera(
            _escribir(tmp_path, "x.tif", geotiff_minimo(compresion=61000))
        )
        assert cabecera.nombre_compresion == "codigo 61000"

    def test_sin_teselas_reporta_franjas(self, tmp_path):
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "x.tif", geotiff_minimo(alto=4)))
        assert cabecera.teselado is False
        assert cabecera.filas_por_franja == 4


class TestGeorreferencia:
    def test_saca_el_epsg_de_las_geoclaves(self, tmp_path):
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "x.tif", geotiff_minimo(epsg=32719)))
        assert cabecera.epsg == 32719

    def test_sin_geoclaves_el_epsg_es_none_y_no_se_inventa(self, tmp_path):
        contenido = ConstructorTiff().raster(epsg=None, escala_m=None, origen=None).bytes()
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "x.tif", contenido))
        assert cabecera.epsg is None
        assert cabecera.escala_pixel is None
        assert cabecera.gsd_cm is None

    def test_el_valor_32767_no_es_un_epsg(self, tmp_path):
        """32767 significa «definido por el usuario» en GeoTIFF. Tomarlo por un codigo
        daria un EPSG que no existe y una reproyeccion a ninguna parte."""
        constructor = ConstructorTiff().raster(epsg=None)
        constructor.campo(34735, 3, (1, 1, 0, 1, 3072, 0, 1, 32767))
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "x.tif", constructor.bytes()))
        assert cabecera.epsg is None

    def test_el_proyectado_manda_sobre_el_geografico(self, tmp_path):
        """Un archivo en UTM que ademas declara su geografico de base no esta en 4326.
        Decir 4326 pondria la ortofoto en el golfo de Guinea."""
        constructor = ConstructorTiff().raster(epsg=None)
        constructor.campo(34735, 3, (1, 1, 0, 2, 2048, 0, 1, 4326, 3072, 0, 1, 32719))
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "x.tif", constructor.bytes()))
        assert cabecera.epsg == 32719

    def test_calcula_gsd_y_extension_en_terreno(self, tmp_path):
        contenido = geotiff_minimo(ancho=100, alto=200, escala_m=0.025577)
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "x.tif", contenido))
        assert cabecera.gsd_cm == pytest.approx(2.5577)
        ancho_m, alto_m = cabecera.extension_terreno_m
        assert ancho_m == pytest.approx(2.5577)
        assert alto_m == pytest.approx(5.1154)

    def test_lee_el_origen_del_punto_de_atadura(self, tmp_path):
        contenido = geotiff_minimo(origen=(495003.25, 7318841.75))
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "x.tif", contenido))
        assert cabecera.origen == pytest.approx((495003.25, 7318841.75))


class TestNecesitabaBigtiff:
    """El aviso mas util que da la aplicacion: «esto es BigTIFF y no hacia falta»."""

    def test_una_imagen_pequena_no_necesitaba_bigtiff(self, tmp_path):
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "x.tif", bigtiff_minimo()))
        assert cabecera.necesitaba_bigtiff is False

    def test_una_imagen_enorme_si_lo_necesitaba(self, tmp_path):
        # 40000 x 40000 x 3 bandas = 4,8 GB sin comprimir: por encima del techo.
        contenido = bigtiff_minimo(ancho=40000, alto=40000, bandas=3)
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "x.tif", contenido))
        assert cabecera.bytes_sin_comprimir > 4_000_000_000
        assert cabecera.necesitaba_bigtiff is True


class TestElConstructorNoEscribePixeles:
    """La invariante que hace útil a este constructor, y que costó una corrida de CI.

    Declarar las dimensiones de la ortofoto real materializaba **839 MB de ceros** por
    archivo, y con varias pruebas así el runner se quedó sin disco. Los píxeles no se leen
    nunca: lo que se prueba es la cabecera.
    """

    def test_un_archivo_enorme_declarado_pesa_lo_que_una_cabecera(self, tmp_path):
        contenido = geotiff_minimo(ancho=14526, alto=14443, bandas=4)
        assert len(contenido) < 1000

    def test_y_aun_asi_declara_las_dimensiones_de_verdad(self, tmp_path):
        contenido = geotiff_minimo(ancho=14526, alto=14443, bandas=4)
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "x.tif", contenido))
        assert (cabecera.ancho_px, cabecera.alto_px, cabecera.bandas) == (14526, 14443, 4)
        assert cabecera.bytes_sin_comprimir > 800_000_000


class TestBigEndian:
    def test_lee_un_tiff_motorola(self, tmp_path):
        """`MM` casi no se ve hoy, pero el que aparece viene de un escaner viejo y es justo
        el archivo que nadie mas sabe abrir."""
        contenido = ConstructorTiff(little_endian=False).raster(ancho=6, alto=3, epsg=32719).bytes()
        cabecera = tiff.leer_cabecera(_escribir(tmp_path, "mm.tif", contenido))
        assert cabecera.little_endian is False
        assert (cabecera.ancho_px, cabecera.alto_px) == (6, 3)
        assert cabecera.epsg == 32719
