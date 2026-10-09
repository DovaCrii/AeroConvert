"""Terreno contra GDAL de verdad (regla 2): el oráculo es otro lector o una fórmula, no nuestra
cuenta.

Se corren con `uv run pytest -m oraculo apps/visor/test_terreno_oraculo.py` y quedan deseleccionadas
en el gate (el CI no tiene GDAL). El archivo es un **DEM sintético** que crea cada prueba: un plano
inclinado más una gaussiana, con un cuadrado de «sin dato» (`testing.crear_dem_sintetico`), en
EPSG:32719. La fórmula que lo creó (`testing.cota_conocida`) dice la cota de cada celda sin leer el
archivo. Nunca un dato real.

Qué se comprueba, y contra qué:

- **La cota bajo el cursor**, en cinco celdas (una en el hueco de «sin dato»): `gdallocationinfo
  -wgs84` y la fórmula del DEM.
- **El perfil**: cada muestra, contra `gdallocationinfo -wgs84` con la longitud y la latitud que
  devolvió el propio perfil, y contra la fórmula; la distancia, contra la del plano de UTM.
- **Una tesela de sombreado**: contra un `gdaldem hillshade` + `gdalwarp` independientes y contra la
  fórmula analítica de Horn sobre el plano (a 255 · [cos z · cos p + sen z · sen p · cos(az − as)]).
- **Una tesela de color por cota**: contra un `gdalwarp` a `Float32` + `gdaldem color-relief`
  independientes y contra la interpolación lineal de los colores a una cota conocida (512 m).
- **Lo que no se declara no se inventa**: sin unidad, sin «sin dato» y sin referencia vertical.
- **El original no se toca**: `sha256`, `mtime` y la carpeta (ningún `.aux.xml`) tras todo.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from PIL import Image

from apps.visor import cache, capa, mercator, motor, punto, terreno
from apps.visor.test_oraculo import _caja_de_tesela_aparte, _diferencia, _png_a_matriz
from apps.visor.testing import (
    ANCHO_PX,
    ESTE_NO_M,
    NORTE_NO_M,
    PASO_M,
    SIN_DATO_DEL_DEM,
    cota_conocida,
    crear_dem_sintetico,
    herramienta_externa,
)

pytestmark = [
    pytest.mark.oraculo,
    pytest.mark.django_db,
    pytest.mark.skipif(
        any(
            motor.ejecutable(h) is None
            for h in ("gdalwarp", "gdallocationinfo", "gdaldem", "gdaltransform")
        ),
        reason="Sin GDAL (con gdaldem) en esta máquina: se corre donde esté instalado.",
    ),
]

#: Las paradas de viridis **escritas otra vez aquí** (no importadas de `dem.py`).
VIRIDIS = [
    (68, 1, 84),
    (65, 68, 135),
    (42, 120, 142),
    (34, 168, 132),
    (122, 209, 81),
    (253, 231, 37),
]


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
def dem(obra):
    return crear_dem_sintetico(obra / "terreno.tif")


@pytest.fixture
def sesion(client):
    client.force_login(get_user_model().objects.create_user("ana"))
    return client


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


def _lonlat_del_centro(columna: int, fila: int) -> tuple[float, float]:
    """Longitud y latitud del **centro** de una celda, con `gdaltransform` (otro lector de PROJ)."""
    este = ESTE_NO_M + (columna + 0.5) * PASO_M
    norte = NORTE_NO_M - (fila + 0.5) * PASO_M
    hecho = herramienta_externa(
        "gdaltransform",
        ["-s_srs", "EPSG:32719", "-t_srs", "EPSG:4326", "-output_xy"],
        entrada=f"{este!r} {norte!r}\n",
    )
    assert hecho.returncode == 0, hecho.stderr
    lon, lat = (float(v) for v in hecho.stdout.split())
    return lon, lat


def _valor_de_gdal(dem: Path, lon: float, lat: float) -> float | None:
    """La celda bajo un punto según `gdallocationinfo -wgs84`; el «sin dato» del archivo, `None`."""
    hecho = herramienta_externa(
        "gdallocationinfo", ["-valonly", "-wgs84", str(dem), repr(lon), repr(lat)]
    )
    assert hecho.returncode == 0, hecho.stderr
    valor = float(hecho.stdout.split()[0])
    return None if valor == SIN_DATO_DEL_DEM else valor


def _esperado(columna: int, fila: int) -> float | None:
    return cota_conocida(columna, fila)


class TestLaFichaDelDem:
    def test_lo_que_declara_el_archivo_contra_gdalinfo(self, dem):
        ficha = capa.leer(dem)
        info = herramienta_externa("gdalinfo", ["-json", "-stats", str(dem)])
        assert info.returncode == 0, info.stderr
        banda = json.loads(info.stdout)["bands"][0]
        assert ficha.es_dem and ficha.dibujable
        assert banda["type"] == "Float32" == ficha.tipo
        assert banda["unit"] == "m" == ficha.unidad_vertical
        assert banda["noDataValue"] == SIN_DATO_DEL_DEM == ficha.nodata
        # Las estadísticas **exactas** de GDAL y la fórmula del DEM dicen lo mismo (sin el hueco)...
        cotas = [
            c for f in range(100) for k in range(ANCHO_PX) if (c := cota_conocida(k, f)) is not None
        ]
        assert [banda["minimum"], banda["maximum"]] == pytest.approx(
            [min(cotas), max(cotas)], abs=1e-2
        )
        # ...y el rango de la capa es **aproximado** (`-approx_stats` lee una muestra): GDAL 3.12.4
        # dio 611,745 de máximo contra 612,022 exacto (2026-10-09). Nunca pasa del exacto, y la
        # leyenda lo dice («rango medido de forma aproximada»).
        assert ficha.escala[0] == pytest.approx(banda["minimum"], abs=1e-2)
        assert banda["maximum"] - 1.0 <= ficha.escala[1] <= banda["maximum"] + 1e-2
        assert ficha.referencia_vertical == "", "el archivo no declara referencia vertical"
        assert ficha.escala_sombreado == 1.0

    def test_sin_unidad_ni_sin_dato_no_se_inventan(self, obra):
        sin = crear_dem_sintetico(obra / "sin-declarar.tif", unidad=None, sin_dato=None)
        ficha = capa.leer(sin)
        assert ficha.es_dem and ficha.unidad_vertical == "" and ficha.nodata is None
        # Sin «sin dato» declarado, -9999 es una altura como cualquier otra: no se esconde.
        lon, lat = _lonlat_del_centro(65, 25)  # el hueco
        encontrado = punto.con_valores(sin, ficha, punto.localizar(ficha, lon, lat))
        assert encontrado.valores == (SIN_DATO_DEL_DEM,)

    def test_una_referencia_vertical_compuesta_es_la_que_dice_gdalsrsinfo(self, obra):
        compuesto = crear_dem_sintetico(obra / "egm.tif", epsg="EPSG:32719+5773")
        ficha = capa.leer(compuesto)
        hecho = herramienta_externa("gdalsrsinfo", ["-o", "wkt2", str(compuesto)])
        assert hecho.returncode == 0, hecho.stderr
        nombre = re.search(r'VERTCRS\["([^"]+)"', hecho.stdout)
        assert nombre, hecho.stdout
        assert ficha.referencia_vertical == nombre.group(1)
        assert ficha.dibujable and ficha.es_dem


class TestLaCotaBajoElCursor:
    #: Cinco celdas (columna, fila): una al azar, la cima de la gaussiana, un borde, una esquina y
    #: una dentro del hueco de «sin dato».
    CELDAS = [(10, 10), (140, 40), (0, 0), (199, 99), (65, 25)]

    @pytest.mark.parametrize(("columna", "fila"), CELDAS)
    def test_contra_gdallocationinfo_y_la_formula(self, sesion, dem, columna, fila):
        lon, lat = _lonlat_del_centro(columna, fila)
        respuesta = sesion.get(
            reverse("visor:punto"),
            {"ruta": str(dem), "lon": repr(lon), "lat": repr(lat), "valor": 1},
        )
        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["dentro"] and (int(cuerpo["columna"]), int(cuerpo["fila"])) == (columna, fila)
        propio = cuerpo["valores"][0]
        otro = _valor_de_gdal(dem, lon, lat)
        esperado = _esperado(columna, fila)
        if esperado is None:
            assert propio is None and otro is None, "el hueco no es una cota"
        else:
            assert propio == pytest.approx(otro, abs=1e-3)
            assert propio == pytest.approx(esperado, abs=1e-3)

    def test_fuera_del_modelo_no_hay_cota(self, sesion, dem):
        ficha = sesion.get(reverse("visor:capa"), {"ruta": str(dem)}).json()
        lon, lat = ficha["esquinas_4326"][2]  # sureste
        cuerpo = sesion.get(
            reverse("visor:punto"),
            {"ruta": str(dem), "lon": lon + 0.01, "lat": lat - 0.01, "valor": 1},
        ).json()
        assert cuerpo["dentro"] is False and cuerpo["valores"] == []


class TestElPerfil:
    """Una fila de la rejilla, de la celda (40, 25) a la (90, 25): 51 muestras, una por celda, y la
    fila 25 cruza el hueco de «sin dato» (columnas 60 a 69)."""

    def _consulta(self, dem, n=51):
        (lon1, lat1), (lon2, lat2) = _lonlat_del_centro(40, 25), _lonlat_del_centro(90, 25)
        return {
            "ruta": str(dem),
            "lon1": repr(lon1),
            "lat1": repr(lat1),
            "lon2": repr(lon2),
            "lat2": repr(lat2),
            "n": n,
        }

    def test_cada_muestra_contra_gdallocationinfo_y_la_formula(self, sesion, dem):
        cuerpo = sesion.get(reverse("visor:perfil"), self._consulta(dem)).json()
        muestras = cuerpo["muestras"]
        assert len(muestras) == 51
        for i, m in enumerate(muestras):
            esperado = _esperado(40 + i, 25)
            otro = _valor_de_gdal(dem, m["lon"], m["lat"])
            if esperado is None:
                assert m["cota"] is None and otro is None, i
            else:
                assert m["cota"] == pytest.approx(otro, abs=1e-3), i
                assert m["cota"] == pytest.approx(esperado, abs=1e-3), i
        huecos = [m["i"] for m in muestras if m["cota"] is None]
        assert huecos == list(range(20, 30)), "el hueco son las columnas 60 a 69, ni más ni menos"
        assert cuerpo["sin_dato"] == 10 and cuerpo["fuera"] == 0
        assert cuerpo["unidad_vertical"] == "m"

    def test_la_distancia_es_la_de_la_rejilla_corregida_por_la_escala_de_utm(self, sesion, dem):
        """50 celdas de 2 m son 100 m en el plano de UTM; la geodésica del elipsoide es esa
        distancia dividida por el factor de escala del lugar. A 1,67° del meridiano central (-69°) y
        33,5° de latitud, k = 0,9996 · (1 + (Δλ · cos φ)² / 2) ≈ 0,99989: la geodésica es ~0,011 %
        más larga. Se acota entre 0,005 % y 0,02 %: una cuenta de ancha holgura, no la nuestra."""
        cuerpo = sesion.get(reverse("visor:perfil"), self._consulta(dem)).json()
        plano_m = 50 * PASO_M
        assert plano_m * 1.00005 < cuerpo["longitud_m"] < plano_m * 1.0002
        pasos = np.diff([m["d"] for m in cuerpo["muestras"]])
        assert pasos == pytest.approx(cuerpo["longitud_m"] / 50, abs=2e-3)

    def test_el_csv_tiene_lo_mismo_que_el_json_y_los_huecos_vacios(self, sesion, dem):
        consulta = self._consulta(dem)
        json_ = sesion.get(reverse("visor:perfil"), consulta).json()
        respuesta = sesion.get(reverse("visor:perfil"), {**consulta, "formato": "csv"})
        assert respuesta["Content-Type"].startswith("text/csv")
        filas = list(csv.DictReader(io.StringIO(respuesta.content.decode("utf-8"))))
        assert len(filas) == 51
        for fila, m in zip(filas, json_["muestras"], strict=True):
            assert (fila["cota"] == "") == (m["cota"] is None)
            if m["cota"] is not None:
                assert float(fila["cota"]) == pytest.approx(m["cota"], abs=1e-4)
            assert float(fila["distancia_m"]) == pytest.approx(m["d"], abs=1e-3)
        assert {f["unidad_vertical"] for f in filas} == {"m"}
        assert {f["referencia_vertical"] for f in filas} == {"no declarada"}

    def test_lo_que_cae_fuera_del_modelo_es_hueco_y_no_cero(self, sesion, dem):
        consulta = self._consulta(dem, n=21)
        lon2, lat2 = _lonlat_del_centro(260, 25)  # 120 celdas al este del borde... fuera
        consulta.update(lon2=repr(lon2), lat2=repr(lat2))
        cuerpo = sesion.get(reverse("visor:perfil"), consulta).json()
        fuera = [m for m in cuerpo["muestras"] if not m["dentro"]]
        assert fuera and all(m["cota"] is None for m in fuera)
        assert cuerpo["fuera"] == len(fuera)
        for m in cuerpo["muestras"]:
            if m["dentro"] and m["cota"] is not None:
                assert m["cota"] == pytest.approx(_valor_de_gdal(dem, m["lon"], m["lat"]), abs=1e-3)


def _pixel_de_tesela(tesela: np.ndarray, z: int, x: int, y: int, columna: int, fila: int):
    """El píxel de la tesela `z/x/y` donde cae el centro de una celda del DEM, con otra ruta de
    cálculo: UTM → EPSG:3857 con `pyproj` y la caja de la cuadrícula escrita aparte."""
    from pyproj import Transformer

    oeste, sur, este, norte = _caja_de_tesela_aparte(z, x, y)
    mx, my = Transformer.from_crs("EPSG:32719", "EPSG:3857", always_xy=True).transform(
        ESTE_NO_M + (columna + 0.5) * PASO_M, NORTE_NO_M - (fila + 0.5) * PASO_M
    )
    px = int((mx - oeste) / (este - oeste) * 256)
    py = int((norte - my) / (norte - sur) * 256)
    assert 0 <= px < 256 and 0 <= py < 256, "la celda no cae en esta tesela"
    return tesela[py, px]


def _tesela_que_contiene(ficha, columna: int, fila: int) -> tuple[int, int, int]:
    from pyproj import Transformer

    mx, my = Transformer.from_crs("EPSG:32719", "EPSG:3857", always_xy=True).transform(
        ESTE_NO_M + (columna + 0.5) * PASO_M, NORTE_NO_M - (fila + 0.5) * PASO_M
    )
    z = ficha.zoom_maximo
    lado = 2 * mercator.ORIGEN_M / 2**z
    return z, int((mx + mercator.ORIGEN_M) // lado), int((mercator.ORIGEN_M - my) // lado)


class TestElSombreado:
    def _nuestra(self, sesion, dem, **parametros):
        ficha = capa.leer(dem)
        z, x, y = _tesela_que_contiene(ficha, 20, 80)
        respuesta = sesion.get(
            reverse("visor:tesela", args=[z, x, y]),
            {"ruta": str(dem), "modo": "sombra", **parametros},
        )
        assert respuesta.status_code == 200, respuesta.content[:200]
        return ficha, (z, x, y), _png_a_matriz(respuesta.content)

    def _independiente(self, dem, tmp, caja, *, az=315, alt=45, zf=1.0):
        """Otro `gdaldem hillshade` y otro `gdalwarp`, con la caja de la fórmula escrita aparte."""
        sombra = tmp / "independiente-sombra.tif"
        hecho = herramienta_externa(
            "gdaldem",
            [
                "hillshade",
                str(dem),
                str(sombra),
                "-az",
                str(az),
                "-alt",
                str(alt),
                "-z",
                repr(zf),
                "-compute_edges",
            ],
        )
        assert hecho.returncode == 0 and sombra.is_file(), hecho.stderr
        destino = tmp / "independiente-tesela.tif"
        corte = herramienta_externa(
            "gdalwarp",
            [
                "-q",
                "-overwrite",
                "-of",
                "GTiff",
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
                str(sombra),
                str(destino),
            ],
        )
        assert corte.returncode == 0 and destino.is_file(), corte.stderr
        return np.asarray(Image.open(destino).convert("RGBA"))

    def test_una_tesela_contra_gdaldem_y_gdalwarp_independientes(self, sesion, dem, tmp_path):
        ficha, (z, x, y), propia = self._nuestra(sesion, dem)
        externa = self._independiente(dem, tmp_path, _caja_de_tesela_aparte(z, x, y))
        mayor, fraccion = _diferencia(propia, externa)
        assert mayor <= 1 and fraccion < 0.01, (mayor, fraccion)

    def test_el_sombreado_entero_de_la_cache_es_celda_a_celda_el_de_otro_gdaldem(
        self, sesion, dem, tmp_path
    ):
        """Lo que atrapó la opción `TILED=YES`: con DEFLATE **y** franjas en mosaico, GDAL 3.12.4
        dejaba 24 celdas distintas junto al hueco de «sin dato»."""
        self._nuestra(sesion, dem)
        (guardado,) = cache.carpeta().rglob("sombra-*.tif")
        aparte = tmp_path / "aparte.tif"
        hecho = herramienta_externa(
            "gdaldem",
            [
                "hillshade",
                str(dem),
                str(aparte),
                "-az",
                "315",
                "-alt",
                "45",
                "-z",
                "1.0",
                "-compute_edges",
            ],
        )
        assert hecho.returncode == 0 and aparte.is_file(), hecho.stderr
        propio, ajeno = np.asarray(Image.open(guardado)), np.asarray(Image.open(aparte))
        assert propio.shape == ajeno.shape == (100, ANCHO_PX)
        assert int((propio != ajeno).sum()) == 0

    def test_otro_sol_contra_el_otro_gdaldem(self, sesion, dem, tmp_path):
        ficha, (z, x, y), propia = self._nuestra(sesion, dem, az="90", alt="25", zf="2,5")
        externa = self._independiente(
            dem, tmp_path, _caja_de_tesela_aparte(z, x, y), az=90, alt=25, zf=2.5
        )
        mayor, fraccion = _diferencia(propia, externa)
        assert mayor <= 1 and fraccion < 0.01, (mayor, fraccion)
        assert _diferencia(propia, self._nuestra(sesion, dem)[2])[0] > 5, "el sol importa"

    def test_sobre_el_plano_vale_lo_que_dice_la_formula_de_horn(self, sesion, dem):
        """Cerca de (20, 80) el terreno es un plano: sube 0,1 m por metro al este y 0,05 al sur,
        así que baja hacia el noroeste. Con el sol al noroeste (315°, 45°) la ladera lo mira."""
        _, (z, x, y), tesela = self._nuestra(sesion, dem)
        pendiente = math.atan(math.hypot(0.2 / PASO_M, 0.1 / PASO_M))
        sentido_de_bajada = math.atan2(-0.2 / PASO_M, 0.1 / PASO_M)  # (este, norte) de bajada
        cenit = math.radians(90 - 45)
        esperado = 255 * (
            math.cos(cenit) * math.cos(pendiente)
            + math.sin(cenit)
            * math.sin(pendiente)
            * math.cos(math.radians(315) - sentido_de_bajada % (2 * math.pi))
        )
        rojo, verde, azul, alfa = _pixel_de_tesela(tesela, z, x, y, 20, 80)
        assert alfa == 255
        assert abs(int(rojo) - esperado) <= 2, (int(rojo), esperado)

    def test_el_hueco_de_sin_dato_sale_transparente(self, sesion, dem):
        ficha = capa.leer(dem)
        z, x, y = _tesela_que_contiene(ficha, 65, 25)
        respuesta = sesion.get(
            reverse("visor:tesela", args=[z, x, y]), {"ruta": str(dem), "modo": "sombra"}
        )
        pixel = _pixel_de_tesela(_png_a_matriz(respuesta.content), z, x, y, 65, 25)
        assert pixel[3] == 0


class TestElColorPorCota:
    def _nuestra(self, sesion, dem):
        ficha = capa.leer(dem)
        z, x, y = _tesela_que_contiene(ficha, 20, 80)
        respuesta = sesion.get(
            reverse("visor:tesela", args=[z, x, y]), {"ruta": str(dem), "modo": "cota"}
        )
        assert respuesta.status_code == 200, respuesta.content[:200]
        return ficha, (z, x, y), _png_a_matriz(respuesta.content)

    def test_contra_un_gdalwarp_y_un_color_relief_independientes(self, sesion, dem, tmp_path):
        ficha, (z, x, y), propia = self._nuestra(sesion, dem)
        minimo, maximo = ficha.escala
        tabla = tmp_path / "colores-aparte.txt"
        tabla.write_text(
            "".join(
                f"{minimo + i * (maximo - minimo) / 5!r} {r} {g} {b} 255\n"
                for i, (r, g, b) in enumerate(VIRIDIS)
            )
            + "nv 0 0 0 0\n",
            encoding="ascii",
        )
        flotante = tmp_path / "flotante.tif"
        corte = herramienta_externa(
            "gdalwarp",
            [
                "-q",
                "-overwrite",
                "-of",
                "GTiff",
                "-t_srs",
                "EPSG:3857",
                "-te",
                *(repr(v) for v in _caja_de_tesela_aparte(z, x, y)),
                "-ts",
                "256",
                "256",
                "-r",
                "bilinear",
                "-ot",
                "Float32",
                "-dstnodata",
                "-99999",
                str(dem),
                str(flotante),
            ],
        )
        assert corte.returncode == 0 and flotante.is_file(), corte.stderr
        salida = tmp_path / "color-aparte.png"
        hecho = herramienta_externa(
            "gdaldem",
            ["color-relief", str(flotante), str(tabla), str(salida), "-alpha", "-of", "PNG"],
        )
        assert hecho.returncode == 0 and salida.is_file(), hecho.stderr
        mayor, fraccion = _diferencia(propia, np.asarray(Image.open(salida).convert("RGBA")))
        assert mayor <= 1 and fraccion < 0.01, (mayor, fraccion)

    def test_una_cota_conocida_tiene_el_color_que_dice_la_interpolacion_lineal(self, sesion, dem):
        """La celda (20, 80) vale 500 + 0,2·20 + 0,1·80 = 512 m. El color es el de esa cota entre
        dos
        paradas de viridis, interpolado a mano."""
        ficha, (z, x, y), tesela = self._nuestra(sesion, dem)
        minimo, maximo = ficha.escala
        fraccion = (512.0 - minimo) / (maximo - minimo) * 5
        i = min(int(fraccion), 4)
        t = fraccion - i
        esperado = [
            round(VIRIDIS[i][k] + t * (VIRIDIS[i + 1][k] - VIRIDIS[i][k])) for k in range(3)
        ]
        rojo, verde, azul, alfa = _pixel_de_tesela(tesela, z, x, y, 20, 80)
        assert alfa == 255
        assert max(abs(int(a) - b) for a, b in zip((rojo, verde, azul), esperado, strict=True)) <= 2

    def test_la_escritura_de_la_leyenda_es_la_rampa_de_la_ficha(self, sesion, dem):
        ficha = sesion.get(reverse("visor:capa"), {"ruta": str(dem)}).json()
        valores = [p[0] for p in ficha["rampa"]]
        minimo, maximo = ficha["escala"]
        assert valores == pytest.approx([minimo + i * (maximo - minimo) / 5 for i in range(6)])
        assert [p[1] for p in ficha["rampa"]] == [list(c) for c in VIRIDIS]


class TestElOriginalYLaCache:
    def test_el_original_no_se_toca_ni_aparece_un_aux_xml(self, sesion, dem):
        antes = _huella(dem)
        carpeta = sorted(p.name for p in dem.parent.iterdir())
        ficha = capa.leer(dem)
        z, x, y = _tesela_que_contiene(ficha, 20, 80)
        for modo in ("gris", "sombra", "cota"):
            assert (
                sesion.get(
                    reverse("visor:tesela", args=[z, x, y]), {"ruta": str(dem), "modo": modo}
                ).status_code
                == 200
            )
        lon, lat = _lonlat_del_centro(20, 80)
        sesion.get(reverse("visor:punto"), {"ruta": str(dem), "lon": lon, "lat": lat, "valor": 1})
        (lon1, lat1), (lon2, lat2) = _lonlat_del_centro(40, 25), _lonlat_del_centro(90, 25)
        sesion.get(
            reverse("visor:perfil"),
            {"ruta": str(dem), "lon1": lon1, "lat1": lat1, "lon2": lon2, "lat2": lat2},
        )
        assert _huella(dem) == antes
        assert sorted(p.name for p in dem.parent.iterdir()) == carpeta, "ningún .aux.xml al lado"

    def test_las_teselas_de_cada_modo_viven_en_la_cache_con_su_clave(self, sesion, dem):
        ficha = capa.leer(dem)
        z, x, y = _tesela_que_contiene(ficha, 20, 80)
        for modo in (
            {"modo": "gris"},
            {"modo": "sombra"},
            {"modo": "sombra", "az": "10"},
            {"modo": "cota"},
        ):
            sesion.get(reverse("visor:tesela", args=[z, x, y]), {"ruta": str(dem), **modo})
        nombres = sorted(p.name for p in cache.carpeta().rglob("*.png"))
        assert len(nombres) == 4 and len(set(nombres)) == 4
        assert sum(1 for p in cache.carpeta().rglob("sombra-*.tif")) == 2, "un sombreado por sol"
        assert all(
            cache.PATRON_PROPIO.match(str(p.relative_to(cache.carpeta())))
            for p in cache.carpeta().rglob("*")
            if p.is_file()
        )

    def test_sin_gdaldem_el_sombreado_se_apaga_pero_la_cota_y_el_perfil_siguen(
        self, sesion, dem, monkeypatch
    ):
        original = motor.ejecutable
        monkeypatch.setattr(motor, "ejecutable", lambda n: None if n == "gdaldem" else original(n))
        ficha = capa.leer(dem)
        z, x, y = _tesela_que_contiene(ficha, 20, 80)
        apagado = sesion.get(
            reverse("visor:tesela", args=[z, x, y]), {"ruta": str(dem), "modo": "sombra"}
        )
        assert apagado.status_code == 503 and apagado.json()["codigo"] == "sin-gdaldem"
        assert apagado.json()["sugerencia"]
        lon, lat = _lonlat_del_centro(20, 80)
        cota = sesion.get(
            reverse("visor:punto"), {"ruta": str(dem), "lon": lon, "lat": lat, "valor": 1}
        ).json()["valores"][0]
        assert cota == pytest.approx(_esperado(20, 80), abs=1e-3)
        (lon1, lat1), (lon2, lat2) = _lonlat_del_centro(40, 25), _lonlat_del_centro(90, 25)
        perfil = sesion.get(
            reverse("visor:perfil"),
            {"ruta": str(dem), "lon1": lon1, "lat1": lat1, "lon2": lon2, "lat2": lat2},
        )
        assert perfil.status_code == 200 and terreno.MUESTRAS_POR_OMISION == len(
            perfil.json()["muestras"]
        )
