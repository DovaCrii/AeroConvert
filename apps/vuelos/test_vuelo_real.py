"""Un vuelo real contra Trimble Business Center (F18.2, F18.6): el oráculo de verdad.

Los datos **nunca van en el repositorio** (regla de `AGENTS.md`): la prueba corre solo si
`AEROCONVERT_VUELO_DE_PRUEBA` apunta a la carpeta de un vuelo con

- el `.MRK` del dron (`*Timestamp.MRK`),
- la trayectoria que sacó Trimble Business Center (`NNN.csv`) y
- las posiciones de las fotos que sacó el UAS sync de Trimble (`* export_extended.csv`).

**Lo que se mide:** con la trayectoria de Trimble y los disparos del `.MRK`, la posición de cada
foto que calcula `vuelo_sync` (con el desfase de la antena) contra la que entregó Trimble para
la misma foto. Trimble es el otro lector: otro programa, otro autor y otro código.

Cifras del vuelo con que se escribió (Matrice 3E, 2025-12-29, 2 505 fotos, UTM 19S), medidas el
2026-10-08: desviación de 0,3 mm en las tres componentes y 0,9 mm en el peor caso, que es el
redondeo a tres decimales del CSV de Trimble. Sin el desfase de la antena la diferencia es de 8,6 cm
en la altura y 29 mm de desviación en el norte.
"""

from __future__ import annotations

import csv
import io
import os
import re
import statistics
from pathlib import Path

import pytest
from pyproj import Transformer

from apps.vuelos import vuelo_proceso, vuelo_sync, vuelo_trimble

CARPETA = os.environ.get("AEROCONVERT_VUELO_DE_PRUEBA", "")

pytestmark = [
    pytest.mark.oraculo,
    pytest.mark.skipif(
        not CARPETA or not Path(CARPETA).is_dir(),
        reason="AEROCONVERT_VUELO_DE_PRUEBA no apunta a la carpeta de un vuelo",
    ),
]


@pytest.fixture(scope="module")
def vuelo():
    carpeta = Path(CARPETA)

    def uno(patron: str) -> Path:
        hallados = sorted(carpeta.glob(patron))
        assert hallados, f"falta {patron} en {carpeta}"
        return hallados[0]

    mrk = vuelo_sync.leer_mrk(uno("*Timestamp.MRK").read_text(encoding="utf-8"))
    puntos = vuelo_trimble.leer_trayectoria(uno("[0-9][0-9][0-9].csv").read_bytes())
    referencia = vuelo_trimble.leer_posiciones_por_foto(uno("*export_extended.csv").read_bytes())
    return mrk, puntos, referencia


def _residuos(vuelo, *, aplicar_desfase: bool):
    mrk, puntos, referencia = vuelo
    tray = vuelo_trimble.a_trayectoria(puntos, 32719)
    fotos = vuelo_sync.sincronizar(
        tray, mrk, [r.nombre for r in referencia], aplicar_desfase=aplicar_desfase
    )
    a_utm = Transformer.from_crs("EPSG:4326", "EPSG:32719", always_xy=True)
    dn, de, du = [], [], []
    for f, r in zip(fotos, referencia, strict=True):
        assert f.con_posicion, f"{f.nombre}: {f.motivo}"
        este, norte = a_utm.transform(f.lon, f.lat)
        dn.append(r.norte - norte)
        de.append(r.este - este)
        du.append(r.altura - f.alt_m)
    return dn, de, du


def test_hay_tantos_disparos_como_fotos_y_la_trayectoria_no_tiene_huecos(vuelo):
    mrk, puntos, referencia = vuelo
    assert len(mrk) == len(referencia) > 1000
    assert all(r.calidad == "PPK" for r in referencia)
    tray = vuelo_trimble.a_trayectoria(puntos, 32719)
    assert tray.huecos() == [] and abs(tray.intervalo_tipico_s - 0.2) < 1e-3


def test_con_el_desfase_la_posicion_de_cada_foto_coincide_con_trimble_al_milimetro(vuelo):
    dn, de, du = _residuos(vuelo, aplicar_desfase=True)
    for nombre, v in (("norte", dn), ("este", de), ("altura", du)):
        assert max(map(abs, v)) < 0.002, f"{nombre}: el peor caso pasa de 2 mm"
        assert statistics.pstdev(v) < 0.001, f"{nombre}: desviación pasa de 1 mm"


def test_sin_el_desfase_no_coincide_y_la_prueba_distingue_la_diferencia(vuelo):
    dn, _de, du = _residuos(vuelo, aplicar_desfase=False)
    assert abs(statistics.mean(du)) > 0.08, "la cámara cuelga unos 8,6 cm por debajo de la antena"
    assert statistics.pstdev(dn) > 0.02


