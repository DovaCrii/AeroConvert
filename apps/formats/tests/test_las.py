"""El lector de cabecera LAS, contra archivos escritos byte a byte en la prueba misma.

Gemelo de `test_tiff.py`, y por lo mismo: si el archivo lo escribiera PDAL y lo leyera
nuestro código, lo único que se comprobaría es que los dos entienden igual el formato — y
haría falta PDAL instalado, que es justo lo que el gate no puede exigir.
"""

import pytest

from apps.formats import las

from .constructor import copc_minimo, las_minimo

WKT_UTM19S = (
    'PROJCS["WGS 84 / UTM zone 19S",GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],'
    'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4326"]],PROJECTION["Transverse_Mercator"],'
    'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-69],'
    'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],'
    'PARAMETER["false_northing",10000000],UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
    'AUTHORITY["EPSG","32719"]]'
)


def _escribir(tmp_path, nombre, contenido):
    ruta = tmp_path / nombre
    ruta.write_bytes(contenido)
    return ruta


class TestLoBasico:
    def test_lee_version_y_cuenta(self, tmp_path):
        cabecera = las.leer_cabecera(_escribir(tmp_path, "n.las", las_minimo(puntos=9_618_692)))
        assert cabecera.version == (1, 2)
        assert cabecera.puntos == 9_618_692

    def test_en_las_1_4_manda_la_cuenta_de_64_bits(self, tmp_path):
        """La de 32 bits queda a cero cuando no cabe. Leer solo esa da cero puntos en
        cualquier nube grande moderna."""
        contenido = las_minimo(version=(1, 4), formato_de_punto=6, puntos=5_000_000_000)
        assert las.leer_cabecera(_escribir(tmp_path, "n.las", contenido)).puntos == 5_000_000_000

    def test_lo_que_no_empieza_por_lasf_se_rechaza(self, tmp_path):
        with pytest.raises(las.NoEsLas):
            las.leer_cabecera(_escribir(tmp_path, "x.las", b"II*\x00" + bytes(300)))

    def test_un_archivo_truncado_se_rechaza(self, tmp_path):
        with pytest.raises(las.NoEsLas):
            las.leer_cabecera(_escribir(tmp_path, "x.las", b"LASF" + bytes(20)))

    def test_lee_el_software_que_lo_escribio(self, tmp_path):
        contenido = las_minimo(software="Agisoft Metashape")
        assert las.leer_cabecera(_escribir(tmp_path, "n.las", contenido)).software == (
            "Agisoft Metashape"
        )


class TestLaCompresion:
    """El bit alto del identificador de formato marca LAZ. Leerlo sin la máscara da 134 en
    vez de 6, y entonces el formato de punto no coincide con ninguno del estándar."""

    def test_un_las_no_esta_comprimido(self, tmp_path):
        cabecera = las.leer_cabecera(_escribir(tmp_path, "n.las", las_minimo(comprimido=False)))
        assert cabecera.comprimido is False
        assert cabecera.formato_de_punto == 2

    def test_un_laz_si_y_su_formato_sigue_leyendose_bien(self, tmp_path):
        contenido = las_minimo(comprimido=True, formato_de_punto=6, version=(1, 4))
        cabecera = las.leer_cabecera(_escribir(tmp_path, "n.laz", contenido))
        assert cabecera.comprimido is True
        assert cabecera.formato_de_punto == 6


class TestCopc:
    """Un COPC exige tres cosas a la vez, y las tres se comprueban.

    Aceptar un LAZ solo porque trae un VLR llamado `copc` haría que AeroBim intentara leer
    un octree que no está.
    """

    def test_un_copc_de_verdad_se_reconoce(self, tmp_path):
        assert las.leer_cabecera(_escribir(tmp_path, "n.copc.laz", copc_minimo())).es_copc

    def test_sin_el_vlr_no_es_copc(self, tmp_path):
        contenido = las_minimo(version=(1, 4), formato_de_punto=7, comprimido=True, copc=False)
        assert las.leer_cabecera(_escribir(tmp_path, "n.laz", contenido)).es_copc is False

    def test_con_formato_de_punto_antiguo_no_es_copc(self, tmp_path):
        """La especificación fija formato 6, 7 u 8."""
        contenido = copc_minimo(formato_de_punto=3)
        assert las.leer_cabecera(_escribir(tmp_path, "n.laz", contenido)).es_copc is False

    def test_con_las_1_2_no_es_copc(self, tmp_path):
        contenido = copc_minimo(version=(1, 2), formato_de_punto=2)
        assert las.leer_cabecera(_escribir(tmp_path, "n.laz", contenido)).es_copc is False


