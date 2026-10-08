"""«Vuelo de dron con PPK», el camino de Trimble, de punta a punta (F18.4).

El vuelo es **sintético y de fórmula conocida** (una recta a velocidad constante, cerca del
meridiano central de la zona 19, donde el Norte de la cuadrícula es el Norte verdadero), con un
`.MRK` de desfases conocidos y unas «posiciones de Trimble» que se calculan **a mano en la
cuadrícula** (Este y Norte suman, la altura resta `V`), sin pasar por `vuelo_sync`.
"""

from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET  # nosec B405 - solo se lee lo que escribimos en la prueba

import pytest
from pyproj import Transformer

from apps.documents import vuelo_proceso
from apps.documents.composicion import ComposicionInvalida

SEMANA = 2399
T0_TOW = 142_750.0
N_FOTOS = 40
GPS_INICIO_S = SEMANA * 604_800 + T0_TOW  # el primer disparo
EPSG = 32719

A_ENU = Transformer.from_crs("EPSG:4326", f"EPSG:{EPSG}", always_xy=True)
A_LL = Transformer.from_crs(f"EPSG:{EPSG}", "EPSG:4326", always_xy=True)


def _antena(t_s: float) -> tuple[float, float, float]:
    """La antena a `t_s` segundos del primer disparo: E, N, H en la cuadrícula."""
    return 499_900.0 + 12.0 * t_s, 7_420_000.0 + 3.0 * t_s, 1_100.0 + 0.1 * t_s


def _fecha(seg_gps: float) -> str:
    from datetime import datetime, timedelta

    return (datetime(1980, 1, 6) + timedelta(seconds=seg_gps)).strftime("%Y-%m-%d %H:%M:%S.%f")


def _trayectoria(n=2000, paso=0.2) -> bytes:
    filas = []
    for i in range(n):
        t = -10.0 + i * paso
        e, nn, h = _antena(t)
        filas.append(f"C1-{i},{e:.3f},{nn:.3f},{h:.3f},,{_fecha(GPS_INICIO_S + t)}0")
    return ("\n".join(filas) + "\n").encode()


def _desfase(i: int) -> tuple[int, int, int]:
    return (-40 + 2 * i, 10 - i, 60 + i)  # milímetros


def _instante(i: int) -> float:
    return 3.0 + i * 1.7  # los disparos no caen en un punto de la trayectoria


def _mrk() -> bytes:
    lineas = []
    for i in range(N_FOTOS):
        n, e, v = _desfase(i)
        tow = T0_TOW + _instante(i)
        lineas.append(
            f"{i + 1}\t{tow:.6f}\t[{SEMANA}]\t{n},N\t{e},E\t{v},V\t-23.0,Lat\t-69.0,Lon\t"
            "1100.000,Ellh\t1.5, 1.6, 3.5\t16,Q"
        )
    return ("\n".join(lineas) + "\n").encode()


def _fotos_de_trimble(*, error_m: float = 0.0, epsg_de_las_ll: int = EPSG) -> bytes:
    """Lo que entregaría Trimble: la cámara = antena + (N, E) y − V, con tres decimales."""
    filas = [
        "ID,Este,Norte,Elevación,Fecha,Modelo,Calidad,Latitud,Longitud,Altura",
    ]
    for i in range(N_FOTOS):
        n, e, v = _desfase(i)
        ea, na, ha = _antena(_instante(i))
        este, norte, alto = ea + e / 1000 + error_m, na + n / 1000, ha - v / 1000
        lon, lat = Transformer.from_crs(
            f"EPSG:{epsg_de_las_ll}", "EPSG:4326", always_xy=True
        ).transform(este, norte)
        filas.append(
            f"DJI_{i + 1:04d}_V.JPG,{este:.3f},{norte:.3f},{alto:.3f},2025:12:29 12:38:52,DJI M3E,"
            f"PPK,{lat:.9f},{lon:.9f},{alto:.3f}"
        )
    return ("\n".join(filas) + "\n").encode("cp1252")


def _hacer(**kw):
    base = {
        "trayectoria": _trayectoria(),
        "disparos": _mrk(),
        "nombre_de_disparos": "vuelo_Timestamp.MRK",
        "referencia": _fotos_de_trimble(),
        "escala_de_tiempo": "GPST",
    }
    base.update(kw)
    return vuelo_proceso.procesar(**base)


