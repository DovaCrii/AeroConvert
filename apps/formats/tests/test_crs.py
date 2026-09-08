"""El sistema de referencia: no se adivina, y cuando se acepta uno se dice de donde vino."""

import pytest

from apps.formats import crs as crs_mod

from .constructor import PRJ_METASHAPE


class TestValidarDeclarado:
    def test_acepta_un_epsg_a_secas(self):
        resultado = crs_mod.validar_declarado("32719")
        assert (resultado.autoridad, resultado.codigo) == ("EPSG", "32719")
        assert resultado.nombre == "WGS 84 / UTM zone 19S"

    def test_acepta_el_prefijo_epsg(self):
        assert crs_mod.validar_declarado("EPSG:32719").codigo == "32719"

    def test_lo_declarado_queda_marcado_como_declarado(self):
        """Que lo tecleara una persona no es un detalle: es lo que permite reconstruir el
        dia en que alguien puso la obra en otro pais."""
        resultado = crs_mod.validar_declarado("32719")
        assert resultado.origen == crs_mod.DECLARADO
        assert resultado.es_declarado is True

    def test_vacio_da_crs_ausente_y_no_un_valor_por_omision(self):
        with pytest.raises(crs_mod.CrsInvalido) as fallo:
            crs_mod.validar_declarado("   ")
        assert fallo.value.codigo == "crs-ausente"

    def test_texto_que_no_es_un_numero_se_rechaza(self):
        with pytest.raises(crs_mod.CrsInvalido) as fallo:
            crs_mod.validar_declarado("UTM 19 sur")
        assert fallo.value.codigo == "crs-invalido"

    def test_un_epsg_inexistente_se_rechaza(self):
        with pytest.raises(crs_mod.CrsInvalido) as fallo:
            crs_mod.validar_declarado("999999")
        assert fallo.value.codigo == "crs-invalido"


class TestPrjDeMetashape:
    """El caso que obligo a la tercera pasada de `desde_wkt`.

    pyproj no identifica este WKT ni con confianza 20 -- devuelve cero candidatos -- porque
    lleva un TOWGS84 de ceros y llama al datum «World Geodetic System 1984 ensemble». Y sin
    embargo el archivo termina en AUTHORITY["EPSG","32719"].
    """

    def test_se_resuelve_a_32719(self):
        resultado = crs_mod.desde_wkt(PRJ_METASHAPE)
        assert (resultado.autoridad, resultado.codigo) == ("EPSG", "32719")

    def test_pyproj_por_si_solo_no_lo_resuelve(self):
        """Si algun dia pyproj empieza a resolverlo, esta prueba avisa y la tercera pasada
        se puede quitar. Documenta por que existe el codigo, no solo que existe."""
        pyproj = pytest.importorskip("pyproj")
        assert pyproj.CRS.from_wkt(PRJ_METASHAPE).to_authority(min_confidence=20) is None

    def test_queda_marcado_como_venido_del_prj(self):
        assert crs_mod.desde_wkt(PRJ_METASHAPE).origen == crs_mod.SIDECAR_PRJ


class TestAutoridadDeclaradaSeVerifica:
    """Leer el EPSG que el archivo declara es util. Creerselo sin comprobar seria adivinar."""

    def test_un_epsg_declarado_que_no_cuadra_se_descarta(self):
        # El mismo WKT de UTM 19S, pero diciendo que es EPSG:4326 (grados).
        mentiroso = PRJ_METASHAPE.replace('AUTHORITY["EPSG","32719"]]', 'AUTHORITY["EPSG","4326"]]')
        resultado = crs_mod.desde_wkt(mentiroso)
        assert resultado.codigo != "4326"
        assert resultado.conocido is False
        # El WKT no se pierde aunque no se pueda nombrar.
        assert resultado.wkt == mentiroso

    def test_un_wkt_vacio_da_sin_crs(self):
        assert crs_mod.desde_wkt("") is crs_mod.SIN_CRS


class TestPuntoConCrs:
    def test_lleva_su_sistema_pegado(self):
        punto = crs_mod.PuntoConCrs(495279.406, 7318729.036, crs_mod.epsg(32719), z_m=3042.641)
        assert "EPSG:32719" in str(punto)
        assert punto.crs.codigo == "32719"


class TestSinCrs:
    def test_el_desconocido_no_es_none(self):
        """Se usa un objeto y no `None` para que quien lo consume pregunte una sola cosa."""
        assert crs_mod.SIN_CRS.conocido is False
        assert str(crs_mod.SIN_CRS) == ":"