def test_el_sistema_de_las_coordenadas_de_trimble_se_identifica_midiendo(vuelo):
    _mrk, _puntos, referencia = vuelo
    candidatos = vuelo_trimble.identificar_sistema(referencia)
    assert {c.epsg for c in candidatos if c.coincide} == {32719, 5361, 31979}
    por = {c.epsg: c for c in candidatos}
    assert por[24879].error_medio_m > 400, "PSAD56 queda a unos 418 m"
    assert 60 < por[29189].error_medio_m < 90, "SAD69 queda a unos 73 m"
    assert "no se distinguen entre sí" in vuelo_trimble.veredicto(candidatos)


def test_la_altura_de_trimble_no_es_la_elipsoidal_del_mrk(vuelo):
    """Difieren unos 35 m: la salida dice de qué altura se trata y no la llama elipsoidal."""
    mrk, puntos, _referencia = vuelo
    tray = vuelo_trimble.a_trayectoria(puntos, 32719)
    fotos = vuelo_sync.sincronizar(tray, mrk)
    assert "no declarada" in tray.referencia_de_altura
    assert fotos[0].alt_m is not None


def test_el_proceso_entero_con_el_vuelo_real(vuelo):
    """`procesar` de punta a punta: lo que hace la pantalla «Corregir un vuelo de dron».

    Medido el 2026-10-08: 2 505 fotos y 7 519 puntos en **un segundo**, con las posiciones a
    0,65 mm de las de Trimble como máximo.
    """
    carpeta = Path(CARPETA)

    def uno(patron: str) -> Path:
        return sorted(carpeta.glob(patron))[0]

    mrk = uno("*Timestamp.MRK")
    r = vuelo_proceso.procesar(
        trayectoria=uno("[0-9][0-9][0-9].csv").read_bytes(),
        disparos=mrk.read_bytes(),
        nombre_de_disparos=mrk.name,
        referencia=uno("*export_extended.csv").read_bytes(),
        nombres_en_carpeta=vuelo_proceso.nombres_de_fotos(carpeta),
        escala_de_tiempo="GPST",
    )
    assert r.resumen["fotos"] == r.resumen["con_posicion"] == 2505
    assert r.resumen["sistema_epsg"] == 32719 and r.resumen["sistema_como"].startswith("medido")
    assert r.resumen["contraste_maximo_mm"] < 2.0
    assert r.avisos == [] and r.resumen["desfase_aplicado"] == 2505

    import json

    datos = json.loads(r.archivos["vuelo.json"])
    assert len(datos["fotos"]) == 2505 and datos["trayectoria_total"] == 7519
    assert len(datos["trayectoria"]) <= vuelo_proceso.PUNTOS_DEL_VISOR + 1
    assert all(f["miniatura"] for f in datos["fotos"]), "las 2 505 fotos están en la carpeta"


def test_la_posicion_escrita_en_fotos_reales_de_dji_la_lee_otro_lector():
    """F18.5 con fotos de DJI de verdad (EXIF de ~31 kB con MakerNote y XMP), no sintéticas.

    Medido el 2026-10-08 con fotos de una Matrice: `exifread` lee la posición escrita, el XMP deja
    de repetir la del dron, la imagen y el MakerNote quedan iguales y el original conserva su
    sha256 y su mtime.
    """
    import hashlib
    import io

    import exifread
    from PIL import Image

    from apps.vuelos import fotos_dron, vuelo_exif

    fotos = sorted(Path(CARPETA).glob("*.JPG"))[:3] or sorted(Path(CARPETA).glob("*.jpg"))[:3]
    assert fotos, "la carpeta del vuelo no trae fotos"
    for ruta in fotos:
        original = ruta.read_bytes()
        huella = (hashlib.sha256(original).hexdigest(), ruta.stat().st_mtime_ns)
        nuevo = vuelo_exif.poner_posicion(original, -23.1234567, -69.7654321, 1234.567)

        e = exifread.process_file(io.BytesIO(nuevo), details=False)
        g, m, s = (float(v.num) / float(v.den) for v in e["GPS GPSLatitude"].values)
        assert -(g + m / 60 + s / 3600) == pytest.approx(-23.1234567, abs=1e-9)
        assert str(e["GPS GPSLatitudeRef"]) == "S" and str(e["GPS GPSMapDatum"]) == "WGS-84"

        assert fotos_dron._segmentos(nuevo)[1] == fotos_dron._segmentos(original)[1]
        a, b = Image.open(io.BytesIO(original)), Image.open(io.BytesIO(nuevo))
        assert a.tobytes() == b.tobytes()
        assert a.getexif().get_ifd(0x8769).get(0x927C) == b.getexif().get_ifd(0x8769).get(0x927C)
        assert b'GpsLatitude="-23.12345670"' in nuevo

        assert (hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns) == huella


# --- Las fotos del vuelo real: la ficha, la posición RTK y la orientación (F18.8 a F18.10) ------

#: Se lee **una foto de cada 25** (y la última): las 2 505 son unos 17 GB en una carpeta de
#: OneDrive, y bajarlas todas para comprobar lo mismo no aporta. Con las 102 se midió lo de abajo.
SALTO_DE_LA_MUESTRA = 25