class TestDePuntaAPunta:
    def test_los_entregables_y_el_resumen(self):
        r = _hacer()
        assert set(r.archivos) == {
            "fotos.csv", "fotos.geojson", "fotos.kml", "calidad.md", "vuelo.json",
        }  # fmt: skip
        assert r.resumen["fotos"] == N_FOTOS and r.resumen["con_posicion"] == N_FOTOS
        assert r.resumen["sistema_epsg"] == EPSG and r.resumen["desfase_aplicado"] == N_FOTOS
        assert r.avisos == []

    def test_el_contraste_contra_las_posiciones_de_trimble_es_de_milimetros(self):
        r = _hacer()
        assert r.resumen["contraste_maximo_mm"] < 1.5
        texto = r.archivos["calidad.md"].decode()
        assert "Contraste con las posiciones de Trimble" in texto and "mm" in texto

    def test_el_csv_lleva_los_nombres_de_trimble_y_la_referencia_de_altura(self):
        filas = list(csv.DictReader(io.StringIO(_hacer().archivos["fotos.csv"].decode())))
        assert [f["foto"] for f in filas][:2] == ["DJI_0001_V.JPG", "DJI_0002_V.JPG"]
        assert (
            filas[0]["desfase_aplicado"] == "si"
            and "no declarada" in filas[0]["referencia_de_altura"]
        )
        assert filas[0]["calidad"] == "no informada"

    def test_el_geojson_y_el_kml_traen_una_por_foto(self):
        r = _hacer()
        assert len(json.loads(r.archivos["fotos.geojson"])["features"]) == N_FOTOS
        raiz = ET.fromstring(r.archivos["fotos.kml"])  # noqa: S314 - lo escribimos nosotros
        marcas = raiz.findall(".//{http://www.opengis.net/kml/2.2}Placemark")
        assert len(marcas) == N_FOTOS

    def test_los_datos_del_visor(self):
        datos = json.loads(_hacer(nombres_en_carpeta=["DJI_0001_V.JPG"]).archivos["vuelo.json"])
        assert datos["sistema"]["epsg"] == EPSG and "WGS 84" in datos["sistema"]["nombre"]
        assert datos["origen"]["este"] % 100 == 0
        assert len(datos["fotos"]) == N_FOTOS and len(datos["trayectoria"]) == 2000
        primera = datos["fotos"][0]
        assert primera["calidad"] == "PPK" and primera["miniatura"] is True
        assert datos["fotos"][1]["miniatura"] is False
        # x, y son metros desde el origen: sumándolos se vuelve al Este y Norte de la cuadrícula.
        este = datos["origen"]["este"] + primera["x"]
        esperado = _antena(_instante(0))[0] + _desfase(0)[1] / 1000
        assert este == pytest.approx(esperado, abs=0.002)

    def test_la_trayectoria_del_visor_se_adelgaza_pero_conserva_los_extremos(self):
        r = _hacer(trayectoria=_trayectoria(n=9000))
        datos = json.loads(r.archivos["vuelo.json"])
        assert 2900 < len(datos["trayectoria"]) <= vuelo_proceso.PUNTOS_DEL_VISOR + 1
        ultimo = _antena(-10.0 + 8999 * 0.2)
        assert datos["origen"]["este"] + datos["trayectoria"][-1][0] == pytest.approx(
            ultimo[0], abs=0.01
        )

    def test_el_avance_sube_y_dice_que_hace(self):
        pasos = []
        _hacer(progreso=lambda f, e: pasos.append((f, e)))
        fracciones = [f for f, _ in pasos]
        assert fracciones == sorted(fracciones) and fracciones[-1] == 1.0
        etiquetas = " | ".join(e for _, e in pasos)
        for esperado in ("Leyendo la trayectoria", "Midiendo el sistema", "Sincronizando", "Listo"):
            assert esperado in etiquetas


class TestElSistema:
    def test_medir_elige_uno_y_dice_los_que_dan_lo_mismo(self):
        r = _hacer(sistema="medir")
        texto = r.archivos["calidad.md"].decode()
        assert r.resumen["sistema_como"].startswith("medido")
        assert "Dan lo mismo" in texto and "SIRGAS" in texto
        assert "← coincide" in texto

    def test_declarar_el_correcto_se_comprueba(self):
        r = _hacer(sistema=str(EPSG))
        assert r.resumen["sistema_como"] == "declarado y comprobado contra Trimble"

    def test_declarar_uno_equivocado_se_rechaza_con_lo_que_se_midio(self):
        with pytest.raises(ComposicionInvalida, match=r"Declaró WGS 84 / UTM 18S.*quedan a"):
            _hacer(sistema="32718")

    def test_sin_las_posiciones_de_trimble_no_se_puede_medir(self):
        with pytest.raises(ComposicionInvalida, match="No hay con qué medir"):
            _hacer(referencia=None, sistema="medir")

    def test_sin_ellas_se_puede_declarar_y_se_dice_que_no_hay_con_que_comprobarlo(self):
        r = _hacer(referencia=None, sistema=str(EPSG))
        assert "no hay con qué comprobarlo" in r.resumen["sistema_como"]
        assert r.resumen["contraste_maximo_mm"] is None
        assert "No se hizo" in r.archivos["calidad.md"].decode()

    def test_si_los_datos_estan_en_psad56_se_dice_que_es_antiguo(self):
        referencia = _fotos_de_trimble(epsg_de_las_ll=24879)
        with pytest.raises(ComposicionInvalida, match="PSAD56|antiguo"):
            _hacer(referencia=referencia)

    def test_un_codigo_que_no_es_epsg_o_no_se_lee_se_rechaza(self):
        with pytest.raises(ComposicionInvalida, match="no es un código EPSG"):
            _hacer(sistema="utm")
        with pytest.raises(ComposicionInvalida, match="no es uno de los sistemas"):
            _hacer(sistema="4326")
        with pytest.raises(ComposicionInvalida, match="sistema antiguo"):
            _hacer(sistema="24879")


