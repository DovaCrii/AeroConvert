"""Terreno en el visor (F19.4) con un GDAL de mentira: el pegamento, no GDAL.

Es lo que corre el CI sin GDAL. De GDAL de verdad se ocupa `test_terreno_oraculo.py`
(`@pytest.mark.oraculo`): la cota contra `gdallocationinfo`, el perfil contra muestras
independientes y una tesela de sombreado contra otro `gdaldem hillshade` + `gdalwarp`.

Aquí se prueba lo que **no** necesita GDAL:

- qué es un DEM y qué declara (unidad, referencia vertical, «sin dato») y **qué no se supone**;
- los parámetros del sol: se comprueban, no se recortan; cada juego tiene su clave y su `ETag`;
- la geodésica del perfil contra valores conocidos del elipsoide, y los huecos;
- el CSV (la unidad de un archivo no abre una fórmula en la hoja de cálculo);
- el apagado con motivo (regla 4), el 302 y el 403 por vista nueva, y el original intacto (regla 5)
  en cada camino de fallo.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from PIL import Image

from apps.engines.base import Disponibilidad
from apps.visor import cache, capa, dem, mercator, motor, terreno
from apps.visor.testing import (
    GdalDeMentira,
    info_de_dem,
    info_de_gdal,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def obra(tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path / "obra")
    settings.MODO = settings.MODO_TALLER
    settings.VISOR_CACHE = str(tmp_path / "cache-visor")
    settings.VISOR_CACHE_MAX_MB = 64
    carpeta = tmp_path / "obra"
    carpeta.mkdir()
    return carpeta


@pytest.fixture
def modelo(obra):
    ruta = obra / "terreno.tif"
    ruta.write_bytes(b"II*\x00" + b"modelo sintetico" * 200)
    return ruta


@pytest.fixture
def sesion(client):
    client.force_login(get_user_model().objects.create_user("ana"))
    return client


@pytest.fixture
def falso(monkeypatch):
    """GDAL de mentira, con `gdaldem`, y el archivo es un DEM `Float32` en metros."""
    mentira = GdalDeMentira(info_de_dem())
    monkeypatch.setattr(motor, "correr", mentira)
    monkeypatch.setattr(motor, "disponibilidad", lambda: Disponibilidad.si("GDAL de mentira"))
    monkeypatch.setattr(motor, "disponibilidad_sombreado", lambda: Disponibilidad.si(""))
    return mentira


@pytest.fixture
def sin_gdaldem(monkeypatch):
    monkeypatch.setattr(
        motor,
        "disponibilidad_sombreado",
        lambda: Disponibilidad.no("sin-gdaldem", "Falta gdaldem.", sugerencia="Instale QGIS."),
    )


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


def _tesela(sesion, modelo, parametros=None, *, z=None, cabeceras=None):
    """La tesela del centro del modelo, en el último nivel, con esos parámetros."""
    ficha = sesion.get(reverse("visor:capa"), {"ruta": str(modelo)}).json()
    z = ficha["zoom_maximo"] if z is None else z
    x, y = mercator.tesela_de_lonlat(*ficha["centro_4326"], z)
    return sesion.get(
        reverse("visor:tesela", args=[z, x, y]),
        {"ruta": str(modelo), **(parametros or {})},
        headers=cabeceras or {},
    )


def _llamadas(falso, nombre, primero=None):
    return [a for n, a in falso.llamadas if n == nombre and (primero is None or a[0] == primero)]


def _valor_de(argumentos: list[str], opcion: str) -> str:
    return argumentos[argumentos.index(opcion) + 1]


def _ficha_de(info: dict | None = None):
    ficha = capa.desde_gdalinfo(info or info_de_dem(), "modelo.tif")
    if ficha.es_dem:  # lo que `capa.leer` añade con `gdalinfo -approx_stats`
        ficha.escala = [0.0, 4000.0]
        ficha.rampa = dem.rampa(*ficha.escala)
    return ficha


# ---------------------------------------------------------------------------------------------
# Qué es un DEM y qué declara
# ---------------------------------------------------------------------------------------------


class TestQueEsUnDem:
    @pytest.mark.parametrize("tipo", ["Int16", "UInt16", "Int32", "UInt32", "Float32", "Float64"])
    def test_una_banda_entera_o_flotante_es_un_dem(self, tipo):
        assert _ficha_de(info_de_dem(tipo=tipo)).es_dem

    @pytest.mark.parametrize(
        "cambios",
        [
            {
                "bandas": 3,
                "tipo": "Byte",
                "interpretacion": "Red",
                "unidad": None,
                "sin_dato": None,
            },
            {"bandas": 1, "tipo": "Byte", "interpretacion": "Gray"},
            {"bandas": 3},
            {"interpretacion": "Palette", "tipo": "Byte"},
        ],
    )
    def test_lo_demas_no_lo_es(self, cambios):
        assert not _ficha_de(info_de_dem(**cambios)).es_dem

    def test_declara_su_unidad_y_su_sin_dato(self):
        ficha = _ficha_de(info_de_dem(unidad="ft", sin_dato=-32768.0))
        assert ficha.unidad_vertical == "ft"
        assert ficha.unidad_vertical_m == pytest.approx(0.3048)
        assert ficha.nodata == -32768.0 and not ficha.nodata_es_nan

    def test_sin_unidad_no_hay_unidad_ni_se_supone_metros(self):
        ficha = _ficha_de(info_de_dem(unidad=None))
        assert ficha.unidad_vertical == "" and ficha.unidad_vertical_m is None

    def test_un_sin_dato_nan_no_viaja_como_nan(self):
        ficha = _ficha_de(info_de_dem(sin_dato="NaN"))
        assert ficha.nodata is None and ficha.nodata_es_nan
        json.dumps(ficha.a_dict(), allow_nan=False)  # NaN no es JSON: reventaría en el navegador

    def test_sin_sin_dato_no_se_inventa_uno(self):
        assert _ficha_de(info_de_dem(sin_dato=None)).nodata is None

    def test_la_unidad_de_un_archivo_no_abre_una_formula(self):
        for hostil in ('=HYPERLINK("http://x")', "+cmd|' /C calc'!A0", "-2+3", "@SUM(1)"):
            texto, _ = dem.unidad_vertical(hostil)
            assert not texto or texto[0] not in "=+-@", hostil
            assert '"' not in texto and "|" not in texto and "!" not in texto

    def test_una_unidad_rara_se_dice_pero_no_se_convierte(self):
        texto, metros = dem.unidad_vertical("fathom")
        assert texto == "fathom" and metros is None


class TestLaReferenciaVerticalSoloSiSeDeclara:
    """Regla 3: ni «sobre el nivel del mar» ni ninguna otra por suponer."""

    def test_un_sistema_solo_horizontal_no_declara_referencia_vertical(self):
        assert _ficha_de().referencia_vertical == ""

    def test_un_sistema_compuesto_declara_su_parte_vertical(self):
        from pyproj import CRS

        wkt = CRS.from_user_input("EPSG:32719+5773").to_wkt()
        ficha = _ficha_de(info_de_dem(wkt=wkt))
        assert "EGM96" in ficha.referencia_vertical
        assert ficha.dibujable and ficha.es_dem

    def test_una_altura_elipsoidal_3d_no_se_llama_nivel_del_mar(self):
        from pyproj import CRS

        wkt = CRS.from_epsg(4979).to_wkt()  # WGS 84 con altura elipsoidal: no es compuesto
        assert (
            _ficha_de(
                info_de_dem(wkt=wkt, geotransform=[-70.0, 0.001, 0, -33.0, 0, -0.001])
            ).referencia_vertical
            == ""
        )


class TestLaEscalaDelSombreado:
    def test_metros_sobre_metros_es_uno(self):
        assert _ficha_de().escala_sombreado == 1.0

    def test_pies_sobre_metros(self):
        assert _ficha_de(info_de_dem(unidad="ft")).escala_sombreado == pytest.approx(1 / 0.3048)

    def test_sin_unidad_se_supone_la_horizontal(self):
        assert _ficha_de(info_de_dem(unidad=None)).escala_sombreado == 1.0

    def test_en_grados_es_el_valor_de_gdal(self):
        from pyproj import CRS

        ficha = _ficha_de(
            info_de_dem(
                wkt=CRS.from_epsg(4326).to_wkt(),
                geotransform=[-70.0, 0.0001, 0, -33.0, 0, -0.0001],
            )
        )
        assert ficha.escala_sombreado == 111120.0


class TestLaRampa:
    def test_va_del_minimo_al_maximo_y_es_creciente(self):
        r = dem.rampa(100.0, 600.0)
        assert [p[0] for p in r] == [100.0, 200.0, 300.0, 400.0, 500.0, 600.0]
        assert r[0][1] == [68, 1, 84] and r[-1][1] == [253, 231, 37]

    @pytest.mark.parametrize("par", [(5.0, 5.0), (6.0, 5.0), (math.nan, 1.0)])
    def test_sin_rango_no_hay_rampa(self, par):
        assert dem.rampa(*par) == []

    def test_el_archivo_de_colores_de_gdaldem(self):
        texto = dem.texto_de_rampa(dem.rampa(0.0, 10.0))
        lineas = texto.strip().splitlines()
        assert lineas[0] == "0.0 68 1 84 255" and lineas[-1] == "nv 0 0 0 0"
        assert len(lineas) == 7

    def test_la_capa_de_un_dem_lleva_la_rampa_de_su_rango_medido(self, tmp_path, falso, settings):
        settings.VISOR_CACHE = str(tmp_path / "c")
        origen = tmp_path / "m.tif"
        origen.write_bytes(b"x" * 10)
        ficha = capa.leer(origen)
        assert ficha.es_dem and ficha.escala == [0.0, 4000.0]
        assert ficha.rampa[0][0] == 0.0 and ficha.rampa[-1][0] == 4000.0


# ---------------------------------------------------------------------------------------------
# Los parámetros del sol y su clave
# ---------------------------------------------------------------------------------------------


class TestElModo:
    def test_sin_modo_es_la_imagen_en_grises_y_no_pide_dem(self):
        no_dem = _ficha_de(info_de_gdal())
        modo = terreno.modo_de({}, no_dem)
        assert modo.nombre == "gris" and not modo.es_terreno and modo.sufijo == ""

    def test_los_valores_por_omision_del_sol(self):
        modo = terreno.modo_de({"modo": "sombra"}, _ficha_de())
        assert (modo.azimut_deg, modo.altura_deg, modo.exageracion_z) == (315, 45, 1.0)

    @pytest.mark.parametrize(
        "parametros",
        [
            {"az": "360"},
            {"az": "-1"},
            {"alt": "0"},
            {"alt": "91"},
            {"zf": "0"},
            {"zf": "20.5"},
            {"az": "norte"},
            {"alt": "nan"},
            {"zf": "inf"},
        ],
    )
    def test_fuera_de_rango_se_rechaza_no_se_recorta(self, parametros):
        with pytest.raises(terreno.ParametrosNoValidos):
            terreno.modo_de({"modo": "sombra", **parametros}, _ficha_de())

    def test_la_coma_decimal_vale(self):
        assert terreno.modo_de({"modo": "sombra", "zf": "1,5"}, _ficha_de()).exageracion_z == 1.5

    def test_cada_parametro_cambia_la_clave_y_el_mismo_juego_no(self):
        ficha = _ficha_de()
        base = terreno.modo_de({"modo": "sombra"}, ficha)
        iguales = terreno.modo_de({"modo": "sombra", "az": "315", "alt": "45", "zf": "1"}, ficha)
        assert iguales.sufijo == base.sufijo
        for distinto in ({"az": "100"}, {"alt": "30"}, {"zf": "3"}):
            assert terreno.modo_de({"modo": "sombra", **distinto}, ficha).sufijo != base.sufijo

    def test_la_escala_vertical_entra_en_la_clave(self):
        en_metros = terreno.modo_de({"modo": "sombra"}, _ficha_de())
        en_pies = terreno.modo_de({"modo": "sombra"}, _ficha_de(info_de_dem(unidad="ft")))
        assert en_metros.sufijo != en_pies.sufijo

    def test_sombra_y_cota_no_comparten_sufijo(self):
        ficha = _ficha_de()
        assert (
            terreno.modo_de({"modo": "sombra"}, ficha).sufijo
            != terreno.modo_de({"modo": "cota"}, ficha).sufijo
        )

    def test_un_modo_que_no_existe(self):
        with pytest.raises(terreno.ParametrosNoValidos):
            terreno.modo_de({"modo": "relieve"}, _ficha_de())

    def test_terreno_de_algo_que_no_es_un_dem(self):
        with pytest.raises(terreno.CapaNoEsDem):
            terreno.modo_de({"modo": "sombra"}, _ficha_de(info_de_gdal()))


class TestLaCacheReconoceLoDelTerreno:
    @pytest.mark.parametrize(
        "nombre",
        [
            "sombra-1a2b3c4d.tif",
            "cota-1a2b3c4d.txt",
            "sombra-1a2b3c4d-14-5-7.png",
            "cota-1a2b3c4d-14-5-7.png",
            "sombra-1a2b3c4d.tif.parcial-0a1b2c3d",
            "cota-1a2b3c4d-14-5-7.png.parcial-0a1b2c3d",
            "14-5-7.png",
            "capa.json",
        ],
    )
    def test_es_suyo_y_el_barrido_lo_puede_borrar(self, nombre):
        ruta = "ab/" + "0123456789abcdef" * 2 + "/" + nombre
        assert cache.PATRON_PROPIO.match(ruta), nombre

    @pytest.mark.parametrize(
        "nombre", ["sombra-1234.tif", "sombra-1a2b3c4d.png", "otra-1a2b3c4d.tif", "cota-xx.txt"]
    )
    def test_lo_ajeno_no_se_toca(self, nombre):
        assert not cache.PATRON_PROPIO.match("ab/" + "0123456789abcdef" * 2 + "/" + nombre)

    def test_el_barrido_cuenta_y_borra_lo_del_terreno(self, tmp_path, settings):
        settings.VISOR_CACHE = str(tmp_path / "c")
        carpeta = cache.carpeta_de("ab" + "0" * 30)
        carpeta.mkdir(parents=True)
        grande = carpeta / "sombra-1a2b3c4d.tif"
        grande.write_bytes(b"x" * 5000)
        assert cache.usado_bytes() == 5000
        cache.barrer(tope=1000)
        assert not grande.exists()


# ---------------------------------------------------------------------------------------------
# Las teselas de terreno
# ---------------------------------------------------------------------------------------------


class TestElSombreado:
    def test_una_tesela_de_sombra_es_un_png_de_256_y_viene_del_gdaldem_del_original(
        self, sesion, falso, modelo
    ):
        respuesta = _tesela(sesion, modelo, {"modo": "sombra"})
        assert respuesta.status_code == 200 and respuesta["Content-Type"] == "image/png"
        assert Image.open(io.BytesIO(respuesta.content)).size == (256, 256)
        (sombra,) = _llamadas(falso, "gdaldem", "hillshade")
        assert sombra[1] == str(modelo), "se calcula del original, solo lectura"
        assert str(modelo.parent) not in sombra[2], "y se escribe en la caché, no junto al original"
        assert _valor_de(sombra, "-az") == "315" and _valor_de(sombra, "-alt") == "45"
        assert _valor_de(sombra, "-z") == "1.0" and _valor_de(sombra, "-s") == "1.0"

    def test_los_parametros_llegan_a_gdaldem(self, sesion, falso, modelo):
        _tesela(sesion, modelo, {"modo": "sombra", "az": "90", "alt": "20", "zf": "2,5"})
        (sombra,) = _llamadas(falso, "gdaldem", "hillshade")
        assert _valor_de(sombra, "-az") == "90" and _valor_de(sombra, "-alt") == "20"
        assert _valor_de(sombra, "-z") == "2.5"

    def test_el_sombreado_entero_se_calcula_una_vez_para_todas_las_teselas(
        self, sesion, falso, modelo
    ):
        _tesela(sesion, modelo, {"modo": "sombra"})
        _tesela(sesion, modelo, {"modo": "sombra"}, z=15)
        assert len(_llamadas(falso, "gdaldem", "hillshade")) == 1
        assert falso.contar("gdalwarp") == 2

    def test_otro_sol_es_otra_clave_y_otro_calculo(self, sesion, falso, modelo):
        uno = _tesela(sesion, modelo, {"modo": "sombra", "az": "315"})
        otro = _tesela(sesion, modelo, {"modo": "sombra", "az": "135"})
        assert uno["ETag"] != otro["ETag"]
        assert len(_llamadas(falso, "gdaldem", "hillshade")) == 2

    def test_la_tesela_en_grises_y_la_de_sombra_no_comparten_etag(self, sesion, falso, modelo):
        gris = _tesela(sesion, modelo)
        sombra = _tesela(sesion, modelo, {"modo": "sombra"})
        assert gris["ETag"] != sombra["ETag"]

    def test_con_el_etag_de_la_sombra_es_304_sin_cortar_nada(self, sesion, falso, modelo):
        primera = _tesela(sesion, modelo, {"modo": "sombra"})
        antes = len(falso.llamadas)
        otra = _tesela(
            sesion, modelo, {"modo": "sombra"}, cabeceras={"If-None-Match": primera["ETag"]}
        )
        assert otra.status_code == 304
        assert len(falso.llamadas) == antes
        # ...pero ese mismo ETag **no** vale para otro sol.
        distinta = _tesela(
            sesion,
            modelo,
            {"modo": "sombra", "az": "10"},
            cabeceras={"If-None-Match": primera["ETag"]},
        )
        assert distinta.status_code == 200

    def test_la_caja_de_la_tesela_es_la_de_la_cuadricula_en_3857(self, sesion, falso, modelo):
        ficha = sesion.get(reverse("visor:capa"), {"ruta": str(modelo)}).json()
        z = ficha["zoom_maximo"]
        x, y = mercator.tesela_de_lonlat(*ficha["centro_4326"], z)
        _tesela(sesion, modelo, {"modo": "sombra"})
        corte = _llamadas(falso, "gdalwarp")[-1]
        assert _valor_de(corte, "-t_srs") == "EPSG:3857"
        caja = [float(v) for v in corte[corte.index("-te") + 1 : corte.index("-te") + 5]]
        assert caja == pytest.approx(mercator.caja_de_tesela(z, x, y))
        assert "-dstalpha" in corte, "lo que cae fuera del modelo sale transparente"

    def test_una_tesela_que_no_toca_el_modelo_es_transparente_sin_lanzar_gdal(
        self, sesion, falso, modelo
    ):
        _tesela(sesion, modelo, {"modo": "sombra"}, z=1)  # una ficha ya leída
        antes = len(falso.llamadas)
        lejos = sesion.get(
            reverse("visor:tesela", args=[17, 0, 0]), {"ruta": str(modelo), "modo": "sombra"}
        )
        assert lejos.status_code == 200 and len(falso.llamadas) == antes


class TestElColorPorCota:
    def test_una_tesela_de_cota_pasa_por_float32_y_color_relief(self, sesion, falso, modelo):
        respuesta = _tesela(sesion, modelo, {"modo": "cota"})
        assert respuesta.status_code == 200
        assert Image.open(io.BytesIO(respuesta.content)).size == (256, 256)
        corte = _llamadas(falso, "gdalwarp")[-1]
        assert _valor_de(corte, "-ot") == "Float32"
        assert _valor_de(corte, "-dstnodata") == dem.SIN_DATO_DE_LA_TESELA
        (color,) = _llamadas(falso, "gdaldem", "color-relief")
        assert "-alpha" in color

    def test_la_tabla_de_colores_es_la_rampa_de_la_capa_y_queda_en_la_cache(
        self, sesion, falso, modelo
    ):
        _tesela(sesion, modelo, {"modo": "cota"})
        (color,) = _llamadas(falso, "gdaldem", "color-relief")
        tabla = Path(color[2])
        assert tabla.parent.parent.parent == cache.carpeta()
        assert tabla.read_text(encoding="ascii") == dem.texto_de_rampa(dem.rampa(0.0, 4000.0))

    def test_no_queda_ningun_intermedio_en_la_cache(self, sesion, falso, modelo):
        _tesela(sesion, modelo, {"modo": "cota"})
        _tesela(sesion, modelo, {"modo": "sombra"})
        sobras = [p.name for p in cache.carpeta().rglob("*") if ".parcial-" in p.name]
        assert sobras == []


class TestLasSalidasSeVerifican:
    """Regla 1: que GDAL salga bien no es la prueba; lo es leer lo que dejó."""

    def test_gdaldem_que_no_deja_nada_es_502_y_no_queda_un_sombreado_a_medias(
        self, sesion, falso, modelo
    ):
        falso.escribir = False
        respuesta = _tesela(sesion, modelo, {"modo": "sombra"})
        assert respuesta.status_code == 502 and respuesta.json()["codigo"] == "sin-salida"
        assert not list(cache.carpeta().rglob("sombra-*.tif"))

    def test_un_sombreado_de_otro_tamano_no_se_da_por_bueno(self, sesion, falso, modelo):
        falso.tamano_del_sombreado = (3, 3)
        respuesta = _tesela(sesion, modelo, {"modo": "sombra"})
        assert respuesta.status_code == 502 and respuesta.json()["codigo"] == "salida-invalida"
        assert not list(cache.carpeta().rglob("sombra-*.tif"))

    def test_un_sombreado_que_no_es_de_8_bits_tampoco(self, sesion, falso, modelo):
        falso.tipo_del_sombreado = "Float32"
        respuesta = _tesela(sesion, modelo, {"modo": "sombra"})
        assert respuesta.json()["codigo"] == "salida-invalida"

    def test_una_tesela_de_cota_que_no_es_un_png_de_256(self, sesion, falso, modelo):
        falso.lado_de_salida = 100
        respuesta = _tesela(sesion, modelo, {"modo": "cota"})
        assert respuesta.status_code == 502 and respuesta.json()["codigo"] == "salida-invalida"
        assert not list(cache.carpeta().rglob("cota-*.png"))

    def test_el_original_queda_igual_en_cada_camino_de_fallo(self, sesion, falso, modelo):
        antes = _huella(modelo)
        carpeta = sorted(p.name for p in modelo.parent.iterdir())
        escenarios = [
            ({"modo": "sombra"}, {"escribir": False}),
            ({"modo": "sombra"}, {"tamano_del_sombreado": (2, 2)}),
            ({"modo": "cota"}, {"lado_de_salida": 64}),
            ({"modo": "sombra", "az": "999"}, {}),
            ({"modo": "relieve"}, {}),
            (
                {"modo": "sombra", "alt": "30"},
                {"fallar_con": motor.ErrorDeGdal("se cayó", "error-del-motor")},
            ),
        ]
        for parametros, ajustes in escenarios:
            for nombre, valor in ajustes.items():
                setattr(falso, nombre, valor)
            _tesela(sesion, modelo, parametros)
            falso.escribir, falso.lado_de_salida, falso.fallar_con = True, 256, None
            falso.tamano_del_sombreado = None
            assert _huella(modelo) == antes, (parametros, ajustes)
            assert sorted(p.name for p in modelo.parent.iterdir()) == carpeta


class TestLasNegativasDelTerreno:
    def test_sin_gdaldem_el_sombreado_esta_apagado_con_motivo_y_alternativa(
        self, sesion, falso, sin_gdaldem, modelo
    ):
        for modo in ("sombra", "cota"):
            respuesta = _tesela(sesion, modelo, {"modo": modo})
            assert respuesta.status_code == 503
            cuerpo = respuesta.json()
            assert cuerpo["codigo"] == "sin-gdaldem" and cuerpo["sugerencia"]
        assert not _llamadas(falso, "gdaldem")

    def test_sin_gdaldem_la_imagen_en_grises_sigue_y_no_se_sustituye_en_silencio(
        self, sesion, falso, sin_gdaldem, modelo
    ):
        assert _tesela(sesion, modelo).status_code == 200
        assert _tesela(sesion, modelo, {"modo": "sombra"}).status_code == 503, (
            "pidieron sombra: no se les entrega una imagen en grises que nadie pidió"
        )

    def test_la_ficha_dice_que_el_sombreado_esta_apagado_y_por_que(
        self, sesion, falso, sin_gdaldem, modelo
    ):
        ficha = sesion.get(reverse("visor:capa"), {"ruta": str(modelo)}).json()
        assert ficha["es_dem"] is True
        assert ficha["sombreado"]["disponible"] is False
        assert ficha["sombreado"]["codigo"] == "sin-gdaldem" and ficha["sombreado"]["sugerencia"]

    def test_sin_gdaldem_la_cota_y_el_perfil_siguen(self, sesion, falso, sin_gdaldem, modelo):
        punto = sesion.get(
            reverse("visor:punto"),
            {"ruta": str(modelo), "lon": -70.666, "lat": -33.473, "valor": 1},
        )
        assert punto.status_code == 200 and punto.json()["valores"]
        assert _perfil(sesion, modelo).status_code == 200

    def test_un_parametro_fuera_de_rango_es_400_con_su_motivo(self, sesion, falso, modelo):
        respuesta = _tesela(sesion, modelo, {"modo": "sombra", "az": "400"})
        assert respuesta.status_code == 400
        assert respuesta.json()["codigo"] == "parametros-no-validos"
        assert "azimut" in respuesta.json()["mensaje"].lower()
        assert not _llamadas(falso, "gdaldem")

    def test_terreno_de_una_ortofoto_es_409(self, sesion, falso, modelo):
        falso.info = info_de_gdal()
        respuesta = _tesela(sesion, modelo, {"modo": "sombra"})
        assert respuesta.status_code == 409 and respuesta.json()["codigo"] == "capa-no-es-dem"
        assert not _llamadas(falso, "gdaldem")

    def test_la_ficha_de_una_ortofoto_no_lleva_terreno(self, sesion, falso, modelo):
        falso.info = info_de_gdal()
        ficha = sesion.get(reverse("visor:capa"), {"ruta": str(modelo)}).json()
        assert ficha["es_dem"] is False and "sombreado" not in ficha


# ---------------------------------------------------------------------------------------------
# La cota bajo el cursor
# ---------------------------------------------------------------------------------------------


class TestLaCotaBajoElCursor:
    def _punto(self, sesion, modelo, **extra):
        return sesion.get(
            reverse("visor:punto"),
            {"ruta": str(modelo), "lon": -70.666, "lat": -33.473, "valor": 1, **extra},
        )

    def test_trae_su_valor(self, sesion, falso, modelo):
        falso.valores = ["512.25"]
        cuerpo = self._punto(sesion, modelo).json()
        assert cuerpo["dentro"] and cuerpo["valores"] == [512.25]

    def test_un_sin_dato_sale_como_none_y_no_como_una_altura(self, sesion, falso, modelo):
        falso.valores = ["-9999"]
        assert self._punto(sesion, modelo).json()["valores"] == [None]

    def test_el_sin_dato_float32_tolera_la_ultima_cifra(self):
        assert dem.es_sin_dato(-3.4028234663852886e38, sin_dato=-3.4028235e38, es_nan=False)
        assert not dem.es_sin_dato(-9998.0, sin_dato=-9999.0, es_nan=False)

    def test_nan_no_es_una_cota_y_no_rompe_el_json(self, sesion, falso, modelo):
        falso.valores = ["nan"]
        respuesta = self._punto(sesion, modelo)
        assert respuesta.json()["valores"] == [None]
        assert "NaN" not in respuesta.content.decode()

    def test_una_ortofoto_sigue_igual_con_su_valor_de_cada_banda(self, sesion, falso, modelo):
        falso.info = info_de_gdal()
        falso.valores = ["10", "20", "30"]
        assert self._punto(sesion, modelo).json()["valores"] == [10.0, 20.0, 30.0]


# ---------------------------------------------------------------------------------------------
# El perfil: geometría
# ---------------------------------------------------------------------------------------------


class TestLaGeodesicaDelPerfil:
    """La distancia es la geodésica del elipsoide WGS84. Valores conocidos, no nuestra cuenta:
    un grado de ecuador mide `a · π / 180` y un grado de meridiano en el ecuador, 110 574,3886 m."""

    GRADO_DE_ECUADOR_M = 6378137.0 * math.pi / 180  # 111 319,4908 m
    GRADO_DE_MERIDIANO_EN_EL_ECUADOR_M = 110574.3886

    def test_un_grado_de_ecuador(self):
        _, longitud = terreno.linea_geodesica(0.0, 0.0, 1.0, 0.0, 11)
        assert longitud == pytest.approx(self.GRADO_DE_ECUADOR_M, abs=1e-3)

    def test_un_grado_de_meridiano(self):
        _, longitud = terreno.linea_geodesica(10.0, 0.0, 10.0, 1.0, 11)
        assert longitud == pytest.approx(self.GRADO_DE_MERIDIANO_EN_EL_ECUADOR_M, abs=1e-2)

    def test_las_muestras_estan_a_distancias_iguales_y_los_extremos_son_exactos(self):
        puntos, longitud = terreno.linea_geodesica(-70.5, -33.4, -70.4, -33.5, 21)
        assert len(puntos) == 21
        assert puntos[0] == (0.0, -70.5, -33.4) and puntos[-1] == (longitud, -70.4, -33.5)
        pasos = [b[0] - a[0] for a, b in zip(puntos, puntos[1:], strict=False)]
        assert max(pasos) - min(pasos) == pytest.approx(0.0, abs=1e-6)

    def test_el_punto_medio_esta_a_la_mitad_de_la_geodesica(self):
        from pyproj import Geod

        puntos, longitud = terreno.linea_geodesica(-70.5, -33.4, -69.9, -33.9, 3)
        _, _, a_la_mitad = Geod(ellps="WGS84").inv(-70.5, -33.4, puntos[1][1], puntos[1][2])
        assert a_la_mitad == pytest.approx(longitud / 2, abs=1e-3)

    def test_dos_puntos_iguales_no_son_un_perfil(self):
        with pytest.raises(terreno.ParametrosNoValidos):
            terreno.linea_geodesica(-70.0, -33.0, -70.0, -33.0, 5)

    @pytest.mark.parametrize("n", ["1", "0", "1001", "x", "-4", "2.5"])
    def test_el_numero_de_muestras_se_comprueba(self, n):
        with pytest.raises(terreno.ParametrosNoValidos):
            terreno.muestras_de_de({"n": n})

    def test_por_omision_son_101_y_los_limites_valen(self):
        assert terreno.muestras_de_de({}) == 101
        assert terreno.muestras_de_de({"n": "2"}) == 2
        assert terreno.muestras_de_de({"n": "1000"}) == 1000

    @pytest.mark.parametrize(
        "consulta",
        [
            {},
            {"lon1": "-70", "lat1": "-33", "lon2": "-70"},
            {"lon1": "-70", "lat1": "-33", "lon2": "-70", "lat2": "91"},
            {"lon1": "-181", "lat1": "-33", "lon2": "-70", "lat2": "-33"},
            {"lon1": "nan", "lat1": "-33", "lon2": "-70", "lat2": "-33"},
        ],
    )
    def test_los_extremos_no_tienen_valor_por_omision(self, consulta):
        with pytest.raises(terreno.ParametrosNoValidos):
            terreno.extremos_de(consulta)


class TestElPerfilConHuecos:
    def _ficha(self):
        return _ficha_de()

    def _extremos(self, ficha, fuera=False):
        """De la esquina noroeste a la sureste (por dentro) o más allá del borde este."""
        (nolon, nolat), _, (selon, selat), _ = ficha.esquinas_4326
        paso = 0.0001
        fin = (selon + 0.002, selat) if fuera else (selon - paso, selat + paso)
        return (nolon + paso, nolat - paso, *fin)

    def test_un_hueco_es_none_y_no_se_interpola(self, falso, modelo):
        ficha = self._ficha()
        falso.cotas_del_perfil = ["500", "-9999", "502", "-9999", "-9999", "505", "506"]
        resultado = terreno.perfil(modelo, ficha, self._extremos(ficha), 7)
        assert [m.cota for m in resultado.muestras] == [500, None, 502, None, None, 505, 506]
        assert resultado.sin_dato == 3 and resultado.fuera == 0
        assert all(m.dentro for m in resultado.muestras)

    def test_lo_que_cae_fuera_del_modelo_es_un_hueco_y_gdal_no_lo_ve(self, falso, modelo):
        ficha = self._ficha()
        resultado = terreno.perfil(modelo, ficha, self._extremos(ficha, fuera=True), 11)
        fuera = [m for m in resultado.muestras if not m.dentro]
        assert fuera and all(m.cota is None for m in fuera)
        # A GDAL solo se le pregunta por las celdas de dentro: una columna y una fila **enteras**,
        # y la respuesta de cada pregunta se cuenta (una línea por pregunta).
        pregunta = next(e for e in falso.entradas if e)
        assert len(pregunta.splitlines()) == 11 - len(fuera)
        assert all(
            all(p.lstrip("-").isdigit() for p in linea.split()) for linea in pregunta.splitlines()
        )

    def test_una_sola_llamada_a_gdallocationinfo_por_perfil(self, falso, modelo):
        ficha = self._ficha()
        terreno.perfil(modelo, ficha, self._extremos(ficha), 51)
        assert falso.contar("gdallocationinfo") == 1
        (llamada,) = _llamadas(falso, "gdallocationinfo")
        assert llamada[:3] == ["-valonly", "-b", "1"] and llamada[-1] == str(modelo)

    def test_si_gdal_contesta_de_menos_se_rechaza_y_no_se_corre_el_perfil(self, falso, modelo):
        ficha = self._ficha()
        falso.cotas_del_perfil = ["500", "501"]
        with pytest.raises(motor.ErrorDeGdal) as fallo:
            terreno.perfil(modelo, ficha, self._extremos(ficha), 7)
        assert fallo.value.codigo == "salida-invalida"

    def test_un_valor_que_no_es_un_numero_es_un_hueco(self, falso, modelo):
        ficha = self._ficha()
        falso.cotas_del_perfil = ["", "abc", "nan", "7"]
        resultado = terreno.perfil(modelo, ficha, self._extremos(ficha), 4)
        assert [m.cota for m in resultado.muestras] == [None, None, None, 7.0]

    def test_el_primer_y_el_ultimo_punto_son_los_pedidos(self, falso, modelo):
        ficha = self._ficha()
        extremos = self._extremos(ficha)
        resultado = terreno.perfil(modelo, ficha, extremos, 5)
        a, b = resultado.muestras[0], resultado.muestras[-1]
        assert (a.lon, a.lat, b.lon, b.lat) == extremos
        assert a.distancia_m == 0.0 and b.distancia_m == pytest.approx(resultado.longitud_m)

    def test_una_ortofoto_no_tiene_perfil(self, falso, modelo):
        ficha = _ficha_de(info_de_gdal())
        with pytest.raises(terreno.CapaNoEsDem):
            terreno.perfil(modelo, ficha, (-70.66, -33.47, -70.665, -33.473), 5)


# ---------------------------------------------------------------------------------------------
# El perfil: la vista y el CSV
# ---------------------------------------------------------------------------------------------


def _perfil(sesion, modelo, **extra):
    ficha = sesion.get(reverse("visor:capa"), {"ruta": str(modelo)}).json()
    (nolon, nolat), _, (selon, selat), _ = ficha["esquinas_4326"]
    return sesion.get(
        reverse("visor:perfil"),
        {
            "ruta": str(modelo),
            "lon1": nolon + 0.0001,
            "lat1": nolat - 0.0001,
            "lon2": selon - 0.0001,
            "lat2": selat + 0.0001,
            "n": 7,
            **extra,
        },
    )


class TestLaVistaDelPerfil:
    def test_devuelve_las_muestras_con_sus_huecos_en_null(self, sesion, falso, modelo):
        falso.cotas_del_perfil = ["500", "-9999", "502", "503", "-9999", "505", "506"]
        respuesta = _perfil(sesion, modelo)
        assert respuesta.status_code == 200
        assert respuesta["Cache-Control"] == "private, no-store"
        cuerpo = json.loads(respuesta.content, parse_constant=lambda c: pytest.fail(c))
        assert [m["cota"] for m in cuerpo["muestras"]] == [500, None, 502, 503, None, 505, 506]
        assert cuerpo["n"] == 7 and cuerpo["sin_dato"] == 2 and cuerpo["fuera"] == 0
        assert (cuerpo["minimo"], cuerpo["maximo"]) == (500, 506)
        assert cuerpo["unidad_vertical"] == "m"
        assert cuerpo["referencia_vertical"] == "", "no se declara ninguna: no se inventa"
        assert cuerpo["muestras"][0]["d"] == 0.0

    def test_sin_ninguna_cota_no_hay_minimo_ni_maximo(self, sesion, falso, modelo):
        falso.cotas_del_perfil = ["-9999"] * 7
        cuerpo = _perfil(sesion, modelo).json()
        assert cuerpo["minimo"] is None and cuerpo["maximo"] is None and cuerpo["sin_dato"] == 7

    def test_el_csv_es_descargable_y_deja_las_celdas_de_los_huecos_vacias(
        self, sesion, falso, modelo
    ):
        falso.cotas_del_perfil = ["500", "-9999", "502.5", "503", "504", "505", "506"]
        respuesta = _perfil(sesion, modelo, formato="csv")
        assert respuesta.status_code == 200
        assert respuesta["Content-Type"] == "text/csv; charset=utf-8"
        assert "attachment" in respuesta["Content-Disposition"]
        assert "perfil-terreno.csv" in respuesta["Content-Disposition"]
        filas = list(csv.DictReader(io.StringIO(respuesta.content.decode("utf-8"))))
        assert list(filas[0]) == list(terreno.COLUMNAS_DEL_CSV)
        assert [f["cota"] for f in filas] == [
            "500.0000",
            "",
            "502.5000",
            "503.0000",
            "504.0000",
            "505.0000",
            "506.0000",
        ]
        assert filas[0]["distancia_m"] == "0.000"
        assert {f["unidad_vertical"] for f in filas} == {"m"}
        assert {f["referencia_vertical"] for f in filas} == {"no declarada"}

    def test_un_archivo_sin_unidad_lo_dice_en_el_csv_y_no_pone_metros(self, sesion, falso, modelo):
        falso.info = info_de_dem(unidad=None)
        filas = list(
            csv.DictReader(io.StringIO(_perfil(sesion, modelo, formato="csv").content.decode()))
        )
        assert {f["unidad_vertical"] for f in filas} == {"no declarada"}

    def test_la_unidad_de_un_archivo_hostil_no_abre_una_formula_en_el_csv(
        self, sesion, falso, modelo
    ):
        falso.info = info_de_dem(unidad='=HYPERLINK("http://malo")')
        cuerpo = _perfil(sesion, modelo, formato="csv").content.decode()
        for fila in csv.reader(io.StringIO(cuerpo)):
            for celda in fila:
                assert (
                    not celda
                    or celda[0] not in "=+-@\t\r"
                    or celda.lstrip("-").replace(".", "").isdigit()
                ), celda

    def test_la_referencia_vertical_del_archivo_sale_si_la_declara(self, sesion, falso, modelo):
        from pyproj import CRS

        falso.info = info_de_dem(wkt=CRS.from_user_input("EPSG:32719+5773").to_wkt())
        cuerpo = _perfil(sesion, modelo).json()
        assert "EGM96" in cuerpo["referencia_vertical"]

    @pytest.mark.parametrize(
        "extra",
        [
            {"n": "1"},
            {"n": "5000"},
            {"lat1": "99"},
            {"lon2": "x"},
            {"formato": "xml"},
        ],
    )
    def test_un_parametro_malo_es_400(self, sesion, falso, modelo, extra):
        respuesta = _perfil(sesion, modelo, **extra)
        assert respuesta.status_code == 400
        assert respuesta.json()["codigo"] == "parametros-no-validos"

    def test_dos_puntos_iguales_son_400(self, sesion, falso, modelo):
        respuesta = sesion.get(
            reverse("visor:perfil"),
            {"ruta": str(modelo), "lon1": -70.66, "lat1": -33.47, "lon2": -70.66, "lat2": -33.47},
        )
        assert respuesta.status_code == 400 and "mismo" in respuesta.json()["mensaje"]

    def test_una_ortofoto_es_409(self, sesion, falso, modelo):
        falso.info = info_de_gdal()
        respuesta = _perfil(sesion, modelo)
        assert respuesta.status_code == 409 and respuesta.json()["codigo"] == "capa-no-es-dem"

    def test_un_error_de_gdal_es_502_y_no_filtra_la_ruta(self, sesion, falso, modelo):
        ficha = sesion.get(reverse("visor:capa"), {"ruta": str(modelo)}).json()
        assert ficha["es_dem"]
        falso.fallar_con = motor.ErrorDeGdal(
            "gdallocationinfo terminó con error: x", "error-del-motor"
        )
        respuesta = _perfil(sesion, modelo)
        assert respuesta.status_code == 502
        assert str(modelo.parent) not in respuesta.content.decode()

    def test_el_original_queda_igual_en_cada_camino(self, sesion, falso, modelo):
        antes = _huella(modelo)
        carpeta = sorted(p.name for p in modelo.parent.iterdir())
        _perfil(sesion, modelo)
        _perfil(sesion, modelo, formato="csv")
        _perfil(sesion, modelo, n="1")
        falso.cotas_del_perfil = ["1"]
        _perfil(sesion, modelo)  # GDAL contesta de menos
        falso.fallar_con = motor.ErrorDeGdal("x", "error-del-motor")
        _perfil(sesion, modelo)
        assert _huella(modelo) == antes
        assert sorted(p.name for p in modelo.parent.iterdir()) == carpeta


class TestPermisosDelTerreno:
    def test_sin_sesion_va_a_la_entrada(self, client):
        respuesta = client.get(reverse("visor:perfil"))
        assert respuesta.status_code == 302 and reverse("login") in respuesta["Location"]
        respuesta = client.get("/mapa/teselas/3/2/2.png?modo=sombra")
        assert respuesta.status_code == 302

    def test_el_perfil_es_de_solo_lectura(self, sesion):
        url = reverse("visor:perfil")
        assert sesion.post(url).status_code == 405
        assert sesion.put(url).status_code == 405
        assert sesion.delete(url).status_code == 405

    def test_fuera_de_las_raices_es_403_en_el_perfil_y_en_la_tesela_de_terreno(
        self, sesion, falso, obra, tmp_path
    ):
        fuera = tmp_path / "secreto.tif"
        fuera.write_bytes(b"II*\x00fuera")
        antes = _huella(fuera)
        respuesta = sesion.get(
            reverse("visor:perfil"),
            {"ruta": str(fuera), "lon1": 0, "lat1": 0, "lon2": 1, "lat2": 1},
        )
        assert respuesta.status_code == 403 and respuesta.json()["codigo"] == "ruta-no-permitida"
        respuesta = sesion.get(
            reverse("visor:tesela", args=[3, 2, 2]), {"ruta": str(fuera), "modo": "sombra"}
        )
        assert respuesta.status_code == 403
        assert falso.llamadas == [], "ni siquiera se le preguntó a GDAL"
        assert _huella(fuera) == antes

    def test_otra_extension_no_llega_a_gdal_en_el_perfil(self, sesion, falso, obra):
        ajeno = obra / "capa.vrt"
        ajeno.write_text("<VRTDataset/>")
        respuesta = sesion.get(
            reverse("visor:perfil"),
            {"ruta": str(ajeno), "lon1": 0, "lat1": 0, "lon2": 1, "lat2": 1},
        )
        assert (
            respuesta.status_code == 422 and respuesta.json()["codigo"] == "formato-no-reconocido"
        )
        assert falso.llamadas == []

    def test_sin_gdal_el_perfil_dice_por_que(self, sesion, modelo, monkeypatch):
        monkeypatch.setattr(
            motor, "disponibilidad", lambda: Disponibilidad.no("sin-gdal", "Falta GDAL.")
        )
        respuesta = _perfil_simple(sesion, modelo)
        assert respuesta.status_code == 503 and respuesta.json()["codigo"] == "sin-gdal"


def _perfil_simple(sesion, modelo):
    return sesion.get(
        reverse("visor:perfil"),
        {"ruta": str(modelo), "lon1": 0, "lat1": 0, "lon2": 1, "lat2": 1},
    )


# ---------------------------------------------------------------------------------------------
# La pantalla
# ---------------------------------------------------------------------------------------------


class TestLaPantallaDeTerreno:
    def test_un_dem_trae_su_panel_de_terreno_y_su_perfil(self, sesion, falso, modelo):
        html = sesion.get(reverse("visor:inicio"), {"ruta": str(modelo)}).content.decode()
        assert 'id="terreno"' in html and 'id="perfil"' in html
        assert 'data-perfil="' + reverse("visor:perfil") + '"' in html
        for etiqueta in ("Imagen en grises", "Sombreado", "Color por cota", "Azimut del sol"):
            assert etiqueta in html
        # Sin hover: el perfil se marca con ratón, dedo o teclado y su estado se dice en el botón.
        assert 'aria-pressed="false"' in html and "Marcar perfil" in html
        assert "Descargar CSV" in html

    def test_el_panel_dice_lo_que_el_archivo_no_declara(self, sesion, falso, modelo):
        falso.info = info_de_dem(unidad=None)
        html = sesion.get(reverse("visor:inicio"), {"ruta": str(modelo)}).content.decode()
        assert "Referencia vertical" in html and "no declarada" in html
        assert "no declara su unidad vertical" in html
        assert "sobre el nivel del mar" not in html

    def test_con_gdaldem_el_sombreado_es_lo_que_se_ve_primero(self, sesion, falso, modelo):
        html = sesion.get(reverse("visor:inicio"), {"ruta": str(modelo)}).content.decode()
        marcada = html.split('value="sombra"')[1].split(">")[0]
        assert "checked" in marcada and "disabled" not in marcada

    def test_sin_gdaldem_se_muestra_apagado_con_motivo_y_no_oculto(
        self, sesion, falso, sin_gdaldem, modelo
    ):
        html = sesion.get(reverse("visor:inicio"), {"ruta": str(modelo)}).content.decode()
        for modo in ("sombra", "cota"):
            etiqueta = html.split(f'value="{modo}"')[1].split(">")[0]
            assert "disabled" in etiqueta and 'aria-describedby="terreno-motivo"' in etiqueta
        assert 'id="terreno-motivo"' in html and 'data-motivo="sin-gdaldem"' in html
        assert "Falta gdaldem." in html and "Instale QGIS." in html
        assert "Imagen en grises" in html
        gris = html.split('value="gris"')[1].split(">")[0]
        assert "checked" in gris

    def test_una_ortofoto_no_lleva_panel_de_terreno(self, sesion, falso, modelo):
        falso.info = info_de_gdal()
        html = sesion.get(reverse("visor:inicio"), {"ruta": str(modelo)}).content.decode()
        assert 'id="terreno"' not in html and 'id="perfil"' not in html

    def test_el_javascript_es_propio_y_no_pide_nada_a_otro_origen(self):
        js = (Path(__file__).resolve().parents[2] / "static" / "js" / "visor.js").read_text(
            encoding="utf-8"
        )
        assert "http://" not in js and "w3.org" not in js
        assert "https://" not in js
        assert "innerHTML" not in js, "todo texto del servidor entra con textContent"
        assert "hover" not in js.lower() and "mouseover" not in js.lower()


def test_un_hueco_no_escribe_nan_en_el_csv():
    resultado = terreno.Perfil(
        (terreno.Muestra(0, 0.0, -70.0, -33.0, 1.0, 2.0, True, None),), 0.0, "m", ""
    )
    assert "nan" not in terreno.csv_del_perfil(resultado).lower()
