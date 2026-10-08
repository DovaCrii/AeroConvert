"""La sincronía de fotos (F18.2).

Las trayectorias son **sintéticas y de fórmula conocida** (una recta recorrida a velocidad
constante; un círculo de radio conocido): la posición esperada de cada foto sale de la fórmula, no
de `sincronizar()`. Lo que se entrega se abre además con `ogrinfo` cuando GDAL está.
"""

from __future__ import annotations

import csv
import io
import json
import math
import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta

import pytest

from apps.documents import vuelo_pos, vuelo_sync
from apps.documents.composicion import ComposicionInvalida

SEMANA = 2390
T0 = SEMANA * 604_800 + 302_400.0  # un instante GPS cualquiera, con semana


def _epoca(t_gps_s, lat, lon, alt, q=1, sd=0.002):
    fecha = datetime(1980, 1, 6) + timedelta(seconds=t_gps_s)
    return vuelo_pos.Epoca(t_gps_s, fecha, lat, lon, alt, q, 12, sd, sd, sd * 2, 0.0, 99.0)


def _recta(n=300, paso=0.2, q=1):
    """Velocidad constante: lat = -33.45 + 1e-5·s, lon = -70.65 + 2e-5·s, h = 500 + 0,5·s."""
    t = vuelo_pos.Trayectoria()
    for i in range(n):
        s = i * paso
        t.epocas.append(_epoca(T0 + s, -33.45 + 1e-5 * s, -70.65 + 2e-5 * s, 500 + 0.5 * s, q=q))
    return t


def _disp(s, numero=1):
    return vuelo_sync.Disparo(numero, T0 + s)


class TestInterpolar:
    def test_en_una_recta_la_posicion_es_exacta_en_cualquier_instante(self):
        tray = _recta()
        instantes = [0.0, 0.05, 0.1, 0.17, 3.333, 12.9, 33.01, 59.79]
        fotos = vuelo_sync.sincronizar(tray, [_disp(s, i) for i, s in enumerate(instantes)])
        for foto, s in zip(fotos, instantes, strict=True):
            assert foto.lat == pytest.approx(-33.45 + 1e-5 * s, abs=1e-10)
            assert foto.lon == pytest.approx(-70.65 + 2e-5 * s, abs=1e-10)
            assert foto.alt_m == pytest.approx(500 + 0.5 * s, abs=1e-6)
            assert foto.motivo == ""

    def test_en_una_curva_el_error_no_pasa_de_la_flecha_del_arco(self):
        # Un círculo de 40 m de radio recorrido a 12 m/s, muestreado a 5 Hz.
        radio_m, v, paso = 40.0, 12.0, 0.2
        grado_m = 111_320.0
        omega = v / radio_m
        tray = vuelo_pos.Trayectoria()
        for i in range(400):
            s = i * paso
            tray.epocas.append(
                _epoca(
                    T0 + s,
                    -33.45 + radio_m * math.sin(omega * s) / grado_m,
                    -70.65
                    + radio_m * math.cos(omega * s) / (grado_m * math.cos(math.radians(33.45))),
                    500,
                )
            )
        flecha_m = radio_m * (1 - math.cos(omega * paso / 2))
        peor_m = 0.0
        for k in range(1, 300):
            s = k * 0.137  # instantes que no caen en una época
            f = vuelo_sync.sincronizar(tray, [_disp(s)])[0]
            real_lat = -33.45 + radio_m * math.sin(omega * s) / grado_m
            real_lon = -70.65 + radio_m * math.cos(omega * s) / (
                grado_m * math.cos(math.radians(33.45))
            )
            dn = (f.lat - real_lat) * grado_m
            de = (f.lon - real_lon) * grado_m * math.cos(math.radians(33.45))
            peor_m = max(peor_m, math.hypot(dn, de))
        assert 0 < peor_m <= flecha_m * 1.001, (peor_m, flecha_m)

    def test_un_disparo_justo_en_una_epoca_toma_esa_epoca(self):
        tray = _recta()
        f = vuelo_sync.sincronizar(tray, [_disp(10.0)])[0]
        assert f.lat == tray.epocas[50].lat and f.q == 1

    def test_el_orden_de_los_disparos_no_importa(self):
        tray = _recta()
        a = vuelo_sync.sincronizar(tray, [_disp(40.0), _disp(5.5), _disp(22.2)])
        for foto, s in zip(a, [40.0, 5.5, 22.2], strict=True):
            assert foto.lat == pytest.approx(-33.45 + 1e-5 * s, abs=1e-12)


