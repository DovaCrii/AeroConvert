"""Buscar un sistema de referencia sin saber su EPSG.

El oráculo es la base de PROJ, **leída por otra vía**: `pyproj.CRS.from_epsg` abre cada código
devuelto y su nombre tiene que ser el que la búsqueda enseña. Y la regla 3: nada se ofrece con
la caja vacía y el orden no depende de cuál «es el más probable».
"""

from __future__ import annotations

import pytest
from pyproj import CRS

from apps.formats import crs_busqueda


def _codigos(texto: str) -> list[int]:
    return [r.codigo for r in crs_busqueda.buscar(texto)]


class TestLaBusqueda:
    @pytest.mark.parametrize(
        ("escrito", "esperado"),
        [
            ("sirgas chile", 5361),
            ("chile utm 19 sur", 5361),
            ("psad56 utm 19s", 24879),
            ("wgs84 utm zona 19 sur", 32719),
            ("EPSG:32719", 32719),
            ("32719", 32719),
        ],
    )
    def test_encuentra_lo_que_se_dice_como_se_dice(self, escrito, esperado):
        assert esperado in _codigos(escrito)

    def test_cada_resultado_es_un_sistema_que_proj_abre_con_ese_nombre(self):
        for r in crs_busqueda.buscar("sirgas chile"):
            assert CRS.from_epsg(r.codigo).name == r.nombre

    def test_utm_sur_no_trae_los_del_norte(self):
        for r in crs_busqueda.buscar("wgs 84 utm 19 sur"):
            assert r.nombre.endswith("19S") or "19S" in r.nombre

    def test_con_la_caja_vacia_o_casi_no_ofrece_nada(self):
        assert crs_busqueda.buscar("") == []
        assert crs_busqueda.buscar("u") == []
        assert crs_busqueda.buscar(None) == []

    def test_un_codigo_exacto_va_primero(self):
        assert _codigos("4326")[0] == 4326

    def test_no_hay_sistemas_obsoletos_ni_mas_del_limite(self):
        resultados = crs_busqueda.buscar("utm")
        assert len(resultados) <= crs_busqueda.LIMITE
        assert all(not CRS.from_epsg(r.codigo).to_json_dict().get("deprecated") for r in resultados)

    def test_el_area_no_desborda_una_fila(self):
        for r in crs_busqueda.buscar("wgs 84"):
            assert len(r.area) <= crs_busqueda.AREA_MAX

    def test_lo_que_no_existe_da_lista_vacia(self):
        assert crs_busqueda.buscar("zzzz inexistente") == []