class TestElSistemaDeReferencia:
    def test_lo_lee_de_las_geoclaves_como_un_geotiff(self, tmp_path):
        """LAS 1.0 a 1.3 lo guardan con el registro 34735, que es literalmente el mismo
        formato que un GeoTIFF. Por eso ese parser se reutiliza."""
        contenido = las_minimo(version=(1, 2), epsg=32719)
        assert las.leer_cabecera(_escribir(tmp_path, "n.las", contenido)).epsg == 32719

    def test_lo_lee_del_wkt_en_las_1_4(self, tmp_path):
        contenido = las_minimo(version=(1, 4), formato_de_punto=6, wkt=WKT_UTM19S, epsg=None)
        cabecera = las.leer_cabecera(_escribir(tmp_path, "n.las", contenido))
        assert cabecera.epsg == 32719
        assert "UTM zone 19S" in cabecera.wkt

    def test_sin_ninguno_queda_en_none_y_no_se_inventa(self, tmp_path):
        """Una nube sin CRS no se puede cruzar con nada. Suponerle uno es peor que no
        tenerlo."""
        contenido = las_minimo(epsg=None, wkt="")
        assert las.leer_cabecera(_escribir(tmp_path, "n.las", contenido)).epsg is None

    def test_un_crs_compuesto_se_resuelve_por_su_horizontal(self, tmp_path):
        """PDAL escribe las nubes con un `COMPD_CS`: el UTM más un vertical sin datum
        conocido. Ese compuesto no lo identifica nadie, y la heurística del `AUTHORITY`
        declarado agarraba el del **metro** del componente vertical, `EPSG:9001`.

        Es un fallo real: una nube perfectamente georreferenciada se reportaba sin CRS.
        """
        compuesto = (
            'COMPD_CS["WGS 84 / UTM zone 19S",'
            + WKT_UTM19S
            + ',VERT_CS["",VERT_DATUM["unknown",2005],'
            'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Up",UP]]]'
        )
        contenido = las_minimo(version=(1, 4), formato_de_punto=6, wkt=compuesto, epsg=None)
        assert las.leer_cabecera(_escribir(tmp_path, "n.las", contenido)).epsg == 32719


class TestGeometria:
    def test_los_limites_no_se_leen_alternados(self, tmp_path):
        """El orden en la cabecera es max, min, max, min, max, min. Leerlo como dos ternas
        seguidas cambia el mínimo por el máximo en dos de los tres ejes."""
        contenido = las_minimo(minimo=(10.0, 20.0, 30.0), maximo=(11.0, 22.0, 33.0))
        cabecera = las.leer_cabecera(_escribir(tmp_path, "n.las", contenido))
        assert cabecera.minimo == (10.0, 20.0, 30.0)
        assert cabecera.maximo == (11.0, 22.0, 33.0)

    def test_calcula_extension_densidad_y_separacion(self, tmp_path):
        contenido = las_minimo(puntos=10_000, minimo=(0.0, 0.0, 0.0), maximo=(100.0, 100.0, 5.0))
        cabecera = las.leer_cabecera(_escribir(tmp_path, "n.las", contenido))
        assert cabecera.extension_m == (100.0, 100.0, 5.0)
        assert cabecera.densidad_por_m2 == pytest.approx(1.0)
        assert cabecera.separacion_media_m == pytest.approx(1.0)

    def test_una_extension_degenerada_no_divide_por_cero(self, tmp_path):
        contenido = las_minimo(minimo=(5.0, 5.0, 5.0), maximo=(5.0, 5.0, 5.0))
        cabecera = las.leer_cabecera(_escribir(tmp_path, "n.las", contenido))
        assert cabecera.densidad_por_m2 is None
        assert cabecera.separacion_media_m is None