class TestNoExtrapola:
    def test_antes_y_despues_de_la_trayectoria_no_hay_posicion(self):
        tray = _recta(n=100)  # de 0 a 19,8 s
        antes, despues, dentro = vuelo_sync.sincronizar(
            tray, [_disp(-0.5), _disp(25.0), _disp(10.0)]
        )
        assert not antes.con_posicion and "antes del primer punto" in antes.motivo
        assert not despues.con_posicion and "después del último punto" in despues.motivo
        assert dentro.con_posicion

    def test_los_extremos_exactos_si_tienen_posicion(self):
        tray = _recta(n=100)
        primero, ultimo = vuelo_sync.sincronizar(tray, [_disp(0.0), _disp(19.8)])
        assert primero.con_posicion and ultimo.con_posicion

    def test_dentro_de_un_hueco_largo_no_hay_posicion(self):
        tray = _recta(n=200)
        tray.epocas = tray.epocas[:50] + tray.epocas[90:]  # 8 s sin puntos (0,2 s es lo típico)
        enmedio = vuelo_sync.sincronizar(tray, [_disp(10.5)])[0]
        assert not enmedio.con_posicion
        assert "en un hueco" in enmedio.motivo and "8.2" in enmedio.motivo
        # Y a los lados del hueco, con puntos vecinos, sí.
        lados = vuelo_sync.sincronizar(tray, [_disp(5.0), _disp(25.0)])
        assert all(f.con_posicion for f in lados)

    def test_un_hueco_corto_se_interpola(self):
        tray = _recta(n=100)
        tray.epocas = tray.epocas[:20] + tray.epocas[22:]  # falta un punto: 0,6 s entre vecinos
        assert vuelo_sync.sincronizar(tray, [_disp(4.3)])[0].con_posicion


class TestCalidad:
    def _mixta(self, q1, q2):
        tray = vuelo_pos.Trayectoria()
        tray.epocas = [
            _epoca(T0, -33.0, -70.0, 500, q=q1, sd=0.002),
            _epoca(T0 + 1.0, -33.0001, -70.0001, 501, q=q2, sd=0.05),
        ]
        return tray

    @pytest.mark.parametrize(
        "q1,q2,esperada",
        [(1, 1, 1), (1, 2, 2), (2, 1, 2), (1, 5, 5), (2, 5, 5), (2, 2, 2), (1, 4, 4)],
    )
    def test_la_foto_toma_la_peor_calidad_de_sus_dos_vecinos(self, q1, q2, esperada):
        assert vuelo_sync.sincronizar(self._mixta(q1, q2), [_disp(0.5)])[0].q == esperada

    def test_la_incertidumbre_es_la_mayor_de_las_dos_no_el_promedio(self):
        f = vuelo_sync.sincronizar(self._mixta(1, 1), [_disp(0.5)])[0]
        assert f.sdn_m == 0.05 and f.sde_m == 0.05 and f.sdu_m == 0.1


class TestDisparos:
    MRK = (
        "1\t302410.523456\t[2390]\t-24,N\t-8,E\t30,V\t-33.45678912,Lat\t-70.65432109,Lon\t"
        "520.123,Ellh\t0.9, 0.8, 1.7\n"
        "2\t302412.523456\t[2390]\t-24,N\t-8,E\t30,V\t-33.45678900,Lat\t-70.65432100,Lon\t"
        "520.125,Ellh\t0.9, 0.8, 1.7\n"
    )

    def test_el_mrk_da_el_instante_gps_y_el_desfase_de_la_antena(self):
        d = vuelo_sync.leer_mrk(self.MRK)
        assert [x.numero for x in d] == [1, 2]
        assert d[0].t_gps_s == 2390 * 604_800 + 302_410.523456
        assert (d[0].desfase_n_mm, d[0].desfase_e_mm, d[0].desfase_v_mm) == (-24.0, -8.0, 30.0)

    def test_un_mrk_roto_se_rechaza_con_su_linea(self):
        with pytest.raises(ComposicionInvalida, match="línea 2"):
            vuelo_sync.leer_mrk(self.MRK.splitlines()[0] + "\nesto no es un disparo\n")
        with pytest.raises(ComposicionInvalida, match="ningún disparo"):
            vuelo_sync.leer_mrk("\n\n")

    def test_la_lista_de_tiempos_en_calendario_y_en_semana_segundo(self):
        a = vuelo_sync.leer_lista_de_tiempos(
            "# cabecera\n1980/01/13 00:00:00.500\n2390 302410.25\n"
        )
        assert a[0].t_gps_s == 604_800.5
        assert a[1].t_gps_s == 2390 * 604_800 + 302_410.25
        assert [x.numero for x in a] == [1, 2]

    def test_una_linea_que_no_es_un_tiempo_se_rechaza(self):
        with pytest.raises(ComposicionInvalida, match="línea 2"):
            vuelo_sync.leer_lista_de_tiempos("2390 302410.25\nayer a las tres\n")

    def test_emparejar_exige_tantas_fotos_como_disparos(self):
        d = vuelo_sync.leer_mrk(self.MRK)
        assert vuelo_sync.emparejar(d, ["a.jpg", "b.jpg"]) == ["a.jpg", "b.jpg"]
        with pytest.raises(ComposicionInvalida, match="2 disparos y 3 fotos"):
            vuelo_sync.emparejar(d, ["a.jpg", "b.jpg", "c.jpg"])
        with pytest.raises(ComposicionInvalida, match="cada foto saldría con la posición de otra"):
            vuelo_sync.sincronizar(_recta(), d, nombres=["a.jpg"])


