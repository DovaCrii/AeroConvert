"""La orientación de la cámara en el CSV (F18.10): guiñada, cabeceo y alabeo del gimbal.

Las columnas `gimbal_guinada_deg`, `gimbal_cabeceo_deg` y `gimbal_alabeo_deg` de `fotos.csv` salen
del XMP de DJI de cada foto de la carpeta o, si no hay carpeta, del archivo ampliado de Trimble.
Contra qué se comprueba cada una:

- las **fotos**: el valor que la prueba escribió en el XMP, leído de vuelta con un **analizador de
  XML** (no la expresión regular del código), y el CSV con `csv`;
- **Trimble**: la columna `Gimbal Yaw`, `Gimbal Pitch` y `Gimbal Roll` del CSV que la prueba escribe
  con otro lector (`csv`).

Cada foto tiene valores **distintos** (si fueran iguales, un CSV que repite la primera fila daría
verde). El contraste con el vuelo real está en `test_vuelo_real.py`.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from apps.vuelos import vuelo_proceso, vuelo_rtk, vuelo_sync
from apps.vuelos.test_ficha_foto import _xmp_con_xml, jpeg_de_dji
from apps.vuelos.test_vuelo_ficha import _export_extendido
from apps.vuelos.test_vuelo_proceso import (
    N_FOTOS,
    _mrk,
    _trayectoria,
)
from apps.vuelos.test_vuelo_rtk import _antena_ll


def _guinada(i: int) -> float:
    return -170.0 + 7.25 * i


def _cabeceo(i: int) -> float:
    return -90.0 + 0.5 * i


def _alabeo(i: int) -> float:
    return 0.0 if i % 2 else 1.25 + i / 100


def _carpeta(tmp_path: Path, *, con_xmp: bool = True, nombres="DJI_{n:04d}_V.JPG") -> Path:
    """Fotos con el XMP de DJI y una orientación **distinta** en cada una."""
    carpeta = tmp_path / "fotos"
    carpeta.mkdir(exist_ok=True)
    for i in range(N_FOTOS):
        datos = (
            jpeg_de_dji(
                GimbalYawDegree=f"{_guinada(i):+.2f}",
                GimbalPitchDegree=f"{_cabeceo(i):+.2f}",
                GimbalRollDegree=f"{_alabeo(i):+.2f}",
            )
            if con_xmp
            else jpeg_de_dji(xmp=b"")
        )
        (carpeta / nombres.format(n=i + 1)).write_bytes(datos)
    return carpeta


def _procesar(
    tmp_path, *, carpeta=True, referencia=True, con_xmp=True, nombres="DJI_{n:04d}_V.JPG", **extra
):
    base = {
        "trayectoria": _trayectoria(),
        "disparos": _mrk(),
        "nombre_de_disparos": "vuelo_Timestamp.MRK",
        "escala_de_tiempo": "GPST",
        "sistema": "32719",
    }
    if referencia:
        base["referencia"] = _export_extendido()
        base["sistema"] = "medir"
    if carpeta:
        c = _carpeta(tmp_path, con_xmp=con_xmp, nombres=nombres)
        base["nombres_en_carpeta"] = vuelo_proceso.nombres_de_fotos(c)
        base["fichas"] = vuelo_proceso.fichas_de_la_carpeta(c)
    base.update(extra)
    return vuelo_proceso.procesar(**base)


def _filas(r) -> list[dict]:
    return list(csv.DictReader(io.StringIO(r.archivos["fotos.csv"].decode())))


COLUMNAS = ("gimbal_guinada_deg", "gimbal_cabeceo_deg", "gimbal_alabeo_deg")


class TestLasColumnas:
    def test_estan_en_el_csv_con_la_unidad_y_el_nombre_que_dice_la_convencion(self):
        assert all(c in vuelo_sync.COLUMNAS_CSV for c in COLUMNAS)
        # Antes del motivo, que sigue siendo la última.
        assert vuelo_sync.COLUMNAS_CSV[-1] == "motivo"
        assert (
            vuelo_sync.COLUMNAS_CSV.index("gimbal_alabeo_deg") == len(vuelo_sync.COLUMNAS_CSV) - 2
        )

    def test_cada_nombre_lleva_su_unidad(self):
        assert all(c.endswith("_deg") for c in COLUMNAS)

    def test_de_las_fotos_cada_una_trae_su_orientacion(self, tmp_path):
        r = _procesar(tmp_path)
        carpeta = tmp_path / "fotos"
        filas = _filas(r)
        assert len(filas) == N_FOTOS
        for i, fila in enumerate(filas):
            x = _xmp_con_xml((carpeta / fila["foto"]).read_bytes())  # el otro lector
            assert float(fila["gimbal_guinada_deg"]) == float(x["GimbalYawDegree"]) == _guinada(i)
            assert float(fila["gimbal_cabeceo_deg"]) == float(x["GimbalPitchDegree"])
            assert float(fila["gimbal_alabeo_deg"]) == float(x["GimbalRollDegree"])
        assert r.resumen["con_orientacion"] == N_FOTOS
        assert r.resumen["orientacion_de"] == "el XMP de las fotos"

    def test_el_formato_son_dos_decimales_como_los_escribe_dji(self, tmp_path):
        fila = _filas(_procesar(tmp_path))[0]
        assert fila["gimbal_guinada_deg"] == "-170.00"
        assert fila["gimbal_cabeceo_deg"] == "-90.00"
        assert fila["gimbal_alabeo_deg"] == "1.25"

    def test_cabeceo_menos_90_es_la_camara_mirando_al_nadir(self, tmp_path):
        """La primera foto: cabeceo −90 y alabeo 0 es nadir. No se convierte ni se renombra."""
        fila = _filas(_procesar(tmp_path))[0]
        assert float(fila["gimbal_cabeceo_deg"]) == -90.0

    def test_de_trimble_si_no_hay_carpeta(self, tmp_path):
        r = _procesar(tmp_path, carpeta=False)
        crudo = list(csv.DictReader(io.StringIO(_export_extendido().decode("cp1252"))))
        filas = _filas(r)
        for fila, c in zip(filas, crudo, strict=True):
            assert float(fila["gimbal_guinada_deg"]) == float(c["Gimbal Yaw"])
            assert float(fila["gimbal_cabeceo_deg"]) == float(c["Gimbal Pitch"])
            assert float(fila["gimbal_alabeo_deg"]) == float(c["Gimbal Roll"])
        assert r.resumen["orientacion_de"] == "el archivo de Trimble"
        assert len({f["gimbal_guinada_deg"] for f in filas}) == N_FOTOS

    def test_el_xmp_de_la_foto_manda_sobre_el_archivo_de_trimble(self, tmp_path):
        r = _procesar(tmp_path)  # las dos fuentes, con valores distintos
        crudo = list(csv.DictReader(io.StringIO(_export_extendido().decode("cp1252"))))
        fila = _filas(r)[3]
        assert float(fila["gimbal_guinada_deg"]) == _guinada(3)
        assert float(fila["gimbal_guinada_deg"]) != float(crudo[3]["Gimbal Yaw"])

    def test_sin_de_donde_leerla_quedan_vacias_y_no_en_cero(self, tmp_path):
        r = _procesar(tmp_path, carpeta=False, referencia=False)
        for fila in _filas(r):
            assert all(fila[c] == "" for c in COLUMNAS)
        assert r.resumen["con_orientacion"] == 0 and r.resumen["orientacion_de"] == ""
        assert "van **vacías**" in r.archivos["calidad.md"].decode()

    def test_unas_fotos_sin_xmp_caen_al_archivo_de_trimble(self, tmp_path):
        r = _procesar(tmp_path, con_xmp=False)
        crudo = list(csv.DictReader(io.StringIO(_export_extendido().decode("cp1252"))))
        assert float(_filas(r)[0]["gimbal_guinada_deg"]) == float(crudo[0]["Gimbal Yaw"])
        assert r.resumen["orientacion_de"] == "el archivo de Trimble"

    def test_una_foto_sin_orientacion_entre_las_que_la_traen_se_cuenta_y_se_avisa(self, tmp_path):
        carpeta = _carpeta(tmp_path)
        (carpeta / "DJI_0004_V.JPG").write_bytes(jpeg_de_dji(xmp=b""))
        r = vuelo_proceso.procesar(
            trayectoria=_trayectoria(),
            disparos=_mrk(),
            nombre_de_disparos="a.MRK",
            escala_de_tiempo="GPST",
            sistema="32719",
            nombres_en_carpeta=vuelo_proceso.nombres_de_fotos(carpeta),
            fichas=vuelo_proceso.fichas_de_la_carpeta(carpeta),
        )
        fila = _filas(r)[3]
        assert all(fila[c] == "" for c in COLUMNAS)
        assert r.resumen["con_orientacion"] == N_FOTOS - 1
        assert any("1 foto(s) quedan sin orientación" in a for a in r.avisos)

    def test_los_nombres_se_emparejan_sin_mirar_mayusculas(self, tmp_path):
        """Trimble dice `DJI_0001_V.JPG`; en Linux el archivo puede ser `dji_0001_v.jpg`."""
        r = _procesar(tmp_path, nombres="dji_{n:04d}_v.jpg")
        assert [float(f["gimbal_guinada_deg"]) for f in _filas(r)] == [
            _guinada(i) for i in range(N_FOTOS)
        ]
        assert r.resumen["orientacion_de"] == "el XMP de las fotos"


class TestElInformeDiceLaConvencion:
    def test_dice_de_donde_salio_y_la_convencion_de_dji_sin_convertir(self, tmp_path):
        texto = _procesar(tmp_path).archivos["calidad.md"].decode()
        assert "## Orientación de la cámara" in texto
        assert f"{N_FOTOS} de {N_FOTOS} fotos, leídas de el XMP de las fotos" in texto
        assert "cabeceo −90° = cámara mirando al nadir" in texto
        assert "**sin convertir**" in texto and "Metashape" in texto and "Pix4D" in texto
        assert "no dice si ese norte es el magnético o el geográfico" in texto

    def test_con_las_dos_fuentes_las_dice_las_dos(self, tmp_path):
        carpeta = _carpeta(tmp_path)
        (carpeta / "DJI_0004_V.JPG").write_bytes(jpeg_de_dji(xmp=b""))
        r = vuelo_proceso.procesar(
            trayectoria=_trayectoria(),
            disparos=_mrk(),
            nombre_de_disparos="a.MRK",
            referencia=_export_extendido(),
            escala_de_tiempo="GPST",
            nombres_en_carpeta=vuelo_proceso.nombres_de_fotos(carpeta),
            fichas={
                k: v
                for k, v in vuelo_proceso.fichas_de_la_carpeta(carpeta).items()
                if k != "dji_0004_v.jpg"
            },
        )
        assert r.resumen["orientacion_de"] == "el XMP de las fotos y el archivo de Trimble"


class TestUnaOrientacionPorCadaFotoYSoloLeeLaCabecera:
    def test_fichas_de_la_carpeta_omite_lo_que_no_se_puede_leer(self, tmp_path):
        carpeta = _carpeta(tmp_path)
        (carpeta / "DJI_0002_V.JPG").write_bytes(b"roto")
        fichas = vuelo_proceso.fichas_de_la_carpeta(carpeta)
        assert len(fichas) == N_FOTOS - 1 and "dji_0002_v.jpg" not in fichas

    def test_las_fotos_originales_no_se_tocan(self, tmp_path):
        import hashlib

        carpeta = _carpeta(tmp_path)
        antes = {
            str(f): (hashlib.sha256(f.read_bytes()).hexdigest(), f.stat().st_mtime_ns)
            for f in sorted(carpeta.iterdir())
        }
        vuelo_proceso.fichas_de_la_carpeta(carpeta)
        assert {
            str(f): (hashlib.sha256(f.read_bytes()).hexdigest(), f.stat().st_mtime_ns)
            for f in sorted(carpeta.iterdir())
        } == antes


class TestElVueloRtkTambienLaTrae:
    def test_las_columnas_de_un_vuelo_rtk_salen_del_xmp(self, tmp_path):
        from apps.vuelos.test_vuelo_rtk import _mrk as _mrk_rtk

        carpeta = tmp_path / "rtk"
        carpeta.mkdir()
        for i in range(N_FOTOS):
            lat, lon, alto = _antena_ll(i)
            (carpeta / f"DJI_{i + 1:04d}_V.JPG").write_bytes(
                jpeg_de_dji(
                    GpsLatitude=f"{lat:.9f}",
                    GpsLongitude=f"{lon:.9f}",
                    AbsoluteAltitude=f"{alto:+.3f}",
                    GimbalYawDegree=f"{_guinada(i):+.2f}",
                    GimbalPitchDegree=f"{_cabeceo(i):+.2f}",
                    GimbalRollDegree=f"{_alabeo(i):+.2f}",
                )
            )
        r = vuelo_rtk.procesar(
            fichas=vuelo_rtk.leer_carpeta(carpeta),
            disparos=_mrk_rtk(),
            nombre_de_disparos="a.MRK",
            sistema="32719",
        )
        for i, fila in enumerate(_filas(r)):
            assert float(fila["gimbal_guinada_deg"]) == _guinada(i)
            assert float(fila["gimbal_cabeceo_deg"]) == _cabeceo(i)
        assert r.resumen["con_orientacion"] == N_FOTOS
        assert "Orientación de la cámara" in r.archivos["calidad.md"].decode()


class TestLasOrientacionesSinElResto:
    def test_a_csv_sin_orientaciones_deja_las_columnas_vacias(self):
        foto = vuelo_sync.FotoSincronizada(
            vuelo_sync.Disparo(1, 10.0), "a.jpg", 1.0, 2.0, 3.0, None, None, None, 1, ""
        )
        filas = list(csv.DictReader(io.StringIO(vuelo_sync.a_csv([foto]))))
        assert all(filas[0][c] == "" for c in COLUMNAS)

    def test_a_csv_con_orientaciones_por_nombre_en_minusculas(self):
        foto = vuelo_sync.FotoSincronizada(
            vuelo_sync.Disparo(1, 10.0), "A.JPG", 1.0, 2.0, 3.0, None, None, None, 1, ""
        )
        filas = list(
            csv.DictReader(
                io.StringIO(vuelo_sync.a_csv([foto], orientaciones={"a.jpg": (10.0, -90.0, 0.0)}))
            )
        )
        assert (
            filas[0]["gimbal_guinada_deg"],
            filas[0]["gimbal_cabeceo_deg"],
            filas[0]["gimbal_alabeo_deg"],
        ) == ("10.00", "-90.00", "0.00")

    def test_un_alabeo_que_falta_queda_vacio_y_los_otros_dos_no(self):
        foto = vuelo_sync.FotoSincronizada(
            vuelo_sync.Disparo(1, 10.0), "a.jpg", 1.0, 2.0, 3.0, None, None, None, 1, ""
        )
        filas = list(
            csv.DictReader(
                io.StringIO(vuelo_sync.a_csv([foto], orientaciones={"a.jpg": (5.5, -80.0, None)}))
            )
        )
        assert filas[0]["gimbal_alabeo_deg"] == "" and filas[0]["gimbal_guinada_deg"] == "5.50"

    def test_el_vuelo_json_no_cambia_de_forma(self, tmp_path):
        datos = json.loads(_procesar(tmp_path).archivos["vuelo.json"])
        assert "orientacion" not in datos["fotos"][0]
