"""La estimación previa: cuánto va a pesar, cuánto va a tardar y si cabe."""

import pytest

from apps.formats.deteccion import inspeccionar
from apps.formats.tests.constructor import bigtiff_minimo, geotiff_minimo, las_minimo
from apps.jobs import estimacion as est


def _inspeccion(tmp_path, **kwargs):
    ruta = tmp_path / "orto.tif"
    ruta.write_bytes(geotiff_minimo(**kwargs))
    return inspeccionar(ruta)


@pytest.fixture
def grande(tmp_path):
    """La ortofoto real, en 400 bytes de disco.

    Las dimensiones van en la cabecera y el constructor **no escribe los píxeles**, así que
    el archivo pesa una cabecera. Pero el tamaño en disco sí importa para dos cosas — el
    tiempo estimado y el aviso de «va a crecer» — así que se sustituye por el del archivo
    de verdad, 466,2 MB. Dejarlo en 400 bytes haría creer a la estimación que cualquier
    salida crece cuatro órdenes de magnitud.
    """
    from dataclasses import replace

    ruta = tmp_path / "grande.tif"
    ruta.write_bytes(geotiff_minimo(ancho=14526, alto=14443, bandas=4))
    return replace(inspeccionar(ruta), bytes_totales=488_815_770)


class TestElAncla:
    def test_se_estima_sobre_el_tamano_sin_comprimir(self, tmp_path):
        """Dos archivos con el mismo contenido y distinta compresión tienen que dar la
        misma estimación. Anclar al tamaño del archivo daría dos respuestas para la misma
        imagen."""
        sin = tmp_path / "sin.tif"
        sin.write_bytes(geotiff_minimo(ancho=1000, alto=1000, bandas=3, compresion=1))
        con = tmp_path / "con.tif"
        con.write_bytes(geotiff_minimo(ancho=1000, alto=1000, bandas=3, compresion=5))

        a = est.estimar(inspeccion=inspeccionar(sin), formato_destino="geotiff")
        b = est.estimar(inspeccion=inspeccionar(con), formato_destino="geotiff")

        assert a.bytes_salida == b.bytes_salida

    def test_descartar_el_alfa_reduce_la_estimacion(self, grande):
        con_alfa = est.estimar(inspeccion=grande, formato_destino="geotiff")
        sin_alfa = est.estimar(
            inspeccion=grande, formato_destino="geotiff", opciones={"solo_rgb": True}
        )
        assert sin_alfa.bytes_salida < con_alfa.bytes_salida


class TestRatiosMedidos:
    def test_jp2_estima_mucho_menos_que_deflate(self, grande):
        """Medido: 60 MB contra 285 MB sobre el mismo original."""
        jp2 = est.estimar(inspeccion=grande, formato_destino="jp2")
        deflate = est.estimar(inspeccion=grande, formato_destino="geotiff")
        assert jp2.bytes_salida < deflate.bytes_salida / 3

    def test_deflate_estima_algo_menos_que_lzw(self, grande):
        """Medido: 283 MB contra 302 MB. La diferencia es pequeña pero es real, y es por lo
        que DEFLATE es el valor por omisión."""
        deflate = est.estimar(
            inspeccion=grande, formato_destino="geotiff", opciones={"compresion": "DEFLATE"}
        )
        lzw = est.estimar(
            inspeccion=grande, formato_destino="geotiff", opciones={"compresion": "LZW"}
        )
        assert deflate.bytes_salida < lzw.bytes_salida

    def test_la_estimacion_del_caso_real_se_parece_a_lo_medido(self, grande):
        """Sobre la ortofoto de referencia salieron 285 MB reales hacia GeoTIFF DEFLATE de
        tres bandas. Se admite un factor de 1,5 en cualquier dirección: es una estimación,
        no una promesa, y el material cambia el resultado."""
        estimada = est.estimar(
            inspeccion=grande,
            formato_destino="geotiff",
            opciones={"compresion": "DEFLATE", "solo_rgb": True},
        )
        real = 285_000_000
        assert real / 1.5 < estimada.bytes_salida < real * 1.5

    def test_una_combinacion_sin_medir_se_marca_como_tal(self, grande):
        """Decir «≈ 40 MB» con la misma cara cuando no hay medida detrás sería mentir con
        precisión decimal."""
        assert est.estimar(inspeccion=grande, formato_destino="nitf").medida is False
        assert est.estimar(inspeccion=grande, formato_destino="geotiff").medida is True


class TestAvisos:
    def test_avisa_cuando_la_salida_va_a_crecer(self, grande):
        """ASCII Grid es texto plano y **crece**, mucho. Conviene que se vea antes de
        lanzar la conversión, no después."""
        estimada = est.estimar(inspeccion=grande, formato_destino="asc")
        assert estimada.crece
        assert "veces el original" in estimada.aviso

    def test_no_avisa_cuando_encoge(self, grande):
        assert est.estimar(inspeccion=grande, formato_destino="jp2").crece is False


