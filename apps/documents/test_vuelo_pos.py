"""El lector del `.pos` de RTKLIB (F18.1).

Los `.pos` se **escriben desde valores conocidos** (como los dejaría `rnx2rtkp`); lo leído se
compara con esos valores y, aparte, con **numpy**, que los lee sin pasar por `vuelo_pos`.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta

import numpy as np
import pytest

from apps.documents import vuelo_pos
from apps.documents.composicion import ComposicionInvalida

CABECERA = """\
% program   : RTKPOST ver.2.4.3
% inp file  : rover.obs
% obs start : 2026/10/08 12:00:00.0 GPST (week2390 302400.0s)
% ref pos   : -33.456789012  -70.654321098    520.1230
%
%  GPST                  latitude(deg) longitude(deg)  height(m)   Q  ns   sdn(m)   sde(m)  \
sdu(m)  sdne(m)  sdeu(m)  sdun(m) age(s)  ratio
"""


def _linea(i: int, *, q=1, ns=14, t0=datetime(2026, 10, 8, 12, 0, 0), paso=0.2) -> str:
    t = t0 + timedelta(seconds=i * paso)
    lat = -33.45 - i * 1e-6
    lon = -70.65 + i * 2e-6
    alt = 520.0 + i * 0.01
    return (
        f"{t:%Y/%m/%d %H:%M:%S}.{t.microsecond // 1000:03d} {lat:14.9f} {lon:14.9f} {alt:10.4f} "
        f"{q:3d} {ns:3d} 0.0021 0.0018 0.0045 0.0001 0.0002 0.0003 0.00 {1.5 + i / 100:6.1f}"
    )


def _pos(calidades: list[int], *, saltar: set[int] = frozenset()) -> str:
    return (
        CABECERA
        + "\n".join(_linea(i, q=q) for i, q in enumerate(calidades) if i not in saltar)
        + "\n"
    )


class TestLeer:
    def test_los_valores_leidos_son_los_escritos(self):
        t = vuelo_pos.leer(_pos([1, 1, 2, 5, 1]))
        assert t.n == 5
        e = t.epocas[2]
        assert e.lat == pytest.approx(-33.45 - 2e-6, abs=1e-9)
        assert e.lon == pytest.approx(-70.65 + 4e-6, abs=1e-9)
        assert e.alt_m == pytest.approx(520.02, abs=1e-6)
        assert (e.q, e.ns, e.calidad) == (2, 14, "flotante")
        assert (e.sdn_m, e.sde_m, e.sdu_m) == (0.0021, 0.0018, 0.0045)

    def test_otro_lector_numpy_coincide_en_todo(self):
        texto = _pos([1, 1, 2, 5, 1, 1, 2])
        crudo = np.loadtxt(io.StringIO(texto), comments="%", dtype=str)
        t = vuelo_pos.leer(texto)
        assert crudo.shape[0] == t.n
        assert [int(x) for x in crudo[:, 5]] == [e.q for e in t.epocas]
        np.testing.assert_allclose(crudo[:, 2].astype(float), [e.lat for e in t.epocas])
        np.testing.assert_allclose(crudo[:, 3].astype(float), [e.lon for e in t.epocas])
        np.testing.assert_allclose(crudo[:, 4].astype(float), [e.alt_m for e in t.epocas])

    def test_el_tiempo_gps_se_mide_desde_el_6_de_enero_de_1980(self):
        un_lunes = "1980/01/13 00:00:00.000"  # exactamente una semana GPS después del origen
        linea = _linea(0).replace(_linea(0)[:23], un_lunes)
        t = vuelo_pos.leer(CABECERA + linea + "\n")
        assert t.epocas[0].t_gps_s == 604_800.0
        origen = _linea(0).replace(_linea(0)[:23], "1980/01/06 00:00:00.000")
        assert vuelo_pos.leer(CABECERA + origen + "\n").epocas[0].t_gps_s == 0.0

    def test_los_decimales_del_segundo_se_conservan(self):
        t = vuelo_pos.leer(_pos([1, 1, 1]))
        pasos = [b.t_gps_s - a.t_gps_s for a, b in zip(t.epocas, t.epocas[1:], strict=False)]
        assert pasos == pytest.approx([0.2, 0.2], abs=1e-6)
        assert t.intervalo_tipico_s == pytest.approx(0.2, abs=1e-6)


class TestCalidad:
    def test_cuenta_por_calidad_y_porcentajes(self):
        t = vuelo_pos.leer(_pos([1] * 6 + [2] * 3 + [5]))
        assert t.por_calidad() == {"fija": 6, "flotante": 3, "simple": 1}
        assert t.porcentaje(1) == pytest.approx(60.0)
        assert t.porcentaje(2) == pytest.approx(30.0)
        assert t.porcentaje(5) == pytest.approx(10.0)

    def test_un_codigo_que_no_se_conoce_se_nombra_asi(self):
        assert vuelo_pos.leer(_pos([9])).epocas[0].calidad == "código 9"

    def test_los_huecos_salen_con_su_duracion(self):
        # Se quitan 20 épocas seguidas de 0,2 s: un hueco de 4,2 s.
        t = vuelo_pos.leer(_pos([1] * 60, saltar=set(range(20, 40))))
        (hueco,) = t.huecos()
        assert hueco.duracion_s == pytest.approx(4.2, abs=1e-6)

    def test_sin_huecos_no_inventa_ninguno(self):
        assert vuelo_pos.leer(_pos([1] * 30)).huecos() == []

    def test_una_sola_posicion_no_tiene_intervalo_ni_huecos(self):
        t = vuelo_pos.leer(_pos([1]))
        assert t.intervalo_tipico_s == 0.0 and t.huecos() == []


class TestLoQueNoEsUnPos:
    def test_las_lineas_rotas_se_cuentan_con_su_numero_y_no_tumban_la_lectura(self):
        texto = _pos([1, 1, 1]) + "esto no es una posicion\n" + _linea(3) + "\n"
        texto += "2026/10/08 12:00:09.999 abc def ghi 1 5 0 0 0 0 0 0 0 0\n"
        t = vuelo_pos.leer(texto)
        assert t.n == 4 and len(t.ilegibles) == 2
        primera = t.ilegibles[0]
        assert texto.splitlines()[primera - 1] == "esto no es una posicion"

    def test_una_latitud_imposible_se_cuenta_como_ilegible(self):
        malo = _linea(0).replace("-33.450000000", "-93.450000000")
        t = vuelo_pos.leer(CABECERA + malo + "\n" + _linea(1) + "\n")
        assert t.n == 1 and len(t.ilegibles) == 1

    def test_sin_posiciones_no_es_un_pos(self):
        with pytest.raises(ComposicionInvalida, match="ninguna posición legible"):
            vuelo_pos.leer(CABECERA)
        with pytest.raises(ComposicionInvalida, match="no parece un .pos"):
            vuelo_pos.leer("hola\nmundo\n")
        with pytest.raises(ComposicionInvalida):
            vuelo_pos.leer("")

    def test_posiciones_en_ecef_no_se_convierten_a_ojo(self):
        texto = CABECERA.replace("latitude(deg) longitude(deg)", "x-ecef(m)  y-ecef(m)")
        with pytest.raises(ComposicionInvalida, match="ECEF"):
            vuelo_pos.leer(texto + _linea(0) + "\n")

    def test_otra_escala_de_tiempo_se_rechaza_diciendo_cual(self):
        texto = CABECERA.replace("%  GPST ", "%  UTC  ")
        with pytest.raises(ComposicionInvalida, match="UTC"):
            vuelo_pos.leer(texto + _linea(0) + "\n")


class TestInforme:
    def test_todo_fijo_lo_dice(self):
        texto = vuelo_pos.a_markdown(vuelo_pos.leer(_pos([1] * 50)), "vuelo.pos")
        assert "Fija: 100.0 %" in texto and "ambigüedad resuelta" in texto
        assert "Sin huecos" in texto

    def test_poco_fijo_avisa_y_no_aprueba(self):
        texto = vuelo_pos.a_markdown(vuelo_pos.leer(_pos([1] * 4 + [2] * 6)), "v.pos")
        assert "Solo el 40.0 %" in texto and "ambigüedad resuelta" not in texto

    def test_nada_fijo_lo_dice_sin_rodeos(self):
        texto = vuelo_pos.a_markdown(vuelo_pos.leer(_pos([5] * 10)), "v.pos")
        assert "Ninguna posición es fija" in texto

    def test_los_huecos_y_las_lineas_rotas_salen(self):
        t = vuelo_pos.leer(_pos([1] * 60, saltar=set(range(20, 40))) + "basura\n")
        texto = vuelo_pos.a_markdown(t, "v.pos")
        assert "**1** hueco" in texto and "4.2 s" in texto
        assert "Líneas que no se entendieron:** 1" in texto