class TestElContraste:
    def test_si_las_posiciones_de_trimble_no_son_de_este_vuelo_avisa(self):
        r = _hacer(referencia=_fotos_de_trimble(error_m=0.02))
        assert any("no coinciden con las de Trimble" in a for a in r.avisos)
        assert r.resumen["contraste_maximo_mm"] > 15

    def test_sin_desfase_el_contraste_lo_delata(self):
        r = _hacer(aplicar_desfase=False)
        assert any("no coinciden" in a for a in r.avisos)


class TestNombres:
    def test_sin_trimble_salen_de_la_carpeta_por_orden(self):
        carpeta = [f"DJI_{i + 1:04d}_V.JPG" for i in range(N_FOTOS)]
        r = _hacer(referencia=None, sistema=str(EPSG), nombres_en_carpeta=carpeta)
        filas = list(csv.DictReader(io.StringIO(r.archivos["fotos.csv"].decode())))
        assert filas[0]["foto"] == "DJI_0001_V.JPG"
        assert "la carpeta de fotos" in r.archivos["calidad.md"].decode()

    def test_con_otra_cantidad_no_se_empareja(self):
        with pytest.raises(ComposicionInvalida, match="no se pueden emparejar"):
            _hacer(referencia=None, sistema=str(EPSG), nombres_en_carpeta=["a.jpg", "b.jpg"])

    def test_si_a_la_carpeta_le_faltan_fotos_de_trimble_se_avisa(self):
        r = _hacer(nombres_en_carpeta=["DJI_0001_V.JPG"])
        assert any("no están en la carpeta" in a for a in r.avisos)

    def test_sin_nombres_salen_por_numero_de_disparo(self):
        r = _hacer(referencia=None, sistema=str(EPSG))
        filas = list(csv.DictReader(io.StringIO(r.archivos["fotos.csv"].decode())))
        assert filas[0]["foto"] == "" and filas[0]["disparo"] == "1"
        assert len(json.loads(r.archivos["vuelo.json"])["fotos"]) == N_FOTOS


class TestDisparos:
    def test_una_lista_de_tiempos_en_lugar_del_mrk(self):
        texto = "\n".join(f"{SEMANA} {T0_TOW + _instante(i):.6f}" for i in range(N_FOTOS))
        r = _hacer(
            disparos=texto.encode(),
            nombre_de_disparos="tiempos.txt",
            referencia=None,
            sistema=str(EPSG),
        )
        assert r.resumen["con_posicion"] == N_FOTOS and r.resumen["desfase_aplicado"] == 0
        assert any("no trae el desfase de la antena" in a for a in r.avisos)

    def test_disparos_fuera_de_la_trayectoria_quedan_sin_posicion_y_se_avisan(self):
        tray = _trayectoria(n=60)  # solo cubre unos segundos
        r = _hacer(trayectoria=tray, referencia=None, sistema=str(EPSG))
        assert r.resumen["sin_posicion"] > 0
        assert any("sin posición" in a for a in r.avisos)
        datos = json.loads(r.archivos["vuelo.json"])
        assert any("motivo" in f for f in datos["fotos"])

    def test_un_hueco_en_la_trayectoria_se_avisa(self):
        filas = _trayectoria().decode().splitlines()
        sin_un_tramo = "\n".join(filas[:100] + filas[300:]) + "\n"
        r = _hacer(trayectoria=sin_un_tramo.encode(), referencia=None, sistema=str(EPSG))
        assert any("hueco" in a for a in r.avisos)

    def test_una_escala_de_tiempo_equivocada_se_nota_en_el_contraste(self):
        r = _hacer(escala_de_tiempo="UTC")
        assert any("no coinciden" in a for a in r.avisos) or r.resumen["sin_posicion"] > 0


class TestNombresDeCarpeta:
    def test_los_jpg_de_una_carpeta_en_orden(self, tmp_path):
        for nombre in ("b_0002.JPG", "a_0001.jpg", "c.png", "d_0003.JPEG"):
            (tmp_path / nombre).write_bytes(b"x")
        assert vuelo_proceso.nombres_de_fotos(tmp_path) == [
            "a_0001.jpg",
            "b_0002.JPG",
            "d_0003.JPEG",
        ]