@pytest.fixture(scope="module")
def muestra():
    from apps.vuelos import ficha_foto

    carpeta = Path(CARPETA)
    nombres = vuelo_proceso.nombres_de_fotos(carpeta)
    indices = [*range(0, len(nombres), SALTO_DE_LA_MUESTRA), len(nombres) - 1]
    mrk_ruta = sorted(carpeta.glob("*Timestamp.MRK"))[0]
    lineas = [x for x in mrk_ruta.read_text(encoding="utf-8").splitlines() if x.strip()]
    referencia = vuelo_trimble.leer_posiciones_por_foto(
        sorted(carpeta.glob("*export_extended.csv"))[0].read_bytes()
    )
    assert len(nombres) == len(lineas) == len(referencia), "las tres listas son de las mismas fotos"
    return {
        "indices": indices,
        "fichas": [ficha_foto.leer_ficha(carpeta / nombres[i]) for i in indices],
        # El `.MRK` de esas mismas fotos: sus líneas, con su número original.
        "mrk": ("\n".join(lineas[i] for i in indices) + "\n").encode("utf-8"),
        "referencia": [referencia[i] for i in indices],
    }


def test_las_fotos_del_vuelo_real_dan_su_posicion_rtk_y_el_mrk_la_confirma(muestra):
    """F18.8 con fotos de DJI de verdad: la posición del XMP contra la del `.MRK`.

    Medido el 2026-10-09 (Matrice 3E, 102 de las 2 505 fotos, una de cada 25): el XMP coincide
    con la posición del `.MRK` a 0,7 mm como máximo en horizontal y a 0,0 mm en altura, y la
    `AbsoluteAltitude` es la `Ellh` del `.MRK`. La bandera `RtkFlag` vale 16 (posición simple) en
    todas, aunque `GpsStatus` diga «RTK»: ese vuelo fue PPK, sin corrección en el aire.
    """
    from collections import Counter

    from apps.vuelos import vuelo_rtk

    fichas = muestra["fichas"]
    assert Counter(f.rtk_bandera for f in fichas) == {16: len(fichas)}
    # La columna `Q` del `.MRK` (el otro lector de la calidad) dice lo mismo que `RtkFlag`.
    q_del_mrk = [
        int(re.search(r"(\d+),Q", x).group(1)) for x in muestra["mrk"].decode().splitlines()
    ]
    assert q_del_mrk == [f.rtk_bandera for f in fichas]
    assert {f.gps_estado for f in fichas} == {"RTK"} and {f.calidad for f in fichas} == {"simple"}
    assert {f.datum for f in fichas} == {"WGS-84"} and {f.posicion_de for f in fichas} == {"XMP"}

    r = vuelo_rtk.procesar(
        fichas=fichas,
        disparos=muestra["mrk"],
        nombre_de_disparos="vuelo_Timestamp.MRK",
        sistema="32719",
    )
    assert r.resumen["fotos"] == r.resumen["con_posicion"] == len(fichas)
    assert r.resumen["comprobado_contra_el_mrk_mm"] < 2.0
    assert r.referencia_de_altura.startswith("elipsoidal")
    assert r.resumen["fotos_con_posicion_fija"] == 0
    assert any("no tienen posición fija" in a for a in r.avisos)
    assert {
        f["calidad"] for f in csv.DictReader(io.StringIO(r.archivos["fotos.csv"].decode()))
    } == {"simple"}


def test_la_ficha_del_vuelo_real_coincide_con_el_export_extended_de_trimble(muestra):
    """F18.9: cada dato de la ficha contra la columna de Trimble de la misma foto.

    Medido el 2026-10-09 sobre 102 fotos: la diferencia máxima es **0** en todos (focal, apertura,
    exposición, ISO, dimensiones, gimbal, actitud del dron, velocidades y alturas).
    """
    columnas = {
        "gimbal_guinada_deg": "Gimbal Yaw",
        "gimbal_cabeceo_deg": "Gimbal Pitch",
        "gimbal_alabeo_deg": "Gimbal Roll",
        "dron_guinada_deg": "UAV Yaw",
        "dron_cabeceo_deg": "UAV Pitch",
        "dron_alabeo_deg": "UAV Roll",
        "velocidad_x_ms": "V. UAV X",
        "velocidad_y_ms": "V. UAV Y",
        "velocidad_z_ms": "V. UAV Z",
        "alt_m": "Alt. abs. vuelo",
        "altura_relativa_m": "Alt.rel.vuelo",
        "focal_mm": "Focal",
        "apertura_f": "F Number",
        "exposicion_s": "Tiempo exp.",
        "iso": "ISO Speed",
    }
    for ficha, r in zip(muestra["fichas"], muestra["referencia"], strict=True):
        assert ficha.nombre == r.nombre
        for campo, columna in columnas.items():
            assert getattr(ficha, campo) == pytest.approx(float(r.extras[columna]), abs=1e-9), (
                ficha.nombre,
                campo,
            )
        assert f"{ficha.ancho_px} x {ficha.alto_px}" == r.extras["Dimensiones"]
        assert ficha.modelo in r.extras["Modelo"]