class TestEntregables:
    def _fotos(self):
        tray = _recta(n=100)
        disparos = [_disp(2.0, 1), _disp(8.5, 2), _disp(50.0, 3)]  # el 3 cae fuera
        return vuelo_sync.sincronizar(tray, disparos, ["f1.jpg", "f2.jpg", "f3.jpg"])

    def test_el_csv_lleva_todas_las_fotos_y_el_motivo_de_las_que_no_tienen(self):
        filas = list(csv.DictReader(io.StringIO(vuelo_sync.a_csv(self._fotos()))))
        assert [f["foto"] for f in filas] == ["f1.jpg", "f2.jpg", "f3.jpg"]
        assert float(filas[0]["lat"]) == pytest.approx(-33.45 + 1e-5 * 2.0, abs=1e-9)
        assert filas[0]["calidad"] == "fija"
        assert filas[2]["lat"] == "" and "después del último" in filas[2]["motivo"]
        assert "alt_elipsoidal_m" in filas[0]

    def test_el_desfase_de_la_antena_va_tal_cual_y_no_se_suma(self):
        tray = _recta()
        d = vuelo_sync.Disparo(1, T0 + 2.0, -24.0, -8.0, 30.0)
        f = vuelo_sync.sincronizar(tray, [d])[0]
        fila = next(csv.DictReader(io.StringIO(vuelo_sync.a_csv([f]))))
        assert (fila["desfase_antena_n_mm"], fila["desfase_antena_e_mm"]) == ("-24.0", "-8.0")
        assert f.lat == pytest.approx(-33.45 + 1e-5 * 2.0, abs=1e-12), "la posición no se movió"

    def test_el_geojson_lleva_solo_las_que_tienen_posicion_y_dice_el_sistema(self):
        datos = json.loads(vuelo_sync.a_geojson(self._fotos(), "SIRGAS-Chile"))
        assert datos["sistema"] == "SIRGAS-Chile" and len(datos["features"]) == 2
        lon, lat, alt = datos["features"][0]["geometry"]["coordinates"]
        assert lat == pytest.approx(-33.45 + 1e-5 * 2.0, abs=1e-9) and alt > 500

    def test_el_kml_solo_sale_en_un_sistema_que_es_wgs84(self):
        assert "<Placemark>" in vuelo_sync.a_kml(self._fotos(), "SIRGAS-Chile")
        assert "<Placemark>" in vuelo_sync.a_kml(self._fotos(), "WGS84")
        with pytest.raises(ComposicionInvalida, match="PSAD56"):
            vuelo_sync.a_kml(self._fotos(), "PSAD56")

    def test_el_kml_sin_ninguna_posicion_se_rechaza(self):
        solo_fuera = vuelo_sync.sincronizar(_recta(n=10), [_disp(500.0)])
        with pytest.raises(ComposicionInvalida, match="Ninguna foto tiene posición"):
            vuelo_sync.a_kml(solo_fuera, "WGS84")

    def test_el_resumen_cuenta_calidades_y_motivos(self):
        r = vuelo_sync.resumen(self._fotos())
        assert r["fotos"] == 3 and r["con_posicion"] == 2 and r["sin_posicion"] == 1
        assert r["por_calidad"] == {"fija": 2} and len(r["motivos"]) == 1

    @pytest.mark.oraculo
    @pytest.mark.skipif(not shutil.which("ogrinfo"), reason="sin ogrinfo")
    def test_ogrinfo_abre_el_geojson_y_el_kmz_y_cuenta_las_fotos(self, tmp_path):
        fotos = self._fotos()
        (tmp_path / "f.geojson").write_text(vuelo_sync.a_geojson(fotos, "WGS84"), encoding="utf-8")
        with zipfile.ZipFile(tmp_path / "f.kmz", "w") as z:
            z.writestr("doc.kml", vuelo_sync.a_kml(fotos, "WGS84"))
        for nombre in ("f.geojson", "f.kmz"):
            salida = subprocess.run(  # noqa: S603 - argumentos fijos
                ["ogrinfo", "-so", "-al", str(tmp_path / nombre)],  # noqa: S607
                capture_output=True, text=True, timeout=60,
            )  # fmt: skip
            assert "Feature Count: 2" in salida.stdout, nombre
