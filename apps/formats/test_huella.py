"""La huella de un archivo: esquinas en su sistema y en EPSG:4326 (F13.11).

El oráculo es `gdalinfo -json` (`wgs84Extent`), que **no comparte código con nosotros**: lee el
GeoTIFF con GDAL y proyecta con su propia PROJ. Tolerancia: 1e-7° (≈ 1 cm).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from apps.formats import deteccion, huella
from apps.formats.tests.constructor import geotiff_minimo, las_minimo


def _i(tmp_path, nombre: str, contenido: bytes):
    ruta = tmp_path / nombre
    ruta.write_bytes(contenido)
    return deteccion.inspeccionar(ruta)


class TestSinOraculo:
    def test_un_geotiff_da_cuatro_esquinas_en_su_sistema(self, tmp_path):
        i = _i(
            tmp_path,
            "o.tif",
            geotiff_minimo(ancho=100, alto=50, escala_m=0.5, origen=(1000.0, 2000.0)),
        )
        h = huella.de_inspeccion(i)
        assert h is not None
        assert h.en_su_sistema == (
            (1000.0, 2000.0),
            (1050.0, 2000.0),
            (1050.0, 1975.0),
            (1000.0, 1975.0),
        )
        assert h.sistema == "EPSG:32719"

    def test_un_las_usa_sus_minimos_y_maximos(self, tmp_path):
        i = _i(tmp_path, "n.las", las_minimo())
        h = huella.de_inspeccion(i)
        assert h is not None
        (x0, y1), (x1, _), (_, y0), _ = h.en_su_sistema
        assert (x0, y0, x1, y1) == (495003.24, 7318472.78, 495373.63, 7318841.78)

    def test_en_grados_cae_donde_corresponde_a_la_zona_19_sur(self, tmp_path):
        i = _i(tmp_path, "o.tif", geotiff_minimo())
        h = huella.de_inspeccion(i)
        for lon, lat in h.en_grados:
            assert -69.1 < lon < -69.0 and -24.3 < lat < -24.2, (lon, lat)

    def test_sin_sistema_no_hay_huella(self, tmp_path):
        i = _i(tmp_path, "sin.tif", geotiff_minimo(epsg=None))
        assert huella.de_inspeccion(i) is None

    def test_sin_origen_ni_escala_no_hay_huella(self, tmp_path):
        i = _i(tmp_path, "sin.tif", geotiff_minimo(escala_m=None, origen=None))
        assert huella.de_inspeccion(i) is None

    def test_un_codigo_que_proj_no_conoce_no_rompe(self, tmp_path):
        i = _i(tmp_path, "raro.tif", geotiff_minimo(epsg=32767))
        assert huella.de_inspeccion(i) in (None, huella.de_inspeccion(i))


sin_gdal = pytest.mark.skipif(
    shutil.which("gdalinfo") is None
    or shutil.which("gdal_create") is None
    and not Path(r"C:\Program Files\QGIS 4.0.2\bin\gdal_create.exe").exists(),
    reason="GDAL no esta en esta maquina",
)


def _herramienta(nombre: str) -> str:
    return shutil.which(nombre) or str(Path(r"C:\Program Files\QGIS 4.0.2\bin") / f"{nombre}.exe")


@pytest.mark.oraculo
@pytest.mark.skipif(
    shutil.which("gdalinfo") is None
    and not Path(r"C:\Program Files\QGIS 4.0.2\bin\gdalinfo.exe").exists(),
    reason="GDAL no esta en esta maquina",
)
@pytest.mark.parametrize(
    ("epsg", "caja"),
    [
        (32719, (495000.0, 7318000.0, 497000.0, 7319000.0)),
        (5361, (350000.0, 6300000.0, 352500.0, 6302000.0)),
        (24879, (700000.0, 7500000.0, 701000.0, 7501500.0)),
    ],
)
def test_las_esquinas_coinciden_con_gdalinfo(tmp_path, epsg, caja):
    x0, y0, x1, y1 = caja
    tif = tmp_path / "orto.tif"
    subprocess.run(  # noqa: S603 - argumentos fijos y rutas de la prueba
        [
            _herramienta("gdal_create"),
            "-outsize",
            "200",
            "100",
            "-a_srs",
            f"EPSG:{epsg}",
            "-a_ullr",
            str(x0),
            str(y1),
            str(x1),
            str(y0),
            str(tif),
        ],
        check=True,
        capture_output=True,
    )
    info = json.loads(
        subprocess.run(  # noqa: S603
            [_herramienta("gdalinfo"), "-json", str(tif)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    # GDAL: UL, LL, LR, UR, UL.  Nosotros: NO, NE, SE, SO.
    ul, ll, lr, ur, _ = info["wgs84Extent"]["coordinates"][0]
    esperado = (ul, ur, lr, ll)

    h = huella.de_inspeccion(deteccion.inspeccionar(tif))
    assert h is not None
    for (lon, lat), (lon_g, lat_g) in zip(h.en_grados, esperado, strict=True):
        assert abs(lon - lon_g) <= 1e-7, (epsg, lon, lon_g)
        assert abs(lat - lat_g) <= 1e-7, (epsg, lat, lat_g)
