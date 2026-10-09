"""La cuadrícula de teselas XYZ de EPSG:3857, contra valores publicados y fórmulas escritas aparte.

Ninguna comparación aquí es «el código contra el código»: los números de arriba son los de la
especificación de Web Mercator (EPSG:3857) y de la convención de teselas XYZ, y las fórmulas de
abajo están escritas **otra vez, de otra manera** (con `asinh` y con `n = 2**z`), de modo que un
error de signo o de eje en `mercator.py` no pueda repetirse en la prueba.
"""

from __future__ import annotations

import math

import pytest

from apps.visor import mercator

#: Medio lado del mundo en EPSG:3857, tal como lo publica la especificación.
MEDIO_MUNDO_M = 20037508.34

#: Metros por píxel del nivel 0 (EPSG:3857 con teselas de 256 px): 156 543,03 m.
RESOLUCION_NIVEL_0 = 156543.03


class TestLaCajaDeLaTesela:
    def test_la_tesela_0_0_0_cubre_todo_el_mundo(self):
        x0, y0, x1, y1 = mercator.caja_de_tesela(0, 0, 0)
        assert x0 == pytest.approx(-MEDIO_MUNDO_M, abs=0.01)
        assert y0 == pytest.approx(-MEDIO_MUNDO_M, abs=0.01)
        assert x1 == pytest.approx(MEDIO_MUNDO_M, abs=0.01)
        assert y1 == pytest.approx(MEDIO_MUNDO_M, abs=0.01)

    def test_en_el_nivel_1_la_0_0_es_el_cuadrante_noroeste(self):
        """`y` crece hacia el sur: la tesela 1/0/0 es la de arriba a la izquierda."""
        x0, y0, x1, y1 = mercator.caja_de_tesela(1, 0, 0)
        assert (round(x0), round(y0)) == (round(-MEDIO_MUNDO_M), 0)
        assert (round(x1), round(y1)) == (0, round(MEDIO_MUNDO_M))

    def test_en_el_nivel_1_la_1_1_es_el_cuadrante_sureste(self):
        x0, y0, x1, y1 = mercator.caja_de_tesela(1, 1, 1)
        assert (round(x0), round(y0)) == (0, round(-MEDIO_MUNDO_M))
        assert (round(x1), round(y1)) == (round(MEDIO_MUNDO_M), 0)

    def test_dos_teselas_vecinas_comparten_borde(self):
        a = mercator.caja_de_tesela(5, 10, 12)
        b = mercator.caja_de_tesela(5, 11, 12)
        c = mercator.caja_de_tesela(5, 10, 13)
        assert a[2] == pytest.approx(b[0])
        assert a[1] == pytest.approx(c[3])

    @pytest.mark.parametrize("z", range(0, 25, 4))
    def test_el_lado_de_una_tesela_es_el_mundo_entre_dos_a_la_z(self, z):
        x0, y0, x1, y1 = mercator.caja_de_tesela(z, 0, 0)
        esperado = 2 * MEDIO_MUNDO_M / 2**z
        assert x1 - x0 == pytest.approx(esperado, rel=1e-9)
        assert y1 - y0 == pytest.approx(esperado, rel=1e-9)

    def test_la_resolucion_del_nivel_0_es_la_publicada(self):
        assert mercator.resolucion_m(0) == pytest.approx(RESOLUCION_NIVEL_0, abs=0.01)
        assert mercator.resolucion_m(1) == pytest.approx(RESOLUCION_NIVEL_0 / 2, abs=0.01)


class TestQueTeselaExiste:
    @pytest.mark.parametrize(
        ("z", "x", "y"),
        [(-1, 0, 0), (25, 0, 0), (0, 1, 0), (0, 0, 1), (3, 8, 0), (3, 0, 8), (3, -1, 0)],
    )
    def test_fuera_de_la_cuadricula_no_existe(self, z, x, y):
        assert not mercator.es_valida(z, x, y)
        with pytest.raises(ValueError, match="No existe"):
            mercator.caja_de_tesela(z, x, y)

    @pytest.mark.parametrize(("z", "x", "y"), [(0, 0, 0), (3, 7, 7), (24, 2**24 - 1, 0)])
    def test_dentro_si(self, z, x, y):
        assert mercator.es_valida(z, x, y)


