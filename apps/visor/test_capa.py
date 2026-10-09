"""La ficha de una capa: lo que se lee, lo que se calcula y lo que se **niega** a dibujar.

Aquí no corre GDAL. La ficha que se le da a `capa.desde_gdalinfo` es la que `gdalinfo -json` dio de
un GeoTIFF sintético (ver `apps/visor/testing.py`), y las esquinas se comparan con el `wgs84Extent`
que **calculó GDAL**, no con nuestra cuenta. Con GDAL de verdad lo mismo se repite en
`test_oraculo.py`.
"""

from __future__ import annotations

import json
import math

import pytest

from apps.visor import cache, capa, mercator, motor
from apps.visor.testing import (
    ALTO_PX,
    ANCHO_PX,
    WGS84_EXTENT_DE_GDAL,
    WKT_LOCAL,
    WKT_WGS84,
    GdalDeMentira,
    info_de_gdal,
)

TOLERANCIA_GRADOS = 1e-7


def _capa(**kwargs) -> capa.Capa:
    return capa.desde_gdalinfo(info_de_gdal(**kwargs), "ortofoto.tif")


class TestLasEsquinasContraGdal:
    def test_las_cuatro_esquinas_son_las_que_calculo_gdal(self):
        """`wgs84Extent` de GDAL va noroeste, suroeste, sureste, noreste; las nuestras, en el
        orden de la huella de la ficha (noroeste, noreste, sureste, suroeste)."""
        ficha = _capa()
        gdal_no, gdal_so, gdal_se, gdal_ne, _cierre = WGS84_EXTENT_DE_GDAL
        nuestras = ficha.esquinas_4326
        for propia, de_gdal in zip(nuestras, (gdal_no, gdal_ne, gdal_se, gdal_so), strict=True):
            assert propia[0] == pytest.approx(de_gdal[0], abs=TOLERANCIA_GRADOS)
            assert propia[1] == pytest.approx(de_gdal[1], abs=TOLERANCIA_GRADOS)

    def test_el_centro_esta_entre_las_esquinas_de_gdal(self):
        ficha = _capa()
        lons = [p[0] for p in WGS84_EXTENT_DE_GDAL[:4]]
        lats = [p[1] for p in WGS84_EXTENT_DE_GDAL[:4]]
        assert ficha.centro_4326[0] == pytest.approx(sum(lons) / 4, abs=1e-6)
        assert ficha.centro_4326[1] == pytest.approx(sum(lats) / 4, abs=1e-6)

    def test_las_esquinas_en_su_sistema_son_las_de_la_matriz(self):
        ficha = _capa()
        assert ficha.esquinas[0] == [345000.0, 6295100.0]
        assert ficha.esquinas[2] == [345000.0 + 400.0, 6295100.0 - 200.0]
        assert ficha.centro == [345200.0, 6295000.0]