class TestTiempoYMemoria:
    def test_el_tiempo_crece_con_el_tamano(self, tmp_path):
        pequeno = _inspeccion(tmp_path, ancho=100, alto=100)
        assert est.estimar(inspeccion=pequeno, formato_destino="cog").segundos >= 1.0

    def test_las_piramides_cuestan_tiempo(self, grande):
        con = est.estimar(
            inspeccion=grande, formato_destino="geotiff", opciones={"piramides": "2 4 8"}
        )
        sin = est.estimar(inspeccion=grande, formato_destino="geotiff", opciones={"piramides": ""})
        assert con.segundos > sin.segundos

    def test_la_memoria_es_el_techo_no_una_prediccion(self, grande):
        """Es el dato que importa para saber si la estación se va a quedar sin memoria."""
        assert est.estimar(inspeccion=grande, formato_destino="cog").memoria_mb >= 512

    def test_el_techo_de_raster_esta_por_encima_de_lo_medido(self, grande):
        """Medido el 2026-09-09: `gdal_translate` con `GDAL_CACHEMAX=512` picó en 655 MB.

        Un «techo» por debajo del pico real no es un techo: es una cifra que tranquiliza
        justo antes de que la máquina se quede sin memoria.
        """
        estimada = est.estimar(inspeccion=grande, formato_destino="jp2")
        assert estimada.memoria_mb >= 655


class TestLaMemoriaDeLasNubes:
    """PDAL no respeta `GDAL_CACHEMAX`, así que su techo crece con los puntos.

    Antes se devolvía la cifra de GDAL para todo. Con la nube de referencia se quedaba corta
    en un 50 %, y el error crecía con el tamaño de la nube — que es la peor forma de
    equivocarse, porque acierta en las pruebas pequeñas.
    """

    def _nube(self, carpeta, puntos):
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / "nube.las"
        ruta.write_bytes(las_minimo(puntos=puntos))
        return inspeccionar(ruta)

    def test_una_nube_pide_mas_que_una_ortofoto(self, tmp_path, grande):
        nube = self._nube(tmp_path, 9_618_692)
        de_nube = est.estimar(inspeccion=nube, formato_destino="copc").memoria_mb
        de_raster = est.estimar(inspeccion=grande, formato_destino="cog").memoria_mb
        assert de_nube > de_raster

    def test_el_techo_esta_por_encima_del_pico_medido(self, tmp_path):
        """Medido el 2026-09-09: 966 MB de pico para los 9.618.692 puntos de la referencia."""
        nube = self._nube(tmp_path, 9_618_692)
        assert est.estimar(inspeccion=nube, formato_destino="copc").memoria_mb >= 966

    def test_crece_con_el_numero_de_puntos(self, tmp_path):
        """Lo que distingue esto de una constante: el doble de puntos pide más memoria."""
        poca = est.estimar(inspeccion=self._nube(tmp_path / "a", 5_000_000), formato_destino="copc")
        mucha = est.estimar(
            inspeccion=self._nube(tmp_path / "b", 50_000_000), formato_destino="copc"
        )
        assert mucha.memoria_mb > poca.memoria_mb * 5


class TestEspacio:
    def test_dice_si_cabe(self, grande):
        """Se pide el doble porque durante un instante conviven el parcial y el
        definitivo."""
        estimada = est.estimar(inspeccion=grande, formato_destino="jp2")
        assert estimada.cabe is (estimada.libre_bytes > estimada.bytes_salida * 2)

    def test_sin_espacio_libre_no_cabe(self, grande):
        estimada = est.Estimacion(
            bytes_salida=10_000_000_000, segundos=10, memoria_mb=640, libre_bytes=1_000
        )
        assert estimada.cabe is False


class TestSinCabecera:
    def test_un_archivo_sin_cabecera_legible_no_revienta(self, tmp_path):
        """Se cae al tamaño del archivo, que es peor pero es algo. Negarse a estimar
        dejaría la interfaz sin la línea honesta justo donde más falta hace."""
        ruta = tmp_path / "cosa.asc"
        ruta.write_text("ncols 4\nnrows 4\n")
        estimada = est.estimar(inspeccion=inspeccionar(ruta), formato_destino="geotiff")
        assert estimada.bytes_salida > 0


class TestBigtiff:
    def test_el_bigtiff_del_caso_real_se_estima_igual_que_su_clasico(self, tmp_path):
        """La variante no cambia cuántos píxeles hay."""
        big = tmp_path / "b.tif"
        big.write_bytes(bigtiff_minimo(ancho=5000, alto=5000, bandas=3))
        clasico = tmp_path / "c.tif"
        clasico.write_bytes(geotiff_minimo(ancho=5000, alto=5000, bandas=3))

        a = est.estimar(inspeccion=inspeccionar(big), formato_destino="cog")
        b = est.estimar(inspeccion=inspeccionar(clasico), formato_destino="cog")
        assert a.bytes_salida == b.bytes_salida