class TestPrecisionEnFloat32:
    """El hallazgo caro de AeroBim: **en el norte UTM de Chile, `float32` pierde 200 mm.**

    Un float32 tiene 24 bits de mantisa, así que sobre un valor de 7,3 millones el escalón
    es de medio metro. Hay que restar el desplazamiento de cabecera antes de convertir.
    """

    def test_avisa_con_coordenadas_utm_grandes(self, tmp_path):
        contenido = las_minimo(
            minimo=(495003.24, 7318472.78, 3038.72),
            maximo=(495373.63, 7318841.78, 3064.17),
            escala=(0.01, 0.01, 0.01),
        )
        cabecera = las.leer_cabecera(_escribir(tmp_path, "n.las", contenido))
        assert cabecera.precision_suficiente_para_float32 is False

    def test_no_avisa_con_coordenadas_locales(self, tmp_path):
        """Una nube ya centrada en el origen no tiene el problema."""
        contenido = las_minimo(
            minimo=(-50.0, -50.0, 0.0), maximo=(50.0, 50.0, 10.0), escala=(0.01, 0.01, 0.01)
        )
        cabecera = las.leer_cabecera(_escribir(tmp_path, "n.las", contenido))
        assert cabecera.precision_suficiente_para_float32 is True


class TestVlrs:
    def test_cuenta_los_vlrs(self, tmp_path):
        contenido = copc_minimo(wkt=WKT_UTM19S, epsg=None)
        assert las.leer_cabecera(_escribir(tmp_path, "n.laz", contenido)).vlrs == 2

    def test_un_vlr_con_longitud_absurda_no_cuelga(self, tmp_path):
        """Un archivo corrupto puede declarar cuatro gigas en un VLR. Esto corre al soltar
        un archivo en el navegador."""
        import struct

        contenido = bytearray(las_minimo())
        # El primer VLR empieza en el byte 227; su longitud va en el 227+20.
        struct.pack_into("<H", contenido, 227 + 20, 65535)
        cabecera = las.leer_cabecera(_escribir(tmp_path, "n.las", bytes(contenido)))
        assert cabecera.puntos == 1000


class TestEstimacionDeTamano:
    def test_estima_el_tamano_sin_comprimir(self, tmp_path):
        contenido = las_minimo(puntos=1_000_000, formato_de_punto=2)
        cabecera = las.leer_cabecera(_escribir(tmp_path, "n.las", contenido))
        assert cabecera.bytes_sin_comprimir_estimados == 26_000_000


class TestElVlrDeWktGanaCuandoElArchivoLoDice:
    def test_con_el_bit_puesto_gana_el_wkt(self, tmp_path):
        """Cuando el archivo trae los dos y su `global_encoding` dice WKT, ese es el que el
        escritor declaró autoritativo; las geoclaves suelen ser residuo de una conversión
        anterior.

        Las geoclaves dicen 32718 y el WKT dice 32719 — un huso de diferencia, que sobre el
        terreno son cientos de kilómetros.
        """
        contenido = las_minimo(version=(1, 4), formato_de_punto=6, epsg=32718, wkt=WKT_UTM19S)
        cabecera = las.leer_cabecera(_escribir(tmp_path, "n.las", contenido))
        assert cabecera.vlrs == 2
        assert cabecera.epsg == 32719

    def test_sin_el_bit_gana_lo_incrustado_en_geoclaves(self, tmp_path):
        """Sin el bit, el archivo es un LAS clásico que arrastra un WKT informativo."""
        contenido = las_minimo(version=(1, 2), epsg=32718, wkt=WKT_UTM19S)
        assert las.leer_cabecera(_escribir(tmp_path, "n.las", contenido)).epsg == 32718
