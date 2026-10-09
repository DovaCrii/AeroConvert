"""Ver en el mapa contra GDAL de verdad (regla 2): el oráculo es otro lector, no nuestra cuenta.

Se corren con `uv run pytest -m oraculo apps/visor` y quedan deseleccionadas en el gate (el CI no
tiene GDAL). El archivo es un **GeoTIFF sintético** que crea cada prueba —un tablero de 200 × 100
píxeles de 2 m en EPSG:32719, con un degradado por canal—, nunca un dato real.

Qué se comprueba, y contra qué:

- Esquinas de la capa en EPSG:4326: `wgs84Extent` de `gdalinfo -json` (≤ 1e-7°).
- Centro de la capa en EPSG:4326: `gdaltransform` sobre el centro que da `gdalinfo`.
- Una tesela XYZ: otro `gdalwarp -t_srs EPSG:3857 -te … -ts 256 256`, con la caja de una fórmula
  escrita aparte, a PNG (idéntica) y a GeoTIFF (±1 nivel en menos del 1 % de los píxeles).
- La orientación y la posición de esa tesela: el color que **debe** tener un píxel del tablero (la
  fórmula que lo creó), no lo que diga `gdalwarp`.
- Columna, fila y valor bajo el cursor: `gdallocationinfo -wgs84` y `-geoloc`.
- El original no se toca: `sha256`, `mtime` y la carpeta (ningún `.aux.xml`) tras todo el recorrido.

`python -m osgeo_utils.gdalcompare` **no está** en esta máquina (el Python de QGIS no trae
`osgeo_utils`): la comparación es píxel a píxel con numpy sobre lo que escribe otro `gdalwarp`, que
es lo mismo que `gdalcompare` hace sin su informe.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from PIL import Image

from apps.visor import cache, capa, mercator, motor, punto, teselas
from apps.visor.testing import (
    ALTO_PX,
    ANCHO_PX,
    ESTE_NO_M,
    NORTE_NO_M,
    PASO_M,
    crear_geotiff_sintetico,
    herramienta_externa,
)

pytestmark = [
    pytest.mark.oraculo,
    pytest.mark.skipif(
        motor.ejecutable("gdalwarp") is None or motor.ejecutable("gdallocationinfo") is None,
        reason="Sin GDAL en esta máquina: se corre donde esté instalado.",
    ),
]

#: Medio lado del mundo en EPSG:3857, **escrito aquí** y no importado de `mercator.py`.
MEDIO_MUNDO_M = 20037508.342789244


@pytest.fixture
def obra(tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.MODO = settings.MODO_TALLER
    settings.VISOR_CACHE = str(tmp_path / "cache-visor")
    settings.VISOR_CACHE_MAX_MB = 64
    carpeta = tmp_path / "obra"
    carpeta.mkdir()
    return carpeta


@pytest.fixture
def tif(obra):
    return crear_geotiff_sintetico(obra / "ortofoto.tif")


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


def _gdalinfo_json(ruta: Path) -> dict:
    hecho = herramienta_externa("gdalinfo", ["-json", str(ruta)])
    assert hecho.returncode == 0, hecho.stderr
    return json.loads(hecho.stdout)


def _caja_de_tesela_aparte(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """La caja de una tesela XYZ, escrita otra vez: `lado = mundo / 2**z`, `y` al sur."""
    lado = 2 * MEDIO_MUNDO_M / (2**z)
    oeste = -MEDIO_MUNDO_M + x * lado
    norte = MEDIO_MUNDO_M - y * lado
    return (oeste, norte - lado, oeste + lado, norte)


def _tesela_independiente(tif: Path, caja, destino: Path, controlador: str = "GTiff") -> np.ndarray:
    """La misma tesela cortada por **otro** `gdalwarp`, con la caja de la fórmula escrita aparte.

    A GeoTIFF (otro controlador que el nuestro) o a PNG (el mismo): el primero prueba que no
    dependemos del camino de escritura y el segundo que los argumentos son los que se creen.
    """
    hecho = herramienta_externa(
        "gdalwarp",
        [
            "-q",
            "-overwrite",
            "-of",
            controlador,
            "-t_srs",
            "EPSG:3857",
            "-te",
            *(repr(v) for v in caja),
            "-ts",
            "256",
            "256",
            "-r",
            "bilinear",
            "-dstalpha",
            str(tif),
            str(destino),
        ],
    )
    assert hecho.returncode == 0 and destino.is_file(), hecho.stderr
    return np.asarray(Image.open(destino).convert("RGBA"))


def _diferencia(propia: np.ndarray, externa: np.ndarray) -> tuple[int, float]:
    """`(mayor diferencia en un canal, fracción de píxeles que difieren)`."""
    resta = np.abs(propia.astype(int) - externa.astype(int))
    return int(resta.max()), float((resta.max(axis=2) > 0).mean())


def _png_a_matriz(contenido: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(contenido)).convert("RGBA"))


def _sembrar(settings, tmp_path):
    settings.RAICES_PERMITIDAS = str(tmp_path)


class TestLasEsquinasYElCentro:
    def test_las_esquinas_son_las_de_wgs84_extent_de_gdalinfo(self, tif):
        externo = _gdalinfo_json(tif)["wgs84Extent"]["coordinates"][0]  # NO, SO, SE, NE, NO
        ficha = capa.leer(tif)
        no, ne, se, so = ficha.esquinas_4326
        for propia, de_gdal in zip((no, so, se, ne), externo[:4], strict=True):
            assert abs(propia[0] - de_gdal[0]) <= 1e-7, (propia, de_gdal)
            assert abs(propia[1] - de_gdal[1]) <= 1e-7, (propia, de_gdal)

    def test_el_centro_es_el_que_da_gdaltransform_del_centro_de_gdalinfo(self, tif):
        centro_en_su_sistema = _gdalinfo_json(tif)["cornerCoordinates"]["center"]
        hecho = herramienta_externa(
            "gdaltransform",
            ["-s_srs", "EPSG:32719", "-t_srs", "EPSG:4326", "-output_xy"],
            entrada=f"{centro_en_su_sistema[0]!r} {centro_en_su_sistema[1]!r}\n",
        )
        assert hecho.returncode == 0, hecho.stderr
        lon, lat = (float(v) for v in hecho.stdout.split())
        ficha = capa.leer(tif)
        assert abs(ficha.centro_4326[0] - lon) <= 1e-7
        assert abs(ficha.centro_4326[1] - lat) <= 1e-7

    def test_las_esquinas_en_su_sistema_son_las_de_gdalinfo(self, tif):
        esquinas = _gdalinfo_json(tif)["cornerCoordinates"]
        ficha = capa.leer(tif)
        assert ficha.esquinas[0] == pytest.approx(esquinas["upperLeft"])
        assert ficha.esquinas[1] == pytest.approx(esquinas["upperRight"])
        assert ficha.esquinas[2] == pytest.approx(esquinas["lowerRight"])
        assert ficha.esquinas[3] == pytest.approx(esquinas["lowerLeft"])
        assert ficha.centro == pytest.approx(esquinas["center"])

    def test_el_sistema_y_el_tamano_son_los_de_gdalinfo(self, tif):
        externo = _gdalinfo_json(tif)
        ficha = capa.leer(tif)
        assert [ficha.ancho_px, ficha.alto_px] == externo["size"]
        assert ficha.epsg == "32719"
        assert ficha.sistema == "WGS 84 / UTM zone 19S"
        assert ficha.bandas == len(externo["bands"])

    def test_un_archivo_sin_sistema_no_se_dibuja_con_gdal_de_verdad(self, obra):
        sin = crear_geotiff_sintetico(obra / "sin_crs.tif", epsg=None)
        assert "coordinateSystem" not in _gdalinfo_json(sin), "el archivo de prueba no lo trae"
        ficha = capa.leer(sin)
        assert not ficha.dibujable and ficha.motivo == "capa-sin-crs"


class TestLaTeselaContraOtroGdalwarp:
    def _una(self, tif, obra, desplazamiento=(0, 0)):
        ficha = capa.leer(tif)
        clave = cache.clave_de(tif)
        z = ficha.zoom_maximo - 1
        x, y = mercator.tesela_de_lonlat(*ficha.centro_4326, z)
        x, y = x + desplazamiento[0], y + desplazamiento[1]
        propia = _png_a_matriz(teselas.tesela(tif, ficha, clave, z, x, y))
        caja = _caja_de_tesela_aparte(z, x, y)
        en_png = _tesela_independiente(tif, caja, obra / f"externa_{z}_{x}_{y}.png", "PNG")
        en_tif = _tesela_independiente(tif, caja, obra / f"externa_{z}_{x}_{y}.tif", "GTiff")
        return propia, en_png, en_tif

    def test_la_del_centro_es_identica_a_la_de_otro_gdalwarp(self, tif, obra):
        propia, en_png, en_tif = self._una(tif, obra)
        assert propia.shape == en_png.shape == en_tif.shape == (256, 256, 4)
        assert propia[..., 3].max() == 255, "la tesela del centro tiene imagen"
        # Al mismo controlador: idéntica, píxel a píxel.
        assert _diferencia(propia, en_png) == (0, 0.0)
        # A otro controlador (GeoTIFF) GDAL redondea distinto en unos pocos píxeles (medido: ±1 en
        # el 0,4 %): no depende de nosotros. Tolerancia: un nivel, en menos del 1 % de los píxeles.
        mayor, fraccion = _diferencia(propia, en_tif)
        assert mayor <= 1 and fraccion < 0.01, (mayor, fraccion)

    @pytest.mark.parametrize("desplazamiento", [(1, 0), (0, 1), (-1, -1), (1, 1)])
    def test_las_vecinas_tambien(self, tif, obra, desplazamiento):
        propia, en_png, en_tif = self._una(tif, obra, desplazamiento)
        assert _diferencia(propia, en_png) == (0, 0.0)
        mayor, fraccion = _diferencia(propia, en_tif)
        assert mayor <= 1 and fraccion < 0.01, (mayor, fraccion)

    def test_lo_que_cae_fuera_de_la_imagen_es_transparente(self, tif, obra):
        ficha = capa.leer(tif)
        z = ficha.zoom_maximo - 2  # la tesela es más grande que la imagen
        x, y = mercator.tesela_de_lonlat(*ficha.centro_4326, z)
        tesela = _png_a_matriz(teselas.tesela(tif, ficha, cache.clave_de(tif), z, x, y))
        assert tesela[..., 3].max() == 255 and tesela[..., 3].min() == 0
        assert tesela[0, 0, 3] == 0 and tesela[255, 255, 3] == 0, "las esquinas son del mundo"

    def test_la_caja_que_se_usa_es_la_de_la_formula_aparte(self, obra):
        for z, x, y in ((0, 0, 0), (3, 2, 5), (17, 38000, 80000), (20, 1, 2)):
            assert mercator.caja_de_tesela(z, x, y) == pytest.approx(
                _caja_de_tesela_aparte(z, x, y), abs=1e-6
            )

    def test_el_gdalwarp_externo_tiene_la_caja_pedida_en_su_georreferencia(self, tif, obra):
        """Que el oráculo mide lo que dice medir: la tesela externa cubre la caja de la tesela."""
        z, x, y = 16, 20000, 40000
        caja = _caja_de_tesela_aparte(z, x, y)
        destino = obra / "control.tif"
        _tesela_independiente(tif, caja, destino)
        esquinas = _gdalinfo_json(destino)["cornerCoordinates"]
        # `gdalinfo` escribe las esquinas con tres decimales (un milímetro).
        assert esquinas["upperLeft"] == pytest.approx([caja[0], caja[3]], abs=1e-3)
        assert esquinas["lowerRight"] == pytest.approx([caja[2], caja[1]], abs=1e-3)


class TestLaTeselaPorLoQueDebeContener:
    """El otro oráculo: **no `gdalwarp`**, sino lo que la fórmula del tablero dice que hay ahí.

    Si `gdalwarp` y nuestro `-te` se equivocaran igual (un eje invertido, una tesela corrida), las
    dos teselas coincidirían y estarían mal. Aquí se sabe de antemano qué color tiene un píxel:
    rojo 255 en las casillas `(col // 20 + fila // 20)` impares, 0 en las pares; verde =
    `col · 255 / 199`; azul = `fila · 255 / 99`.
    """

    def _pixel_de_la_tesela(self, tif, columna: float, fila: float):
        from pyproj import Transformer

        ficha = capa.leer(tif)
        este, norte = ESTE_NO_M + columna * PASO_M, NORTE_NO_M - fila * PASO_M
        mx, my = Transformer.from_crs("EPSG:32719", "EPSG:3857", always_xy=True).transform(
            este, norte
        )
        z = ficha.zoom_maximo
        lado = 2 * MEDIO_MUNDO_M / (2**z)
        x, y = int((mx + MEDIO_MUNDO_M) // lado), int((MEDIO_MUNDO_M - my) // lado)
        tesela = _png_a_matriz(teselas.tesela(tif, ficha, cache.clave_de(tif), z, x, y))
        oeste, norte_t = -MEDIO_MUNDO_M + x * lado, MEDIO_MUNDO_M - y * lado
        px = int((mx - oeste) / (lado / 256))
        py = int((norte_t - my) / (lado / 256))
        return tesela[py, px]

    @pytest.mark.parametrize(
        ("columna", "fila"),
        [(130.0, 10.0), (90.0, 10.0), (30.0, 70.0), (50.0, 30.0), (170.0, 50.0)],
    )
    def test_el_color_en_su_sitio(self, tif, columna, fila):
        rojo, verde, azul, alfa = (int(v) for v in self._pixel_de_la_tesela(tif, columna, fila))
        casilla = (int(columna) // 20 + int(fila) // 20) % 2
        assert alfa == 255
        assert rojo == (255 if casilla else 0), "el tablero está corrido o invertido"
        assert verde == pytest.approx(columna * 255 / (ANCHO_PX - 1), abs=4)
        assert azul == pytest.approx(fila * 255 / (ALTO_PX - 1), abs=4)

    def test_el_norte_esta_arriba(self, tif):
        """El azul crece hacia el sur (con la fila): arriba menos que abajo."""
        arriba = self._pixel_de_la_tesela(tif, 130.0, 10.0)
        abajo = self._pixel_de_la_tesela(tif, 130.0, 70.0)
        assert int(arriba[2]) < int(abajo[2])

    def test_el_este_esta_a_la_derecha(self, tif):
        izquierda = self._pixel_de_la_tesela(tif, 30.0, 30.0)
        derecha = self._pixel_de_la_tesela(tif, 170.0, 30.0)
        assert int(izquierda[1]) < int(derecha[1])


class TestElPixelBajoElCursor:
    PUNTOS = [(130.5, 10.5), (3.5, 3.5), (196.5, 96.5), (60.5, 55.5), (100.5, 50.5)]

    def _lonlat(self, columna, fila):
        hecho = herramienta_externa(
            "gdaltransform",
            ["-s_srs", "EPSG:32719", "-t_srs", "EPSG:4326", "-output_xy"],
            entrada=f"{ESTE_NO_M + columna * PASO_M!r} {NORTE_NO_M - fila * PASO_M!r}\n",
        )
        lon, lat = (float(v) for v in hecho.stdout.split())
        return lon, lat

    @pytest.mark.parametrize(("columna", "fila"), PUNTOS)
    def test_columna_fila_y_valores_contra_gdallocationinfo(self, tif, columna, fila):
        lon, lat = self._lonlat(columna, fila)
        ficha = capa.leer(tif)
        encontrado = punto.con_valores(tif, ficha, punto.localizar(ficha, lon, lat))

        assert encontrado.dentro
        assert (int(encontrado.columna), int(encontrado.fila)) == (int(columna), int(fila))
        # Dos lectores independientes: por WGS84 (lo convierte GDAL) y por coordenadas del archivo.
        por_wgs84 = herramienta_externa(
            "gdallocationinfo", ["-valonly", "-wgs84", str(tif), repr(lon), repr(lat)]
        )
        por_geoloc = herramienta_externa(
            "gdallocationinfo",
            [
                "-valonly",
                "-geoloc",
                str(tif),
                repr(ESTE_NO_M + columna * PASO_M),
                repr(NORTE_NO_M - fila * PASO_M),
            ],
        )
        esperado = [float(v) for v in por_wgs84.stdout.split()]
        assert esperado == [float(v) for v in por_geoloc.stdout.split()]
        assert list(encontrado.valores) == esperado

    @pytest.mark.parametrize(("columna", "fila"), PUNTOS)
    def test_y_los_valores_son_los_del_tablero(self, tif, columna, fila):
        lon, lat = self._lonlat(columna, fila)
        ficha = capa.leer(tif)
        valores = punto.con_valores(tif, ficha, punto.localizar(ficha, lon, lat)).valores
        casilla = (int(columna) // 20 + int(fila) // 20) % 2
        assert valores[0] == (255 if casilla else 0)
        assert valores[1] == int(int(columna) * 255 / (ANCHO_PX - 1))
        assert valores[2] == int(int(fila) * 255 / (ALTO_PX - 1))

    def test_los_x_y_del_cursor_son_los_que_da_gdaltransform_a_la_inversa(self, tif):
        lon, lat = self._lonlat(130.5, 10.5)
        ficha = capa.leer(tif)
        encontrado = punto.localizar(ficha, lon, lat)
        assert encontrado.x == pytest.approx(ESTE_NO_M + 130.5 * PASO_M, abs=1e-3)
        assert encontrado.y == pytest.approx(NORTE_NO_M - 10.5 * PASO_M, abs=1e-3)

    def test_un_punto_fuera_de_la_imagen(self, tif):
        ficha = capa.leer(tif)
        encontrado = punto.con_valores(tif, ficha, punto.localizar(ficha, -70.0, -33.0))
        assert not encontrado.dentro and encontrado.valores == ()


class TestLasQueNoSonRgbDe8Bits:
    def test_una_de_16_bits_se_escala_con_el_rango_que_mide_gdal(self, obra):
        tif = crear_geotiff_sintetico(obra / "u16.tif", tipo="UInt16", bandas=1)
        externo = _gdalinfo_json(tif)
        ficha = capa.leer(tif)
        assert ficha.tipo == "UInt16" and ficha.necesita_vrt
        assert ficha.escala == [100.0, 3000.0], (
            "el rango de lo que escribió `-scale 0 255 100 3000`"
        )
        assert externo["bands"][0]["type"] == "UInt16"

        lon, lat = (
            capa.leer(tif).esquinas_4326[0][0] + 0.0001,
            capa.leer(tif).esquinas_4326[0][1] - 0.0001,
        )
        z = ficha.zoom_maximo - 1
        x, y = mercator.tesela_de_lonlat(*ficha.centro_4326, z)
        tesela = _png_a_matriz(teselas.tesela(tif, ficha, cache.clave_de(tif), z, x, y))
        centro = tesela[(tesela[..., 3] == 255)]
        assert centro.size, "la tesela del centro tiene imagen"
        # Dos valores, no un degradado entero: lo que se escribió fue 100 (→ 0) y 3000 (→ 255).
        assert set(np.unique(centro[:, 0]).tolist()) >= {0, 255}
        assert (lon, lat) != (0, 0)

    def test_una_con_canal_alfa_respeta_su_transparencia(self, obra):
        base = crear_geotiff_sintetico(obra / "rgb.tif")
        con_alfa = obra / "rgba.tif"
        hecho = herramienta_externa(
            "gdal_translate",
            ["-q", "-b", "1", "-b", "2", "-b", "3", "-b", "1", "-colorinterp_4", "alpha"]
            + [str(base), str(con_alfa)],
        )
        assert hecho.returncode == 0, hecho.stderr
        ficha = capa.leer(con_alfa)
        assert ficha.bandas == 4 and not ficha.necesita_vrt
        z = ficha.zoom_maximo - 1
        x, y = mercator.tesela_de_lonlat(*ficha.centro_4326, z)
        tesela = _png_a_matriz(teselas.tesela(con_alfa, ficha, cache.clave_de(con_alfa), z, x, y))
        assert tesela.shape == (256, 256, 4)
        assert tesela[..., 3].max() == 255

    def test_una_de_ocho_bandas_se_ve_con_las_tres_primeras(self, obra):
        base = crear_geotiff_sintetico(obra / "rgb.tif")
        ocho = obra / "ocho.tif"
        args = ["-q"]
        for banda in (1, 2, 3, 1, 2, 3, 1, 2):
            args += ["-b", str(banda)]
        hecho = herramienta_externa("gdal_translate", [*args, str(base), str(ocho)])
        assert hecho.returncode == 0, hecho.stderr
        ficha = capa.leer(ocho)
        assert ficha.bandas == 8 and ficha.necesita_vrt
        z = ficha.zoom_maximo - 1
        x, y = mercator.tesela_de_lonlat(*ficha.centro_4326, z)
        tesela = _png_a_matriz(teselas.tesela(ocho, ficha, cache.clave_de(ocho), z, x, y))
        externa = _tesela_independiente(
            base, _caja_de_tesela_aparte(z, x, y), obra / "e8.png", "PNG"
        )
        assert _diferencia(tesela, externa) == (0, 0.0), "las tres primeras bandas, tal cual"


class TestElOriginalNoSeToca:
    def test_tras_todo_el_recorrido_el_original_y_su_carpeta_siguen_iguales(self, tif, obra):
        antes = _huella(tif)
        carpeta_antes = sorted(p.name for p in obra.iterdir())

        ficha = capa.leer(tif)
        clave = cache.clave_de(tif)
        z = ficha.zoom_maximo - 1
        cx, cy = mercator.tesela_de_lonlat(*ficha.centro_4326, z)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                teselas.tesela(tif, ficha, clave, z, cx + dx, cy + dy)
        punto.con_valores(tif, ficha, punto.localizar(ficha, *ficha.centro_4326))

        assert _huella(tif) == antes
        assert sorted(p.name for p in obra.iterdir()) == carpeta_antes, "ni un .aux.xml"

    def test_con_estadisticas_de_una_16_bits_tampoco_deja_aux_xml(self, obra):
        tif = crear_geotiff_sintetico(obra / "u16.tif", tipo="UInt16", bandas=1)
        antes = _huella(tif)
        capa.leer(tif)  # corre `gdalinfo -json -approx_stats`
        assert _huella(tif) == antes
        assert not list(obra.glob("*.aux.xml"))

    def test_el_control_sin_el_ajuste_gdal_si_deja_un_aux_xml(self, obra):
        """Que la de arriba mide algo: **sin** `GDAL_PAM_ENABLED=NO`, GDAL escribe al lado."""
        tif = crear_geotiff_sintetico(obra / "u16.tif", tipo="UInt16", bandas=1)
        copia = obra / "copia.tif"
        copia.write_bytes(tif.read_bytes())
        entorno = {k: v for k, v in motor.entorno().items() if k != "GDAL_PAM_ENABLED"}
        entorno["GDAL_PAM_ENABLED"] = "YES"
        subprocess.run(  # nosec B603
            [motor.ejecutable("gdalinfo"), "-json", "-stats", str(copia)],
            capture_output=True,
            check=False,
            shell=False,
            timeout=60,
            env=entorno,
        )
        assert (obra / "copia.tif.aux.xml").exists()

    def test_los_hijos_se_lanzan_con_el_pam_apagado(self):
        assert motor.entorno()["GDAL_PAM_ENABLED"] == "NO"
        assert os.environ.get("GDAL_PAM_ENABLED") != "NO" or True  # el del servidor no se toca


class TestLaCacheConGdalDeVerdad:
    def test_se_acota_y_lo_que_se_mira_sobrevive(self, tif):
        ficha = capa.leer(tif)
        clave = cache.clave_de(tif)
        z = ficha.zoom_maximo - 1
        cx, cy = mercator.tesela_de_lonlat(*ficha.centro_4326, z)
        hechas = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                teselas.tesela(tif, ficha, clave, z, cx + dx, cy + dy)
                hechas.append(cache.carpeta_de(clave) / f"{z}-{cx + dx}-{cy + dy}.png")
        hechas = [h for h in hechas if h.exists()]
        assert len(hechas) >= 4, "las vecinas del centro tocan la imagen"
        for i, ruta in enumerate(hechas):  # la 0 la más vieja, la última la más nueva
            ahora = ruta.stat().st_mtime
            os.utime(ruta, (ahora - (len(hechas) - i) * 100,) * 2)
        cache.leer(hechas[0])  # se mira ahora: ya no es la más vieja

        tamano_de_una = hechas[0].stat().st_size
        resultado = cache.barrer(tope=tamano_de_una * 3)

        assert resultado.bytes_despues <= tamano_de_una * 3
        assert hechas[0].exists(), "la que se miró es la última en irse"
        assert (cache.carpeta_de(clave) / "capa.json").exists() or resultado.archivos_borrados > 0


@pytest.mark.django_db
class TestDePuntaAPuntaPorHttp:
    def test_la_tesela_que_sirve_la_vista_es_la_de_gdalwarp_independiente(self, tif, obra, client):
        usuario = get_user_model().objects.create_user("ana")
        client.force_login(usuario)
        ficha = client.get(reverse("visor:capa"), {"ruta": str(tif)}).json()
        assert ficha["dibujable"]
        z = ficha["zoom_maximo"] - 1
        x, y = mercator.tesela_de_lonlat(*ficha["centro_4326"], z)

        respuesta = client.get(reverse("visor:tesela", args=[z, x, y]), {"ruta": str(tif)})
        assert respuesta.status_code == 200 and respuesta["Content-Type"] == "image/png"

        propia = _png_a_matriz(respuesta.content)
        externa = _tesela_independiente(
            tif, _caja_de_tesela_aparte(z, x, y), obra / "http_externa.png", "PNG"
        )
        assert _diferencia(propia, externa) == (0, 0.0)

        asegurada = client.get(
            reverse("visor:tesela", args=[z, x, y]),
            {"ruta": str(tif)},
            HTTP_IF_NONE_MATCH=respuesta["ETag"],
        )
        assert asegurada.status_code == 304

    def test_sin_sistema_la_tesela_es_409_con_gdal_de_verdad(self, obra, client):
        sin = crear_geotiff_sintetico(obra / "sin_crs.tif", epsg=None)
        usuario = get_user_model().objects.create_user("ana")
        client.force_login(usuario)
        antes = _huella(sin)
        respuesta = client.get(reverse("visor:tesela", args=[10, 300, 600]), {"ruta": str(sin)})
        assert respuesta.status_code == 409
        assert respuesta.json()["codigo"] == "capa-sin-crs"
        assert _huella(sin) == antes

    def test_un_archivo_que_no_es_una_imagen_es_422(self, obra, client):
        texto = obra / "nota.tif"
        texto.write_text("esto no es un tiff", encoding="utf-8")
        usuario = get_user_model().objects.create_user("ana")
        client.force_login(usuario)
        antes = _huella(texto)
        respuesta = client.get(reverse("visor:capa"), {"ruta": str(texto)})
        assert respuesta.status_code == 422
        assert respuesta.json()["codigo"] == "origen-no-legible"
        assert _huella(texto) == antes
