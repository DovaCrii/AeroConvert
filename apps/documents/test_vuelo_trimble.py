"""Lo que entrega Trimble Business Center de un vuelo, y el sistema de sus coordenadas (F18.6).

Aquí se prueba con archivos pequeños escritos a mano. La prueba con un vuelo real, de 2 505
fotos, es `test_vuelo_real.py`, y corre solo donde están los datos (que no van en el repo).
"""

from __future__ import annotations

import math

import pytest
from pyproj import Transformer

from apps.documents import vuelo_sync, vuelo_trimble
from apps.documents.composicion import ComposicionInvalida

TRAYECTORIA = (
    "C1-0,414782.387,7418966.067,1039.022,,2025-12-29 15:38:13.0000000\n"
    "C1-1,414782.392,7418966.073,1039.006,,2025-12-29 15:38:13.2000000\n"
    "C1-2,414782.413,7418966.102,1039.019,,2025-12-29 15:38:13.4000000\n"
)

EXTENDIDO = (
    "ID,Este,Norte,Elevación,Fecha,Modelo,Calidad,Latitud,Longitud,Altura\n"
    "DJI_0001_V.JPG,414891.733,7418747.281,1122.911,2025:12:29 12:38:52,DJI M3E,PPK,"
    "-23.338638421,-69.832545359,1122.911\n"
    "DJI_0002_V.JPG,414888.983,7418761.796,1123.051,2025:12:29 12:38:53,DJI M3E,PPK,"
    "-23.338507172,-69.832571438,1123.051\n"
)


class TestTrayectoria:
    def test_lee_nombre_este_norte_altura_y_hora_gps(self):
        p = vuelo_trimble.leer_trayectoria(TRAYECTORIA.encode())
        assert [x.nombre for x in p] == ["C1-0", "C1-1", "C1-2"]
        assert (p[0].este, p[0].norte, p[0].altura) == (414782.387, 7418966.067, 1039.022)
        assert p[1].t_gps_s - p[0].t_gps_s == pytest.approx(0.2, abs=1e-6)
        # 2025-12-29 15:38:13 GPST: 1980-01-06 → 2025-12-29 son 16 794 días y 15 h 38 min 13 s.
        assert p[0].t_gps_s == 16_794 * 86_400 + 15 * 3600 + 38 * 60 + 13

    def test_en_utc_se_suman_los_18_segundos(self):
        gps = vuelo_trimble.leer_trayectoria(TRAYECTORIA.encode())[0].t_gps_s
        utc = vuelo_trimble.leer_trayectoria(TRAYECTORIA.encode(), escala_de_tiempo="UTC")[0]
        assert utc.t_gps_s == gps + 18

    def test_una_escala_que_no_existe_se_rechaza(self):
        with pytest.raises(ComposicionInvalida, match="escala de tiempo"):
            vuelo_trimble.leer_trayectoria(TRAYECTORIA.encode(), escala_de_tiempo="local")

    def test_una_linea_mala_se_rechaza_con_su_numero(self):
        malo = TRAYECTORIA + "C1-3,esto,no,es,,2025-12-29 15:38:13.6000000\n"
        with pytest.raises(ComposicionInvalida, match="línea 4"):
            vuelo_trimble.leer_trayectoria(malo.encode())
        with pytest.raises(ComposicionInvalida, match="línea 1"):
            vuelo_trimble.leer_trayectoria(b"a,b\n")

    def test_un_archivo_vacio_se_rechaza(self):
        with pytest.raises(ComposicionInvalida, match="ningún punto"):
            vuelo_trimble.leer_trayectoria(b"\n\n")

    def test_acepta_utf8_con_bom_y_cp1252(self):
        assert vuelo_trimble.leer_trayectoria(b"\xef\xbb\xbf" + TRAYECTORIA.encode())
        assert vuelo_trimble.leer_trayectoria(TRAYECTORIA.replace("C1", "Ñ1").encode("cp1252"))


class TestPosicionesPorFoto:
    def test_el_archivo_corto_trae_este_norte_y_altura(self):
        corto = "DJI_0001_V.JPG,414891.733,7418747.281,1122.911\nDJI_0002_V.JPG,1,2,3\n"
        p = vuelo_trimble.leer_posiciones_por_foto(corto.encode())
        assert p[0].nombre == "DJI_0001_V.JPG" and p[0].altura == 1122.911 and p[0].lat is None

    def test_el_ampliado_trae_ademas_latitud_longitud_y_calidad(self):
        # El archivo real viene en cp1252: «Elevación» no es UTF-8.
        p = vuelo_trimble.leer_posiciones_por_foto(EXTENDIDO.encode("cp1252"))
        assert len(p) == 2 and p[0].calidad == "PPK"
        assert (p[0].lat, p[0].lon) == (-23.338638421, -69.832545359)
        assert p[0].altura == 1122.911

    def test_una_linea_mala_se_rechaza(self):
        with pytest.raises(ComposicionInvalida, match="línea 2"):
            vuelo_trimble.leer_posiciones_por_foto(b"a.jpg,1,2,3\nb.jpg,x,y,z\n")
        with pytest.raises(ComposicionInvalida, match="ninguna posición"):
            vuelo_trimble.leer_posiciones_por_foto(b"\n")