class TestLoQueSeLee:
    def test_el_sistema_es_el_que_dice_el_archivo(self):
        ficha = _capa()
        assert ficha.sistema == "WGS 84 / UTM zone 19S"
        assert ficha.epsg == "32719"
        assert ficha.unidad == "metre"
        assert (ficha.ancho_px, ficha.alto_px, ficha.bandas, ficha.tipo) == (
            ANCHO_PX,
            ALTO_PX,
            3,
            "Byte",
        )

    def test_el_pixel_en_metros_es_el_de_la_matriz(self):
        assert _capa().pixel_size_m == pytest.approx(2.0)

    def test_una_matriz_en_pies_se_dice_en_metros(self):
        """Un sistema en pies de EE. UU. no se toma por metros: se convierte con su factor."""
        pies = (
            'PROJCRS["NAD83 / Texas Central (ftUS)",BASEGEOGCRS["NAD83",'
            'DATUM["North American Datum 1983",ELLIPSOID["GRS 1980",6378137,298.257222101]],'
            'PRIMEM["Greenwich",0]],CONVERSION["SPCS83 Texas Central zone (US survey foot)",'
            'METHOD["Lambert Conic Conformal (2SP)"],'
            'PARAMETER["Latitude of false origin",29.6666666666667],'
            'PARAMETER["Longitude of false origin",-100.333333333333],'
            'PARAMETER["Latitude of 1st standard parallel",31.8833333333333],'
            'PARAMETER["Latitude of 2nd standard parallel",30.1166666666667],'
            'PARAMETER["Easting at false origin",2296583.333,LENGTHUNIT["US survey foot",'
            "0.304800609601219]],"
            'PARAMETER["Northing at false origin",9842500,LENGTHUNIT["US survey foot",'
            "0.304800609601219]]],"
            'CS[Cartesian,2],AXIS["easting (X)",east,ORDER[1],LENGTHUNIT["US survey foot",'
            "0.304800609601219]],"
            'AXIS["northing (Y)",north,ORDER[2],LENGTHUNIT["US survey foot",'
            '0.304800609601219]],ID["EPSG",2277]]'
        )
        ficha = capa.desde_gdalinfo(
            info_de_gdal(wkt=pies, geotransform=[2300000.0, 10.0, 0, 10200000.0, 0, -10.0]),
            "pies.tif",
        )
        assert ficha.dibujable, ficha.detalle
        assert ficha.pixel_size_m == pytest.approx(10 * 0.304800609601219, rel=1e-9)

    def test_una_capa_en_grados_mide_su_pixel_en_metros_reales(self):
        wgs84 = WKT_WGS84
        ficha = capa.desde_gdalinfo(
            info_de_gdal(
                wkt=wgs84, geotransform=[-70.67, 0.0001, 0, -33.47, 0, -0.0001], ancho=100, alto=100
            ),
            "grados.tif",
        )
        assert ficha.dibujable, ficha.detalle
        # 0,0001° de longitud a -33,5° de latitud son ≈ 9,3 m (111 320 m · cos φ · 1e-4).
        esperado = 0.0001 * 111319.49 * math.cos(math.radians(-33.47))
        assert ficha.pixel_size_m == pytest.approx(esperado, rel=1e-3)
        assert ficha.epsg == "4326"

    def test_sin_piramide_y_grande_se_avisa(self):
        grande = info_de_gdal(ancho=20000, alto=20000, overviews=False)
        assert capa.desde_gdalinfo(grande, "g.tif").sin_piramide
        con = info_de_gdal(ancho=20000, alto=20000, overviews=True)
        assert not capa.desde_gdalinfo(con, "g.tif").sin_piramide
        chica = info_de_gdal(ancho=200, alto=200, overviews=False)
        assert not capa.desde_gdalinfo(chica, "g.tif").sin_piramide


class TestLoQueSeNiegaADibujar:
    """**Regla 3**: el CRS no se adivina. Y la negativa dice por qué, con un código estable."""

    def test_sin_sistema_de_referencia_no_se_dibuja(self):
        ficha = _capa(wkt=None)
        assert not ficha.dibujable
        assert ficha.motivo == "capa-sin-crs"

    def test_un_sistema_vacio_tampoco(self):
        assert _capa(wkt="").motivo == "capa-sin-crs"

    def test_un_sistema_local_de_obra_no_ubica_nada(self):
        ficha = _capa(wkt=WKT_LOCAL)
        assert not ficha.dibujable
        assert ficha.motivo == "capa-sin-crs"

    def test_un_wkt_que_proj_no_entiende_no_se_adivina(self):
        assert _capa(wkt="esto no es un sistema").motivo == "capa-sin-crs"

    def test_sin_matriz_de_transformacion_es_una_imagen_y_no_una_capa(self):
        info = info_de_gdal()
        del info["geoTransform"]
        ficha = capa.desde_gdalinfo(info, "foto.tif")
        assert not ficha.dibujable
        assert ficha.motivo == "capa-sin-georreferencia"

    def test_una_matriz_de_tres_valores_tampoco(self):
        assert _capa(geotransform=[0, 1, 0]).motivo == "capa-sin-georreferencia"

    def test_sin_bandas_no_es_legible(self):
        info = info_de_gdal()
        info["bands"] = []
        assert capa.desde_gdalinfo(info, "x.tif").motivo == "origen-no-legible"

    def test_pasado_el_polo_de_web_mercator_no_llega(self):
        wgs84 = WKT_WGS84
        ficha = capa.desde_gdalinfo(
            info_de_gdal(wkt=wgs84, geotransform=[10.0, 0.01, 0, 89.0, 0, -0.01], ancho=100),
            "polar.tif",
        )
        assert ficha.motivo == "capa-fuera-del-mapa"

    def test_cruzar_el_antimeridiano_tampoco(self):
        wgs84 = WKT_WGS84
        ficha = capa.desde_gdalinfo(
            info_de_gdal(wkt=wgs84, geotransform=[-179.0, 1.5, 0, 10.0, 0, -0.1], ancho=250),
            "ancha.tif",
        )
        assert ficha.motivo == "capa-fuera-del-mapa"

    def test_los_codigos_de_negativa_estan_en_el_catalogo_de_motivos(self):
        from apps.jobs.motivos import MOTIVOS

        for codigo in (
            "capa-sin-crs",
            "capa-sin-georreferencia",
            "capa-fuera-del-mapa",
            "sin-gdal",
        ):
            assert codigo in MOTIVOS
            assert MOTIVOS[codigo].mensaje.strip()
            assert codigo == codigo.lower() and "_" not in codigo and " " not in codigo

    def test_sin_crs_no_se_sugiere_el_mas_probable(self):
        from apps.jobs.motivos import MOTIVOS

        texto = (MOTIVOS["capa-sin-crs"].mensaje + MOTIVOS["capa-sin-crs"].sugerencia).lower()
        assert "probable" not in texto
        assert "32719" not in texto and "epsg" not in texto