class TestLonLatYMetros:
    def test_el_origen_es_el_origen(self):
        x, y = mercator.lonlat_a_mercator(0, 0)
        assert (x, y) == (0.0, pytest.approx(0.0, abs=1e-6))

    def test_180_grados_de_longitud_son_medio_mundo(self):
        x, _ = mercator.lonlat_a_mercator(180, 0)
        assert x == pytest.approx(MEDIO_MUNDO_M, abs=0.01)

    def test_la_latitud_maxima_llega_al_borde_del_cuadrado(self):
        """A ±85,0511° Web Mercator se hace cuadrada: `y` vale lo mismo que `x` en 180°."""
        _, y = mercator.lonlat_a_mercator(0, mercator.LATITUD_MAXIMA)
        assert y == pytest.approx(MEDIO_MUNDO_M, abs=0.05)

    def test_santiago_de_chile(self):
        """Valor de PROJ (`cs2cs EPSG:4326 EPSG:3857`): otro código que el de `mercator.py`."""
        x, y = mercator.lonlat_a_mercator(-70.6693, -33.4489)
        assert x == pytest.approx(-7866870.49, abs=0.01)
        assert y == pytest.approx(-3955040.64, abs=0.01)

    @pytest.mark.parametrize(
        ("lon", "lat"), [(-70.6693, -33.4489), (12.5, 41.9), (179.9, -60.0), (0.0001, 0.0001)]
    )
    def test_ida_y_vuelta(self, lon, lat):
        x, y = mercator.lonlat_a_mercator(lon, lat)
        lon2, lat2 = mercator.mercator_a_lonlat(x, y)
        assert lon2 == pytest.approx(lon, abs=1e-9)
        assert lat2 == pytest.approx(lat, abs=1e-9)

    @pytest.mark.parametrize("lat", [85.06, -85.06, 90, -90])
    def test_donde_la_proyeccion_no_llega_se_niega(self, lat):
        with pytest.raises(ValueError, match="no llega"):
            mercator.lonlat_a_mercator(0, lat)


class TestLaTeselaDeUnPunto:
    @pytest.mark.parametrize(
        ("lon", "lat", "z"),
        [(-70.6693, -33.4489, 10), (0.0, 0.0, 1), (139.69, 35.69, 7), (-0.1278, 51.5074, 12)],
    )
    def test_contra_la_formula_de_los_mapas_en_la_web(self, lon, lat, z):
        """La fórmula de siempre del «slippy map», con `asinh`: otra ruta que `mercator.py`."""
        n = 2**z
        esperado_x = int((lon + 180.0) / 360.0 * n)
        esperado_y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
        assert mercator.tesela_de_lonlat(lon, lat, z) == (esperado_x, esperado_y)

    def test_el_punto_cae_dentro_de_la_caja_de_su_tesela(self):
        lon, lat = -70.6693, -33.4489
        x, y = mercator.lonlat_a_mercator(lon, lat)
        for z in (3, 9, 15, 20):
            tx, ty = mercator.tesela_de_lonlat(lon, lat, z)
            x0, y0, x1, y1 = mercator.caja_de_tesela(z, tx, ty)
            assert x0 <= x <= x1
            assert y0 <= y <= y1

    def test_el_nivel_1_separa_los_cuatro_cuadrantes(self):
        assert mercator.tesela_de_lonlat(-90, 45, 1) == (0, 0)  # noroeste
        assert mercator.tesela_de_lonlat(90, 45, 1) == (1, 0)  # noreste
        assert mercator.tesela_de_lonlat(-90, -45, 1) == (0, 1)  # suroeste
        assert mercator.tesela_de_lonlat(90, -45, 1) == (1, 1)  # sureste


class TestSeCruzan:
    def test_cajas_que_comparten_area(self):
        assert mercator.se_cruzan((0, 0, 10, 10), (5, 5, 15, 15))
        assert mercator.se_cruzan((0, 0, 10, 10), (2, 2, 3, 3))

    def test_cajas_separadas_o_que_solo_se_tocan_no(self):
        assert not mercator.se_cruzan((0, 0, 10, 10), (20, 0, 30, 10))
        assert not mercator.se_cruzan((0, 0, 10, 10), (10, 0, 20, 10))  # solo el borde
        assert not mercator.se_cruzan((0, 0, 10, 10), (0, 10, 10, 20))