def _referencias(epsg: int, n: int = 12) -> list[vuelo_trimble.PosicionDeFoto]:
    """Posiciones cuyo Este/Norte salen de latitud/longitud conocidas en el sistema `epsg`."""
    transformador = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    salida = []
    for i in range(n):
        lat, lon = -23.33 - i * 1e-3, -69.83 + i * 2e-3
        este, norte = transformador.transform(lon, lat)
        salida.append(
            vuelo_trimble.PosicionDeFoto(f"f{i}.jpg", este, norte, 1000.0, lat, lon, "PPK")
        )
    return salida


class TestIdentificarElSistema:
    def test_el_que_se_uso_coincide_y_los_antiguos_no(self):
        candidatos = vuelo_trimble.identificar_sistema(_referencias(32719))
        coinciden = {c.epsg for c in candidatos if c.coincide}
        assert coinciden == {32719, 5361, 31979}
        por = {c.epsg: c for c in candidatos}
        assert por[24879].error_medio_m > 100 and not por[24879].coincide  # PSAD56
        assert por[29189].error_medio_m > 30 and not por[29189].coincide  # SAD69
        assert por[32718].error_medio_m > 1_000  # la zona de al lado

    def test_los_que_coinciden_se_dicen_juntos_y_sin_elegir_uno(self):
        texto = vuelo_trimble.veredicto(vuelo_trimble.identificar_sistema(_referencias(32719)))
        assert "WGS 84 / UTM 19S" in texto and "SIRGAS-Chile 2002 / UTM 19S" in texto
        assert "no se distinguen entre sí" in texto

    def test_si_los_datos_estaban_en_psad56_se_identifica_psad56(self):
        candidatos = vuelo_trimble.identificar_sistema(_referencias(24879))
        mejores = [c for c in candidatos if c.coincide]
        assert [c.epsg for c in mejores] == [24879]
        assert not mejores[0].usable
        assert "PSAD56" in vuelo_trimble.veredicto(candidatos)

    def test_si_ninguno_coincide_se_dice_el_mejor_y_su_distancia(self):
        refs = [
            vuelo_trimble.PosicionDeFoto("a", r.este + 5000, r.norte, 0, r.lat, r.lon)
            for r in _referencias(32719)
        ]
        texto = vuelo_trimble.veredicto(vuelo_trimble.identificar_sistema(refs))
        assert texto.startswith("Ningún sistema") and "otro sistema, o en otra zona" in texto

    def test_sin_latitud_y_longitud_no_hay_con_que_medir(self):
        sin = [vuelo_trimble.PosicionDeFoto("a", 1.0, 2.0, 3.0)]
        with pytest.raises(ComposicionInvalida, match="export_extended"):
            vuelo_trimble.identificar_sistema(sin)

    def test_mide_una_muestra_y_no_las_dos_mil_fotos(self):
        refs = _referencias(32719, n=2000)
        assert vuelo_trimble.identificar_sistema(refs, muestra=100)[0].coincide


class TestATrayectoria:
    def test_pasa_a_latitud_y_longitud_con_el_sistema_declarado(self):
        puntos = vuelo_trimble.leer_trayectoria(TRAYECTORIA.encode())
        tray = vuelo_trimble.a_trayectoria(puntos, 32719)
        esperado = Transformer.from_crs("EPSG:32719", "EPSG:4326", always_xy=True).transform(
            puntos[0].este, puntos[0].norte
        )
        assert (tray.epocas[0].lon, tray.epocas[0].lat) == pytest.approx(esperado, abs=1e-12)
        assert tray.epocas[0].alt_m == 1039.022
        assert "no declarada" in tray.referencia_de_altura

    def test_la_calidad_y_la_incertidumbre_quedan_sin_informar(self):
        tray = vuelo_trimble.a_trayectoria(
            vuelo_trimble.leer_trayectoria(TRAYECTORIA.encode()), 32719
        )
        assert tray.epocas[0].q == 0 and tray.epocas[0].calidad == "no informada"
        assert math.isnan(tray.epocas[0].sdn_m)

    def test_un_sistema_antiguo_o_desconocido_se_rechaza(self):
        puntos = vuelo_trimble.leer_trayectoria(TRAYECTORIA.encode())
        with pytest.raises(ComposicionInvalida, match="transformación de datum"):
            vuelo_trimble.a_trayectoria(puntos, 24879)
        with pytest.raises(ComposicionInvalida, match="no es uno de los sistemas"):
            vuelo_trimble.a_trayectoria(puntos, 4326)

    def test_sincronizar_sobre_ella_no_inventa_calidad_ni_incertidumbre(self):
        puntos = vuelo_trimble.leer_trayectoria(TRAYECTORIA.encode())
        tray = vuelo_trimble.a_trayectoria(puntos, 32719)
        disparo = vuelo_sync.Disparo(1, puntos[0].t_gps_s + 0.1)
        foto = vuelo_sync.sincronizar(tray, [disparo])[0]
        assert foto.con_posicion and foto.q == 0 and math.isnan(foto.sdn_m)
        fila = vuelo_sync.a_csv([foto], referencia_de_altura=tray.referencia_de_altura)
        cuerpo = fila.splitlines()[1].split(",")
        cabecera = fila.splitlines()[0].split(",")
        assert cuerpo[cabecera.index("sdn_m")] == ""
        assert cuerpo[cabecera.index("calidad")] == "no informada"
        assert "no declarada" in cuerpo[cabecera.index("referencia_de_altura")]
        assert "NaN" not in vuelo_sync.a_geojson([foto], "SIRGAS-Chile")