class TestElZoom:
    def test_el_maximo_es_el_del_pixel_de_la_imagen_mas_uno(self):
        """2 m de píxel a -33,5° de latitud: ≈ 2,4 m de Mercator, que es el nivel ≈ 16,0."""
        ficha = _capa()
        resolucion_mercator = 2.0 / math.cos(math.radians(-33.4724))
        z_nativo = math.log2(mercator.RESOLUCION_NIVEL_0_M / resolucion_mercator)
        assert ficha.zoom_maximo == math.ceil(z_nativo) + 1

    def test_el_minimo_deja_la_capa_en_unos_64_pixeles(self):
        ficha = _capa()
        lado_m = max(
            ficha.caja_3857[2] - ficha.caja_3857[0], ficha.caja_3857[3] - ficha.caja_3857[1]
        )
        pixeles = lado_m / mercator.resolucion_m(ficha.zoom_minimo)
        assert 32 <= pixeles <= 256 * 4

    def test_el_minimo_no_pasa_del_maximo(self):
        assert _capa().zoom_minimo <= _capa().zoom_maximo

    def test_una_capa_con_pixeles_enormes_no_pide_niveles_negativos(self):
        ficha = _capa(geotransform=[200000.0, 5000.0, 0, 7000000.0, 0, -5000.0])
        assert ficha.dibujable, ficha.detalle
        assert 0 <= ficha.zoom_minimo <= ficha.zoom_maximo <= mercator.ZOOM_MAXIMO


class TestElContorno:
    def test_la_caja_envuelve_todo_el_contorno(self):
        ficha = _capa()
        x0, y0, x1, y1 = ficha.caja_3857
        assert all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in ficha.contorno_3857)

    def test_tiene_varios_puntos_por_lado(self):
        assert len(_capa().contorno_3857) == 4 * capa.SEGMENTOS_POR_LADO

    def test_las_esquinas_de_mercator_coinciden_con_las_de_grados(self):
        ficha = _capa()
        for (lon, lat), (x, y) in zip(
            ficha.esquinas_4326,
            (ficha.contorno_3857[i * capa.SEGMENTOS_POR_LADO] for i in range(4)),
            strict=True,
        ):
            ex, ey = mercator.lonlat_a_mercator(lon, lat)
            assert x == pytest.approx(ex, abs=0.01)
            assert y == pytest.approx(ey, abs=0.01)


class TestLasQueNoSonDe8Bits:
    def test_una_de_16_bits_pide_una_fuente_de_8(self):
        ficha = _capa(tipo="UInt16", bandas=1, interpretacion="Gray")
        assert ficha.necesita_vrt
        assert not ficha.paleta

    def test_una_con_paleta_pide_expandirla(self):
        ficha = _capa(tipo="Byte", bandas=1, interpretacion="Palette")
        assert ficha.necesita_vrt and ficha.paleta

    def test_una_de_ocho_bandas_pide_elegir_tres(self):
        assert _capa(bandas=8).necesita_vrt

    def test_una_rgb_de_8_bits_va_tal_cual(self):
        assert not _capa(tipo="Byte", bandas=3).necesita_vrt
        assert not _capa(tipo="Byte", bandas=4).necesita_vrt


class TestLeerPregunta:
    """`capa.leer` le habla a GDAL por `motor.correr`; aquí, uno de mentira que anota lo pedido."""

    @pytest.fixture
    def falso(self, monkeypatch):
        falso = GdalDeMentira()
        monkeypatch.setattr(motor, "correr", falso)
        return falso

    def test_una_8_bits_pregunta_una_vez_y_en_json(self, falso, tmp_path):
        ficha = capa.leer(tmp_path / "o.tif")
        assert ficha.dibujable
        assert falso.llamadas == [("gdalinfo", ["-json", str(tmp_path / "o.tif")])]

    def test_una_de_16_bits_mide_su_rango_aproximado(self, falso, tmp_path):
        falso.info = info_de_gdal(tipo="UInt16", bandas=1, interpretacion="Gray")
        falso.minimo, falso.maximo = 100.0, 3000.0
        ficha = capa.leer(tmp_path / "o.tif")
        assert ficha.escala == [100.0, 3000.0]
        # `-approx_stats` y no `-stats`: los exactos de una imagen grande tardan minutos.
        assert "-approx_stats" in falso.llamadas[1][1]
        assert "-stats" not in falso.llamadas[1][1]

    def test_un_rango_plano_no_se_inventa(self, falso, tmp_path):
        falso.info = info_de_gdal(tipo="UInt16", bandas=1, interpretacion="Gray")
        falso.minimo = falso.maximo = 7.0
        ficha = capa.leer(tmp_path / "o.tif")
        assert not ficha.dibujable and ficha.motivo == "origen-no-legible"

    def test_un_archivo_que_gdal_no_abre_es_origen_no_legible(self, falso, tmp_path):
        falso.fallar_con = motor.ErrorDeGdal("ERROR 4: no es un raster", "error-del-motor")
        with pytest.raises(motor.ErrorDeGdal) as dentro:
            capa.leer(tmp_path / "o.txt")
        assert dentro.value.codigo == "origen-no-legible"

    def test_una_respuesta_que_no_es_json_tambien(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            motor, "correr", lambda *a, **k: motor.Resultado(salida="no soy json", errores="")
        )
        with pytest.raises(motor.ErrorDeGdal) as dentro:
            capa.leer(tmp_path / "o.tif")
        assert dentro.value.codigo == "origen-no-legible"


class TestLaFichaEnLaCache:
    @pytest.fixture(autouse=True)
    def _cache(self, settings, tmp_path):
        settings.VISOR_CACHE = str(tmp_path / "cache-visor")

    def test_la_segunda_vez_no_pregunta_a_gdal(self, monkeypatch, tmp_path):
        falso = GdalDeMentira()
        monkeypatch.setattr(motor, "correr", falso)
        original = tmp_path / "o.tif"
        original.write_bytes(b"x")
        clave = cache.clave_de(original)

        primera = capa.con_cache(original, clave)
        segunda = capa.con_cache(original, clave)

        assert falso.contar("gdalinfo") == 1
        assert primera == segunda

    def test_una_ficha_rota_se_rehace(self, monkeypatch, tmp_path):
        falso = GdalDeMentira()
        monkeypatch.setattr(motor, "correr", falso)
        original = tmp_path / "o.tif"
        original.write_bytes(b"x")
        clave = cache.clave_de(original)
        capa.con_cache(original, clave)
        (cache.carpeta_de(clave) / "capa.json").write_text("{no es json", encoding="utf-8")

        assert capa.con_cache(original, clave).dibujable
        assert falso.contar("gdalinfo") == 2

    def test_la_ficha_guardada_es_json_legible_y_trae_el_sistema(self, monkeypatch, tmp_path):
        monkeypatch.setattr(motor, "correr", GdalDeMentira())
        original = tmp_path / "o.tif"
        original.write_bytes(b"x")
        clave = cache.clave_de(original)
        capa.con_cache(original, clave)
        datos = json.loads((cache.carpeta_de(clave) / "capa.json").read_text(encoding="utf-8"))
        assert datos["epsg"] == "32719"
        assert "PROJCRS" in datos["wkt"]
