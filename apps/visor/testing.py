"""Ayudas de las pruebas del visor: una ficha de `gdalinfo` y un GDAL de mentira.

Sirven para que el gate **sea verde en una máquina sin GDAL** (el CI). Lo que miden las pruebas que
las usan es el pegamento (rutas, permisos, caché, verificación de la salida), no GDAL; de GDAL de
verdad se ocupan las pruebas `oraculo`, que crean un GeoTIFF sintético y comparan con `gdalinfo`,
`gdaltransform`, `gdalwarp` independiente y `gdallocationinfo`.

**Ningún dato real**: el GeoTIFF sintético es un tablero de 20 píxeles de lado en UTM 19S, con
valores que se conocen de antemano.
"""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

from PIL import Image

from . import motor

#: El GeoTIFF sintético de todas las pruebas: 200 × 100 píxeles de 2 m, esquina noroeste en
#: (345 000, 6 295 100) de EPSG:32719, cerca de Santiago.
ANCHO_PX = 200
ALTO_PX = 100
PASO_M = 2.0
ESTE_NO_M = 345000.0
NORTE_NO_M = 6295100.0

#: Lo que `gdalinfo -json` dijo de ese archivo (GDAL 3.12.4, 2026-10-09): `wgs84Extent` en el orden
#: de GDAL —noroeste, suroeste, sureste, noreste, noroeste— y a siete decimales. Es **el otro
#: lector**: se copió de su salida, no de nuestro cálculo.
WGS84_EXTENT_DE_GDAL = (
    (-70.6681005, -33.4723649),
    (-70.6681351, -33.474168),
    (-70.6638318, -33.4742259),
    (-70.6637973, -33.4724227),
    (-70.6681005, -33.4723649),
)

WKT_UTM_19S = (
    'PROJCRS["WGS 84 / UTM zone 19S",BASEGEOGCRS["WGS 84",DATUM["World Geodetic System 1984",'
    'ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]]],'
    'PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]],ID["EPSG",4326]],'
    'CONVERSION["UTM zone 19S",METHOD["Transverse Mercator",ID["EPSG",9807]],'
    'PARAMETER["Latitude of natural origin",0,ANGLEUNIT["degree",0.0174532925199433],'
    'ID["EPSG",8801]],PARAMETER["Longitude of natural origin",-69,'
    'ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8802]],'
    'PARAMETER["Scale factor at natural origin",0.9996,SCALEUNIT["unity",1],ID["EPSG",8805]],'
    'PARAMETER["False easting",500000,LENGTHUNIT["metre",1],ID["EPSG",8806]],'
    'PARAMETER["False northing",10000000,LENGTHUNIT["metre",1],ID["EPSG",8807]]],'
    'CS[Cartesian,2],AXIS["(E)",east,ORDER[1],LENGTHUNIT["metre",1]],'
    'AXIS["(N)",north,ORDER[2],LENGTHUNIT["metre",1]],ID["EPSG",32719]]'
)


def _wkt_de_epsg(codigo: int) -> str:
    from pyproj import CRS

    return CRS.from_epsg(codigo).to_wkt()


#: EPSG:4326 tal como lo escribe PROJ (el de GDAL es el mismo): con otras palabras en los ejes no
#: sería ya «EPSG:4326» y el visor, a propósito, no lo afirmaría.
WKT_WGS84 = _wkt_de_epsg(4326)

WKT_LOCAL = 'LOCAL_CS["Obra norte",UNIT["metre",1]]'


def info_de_gdal(
    *,
    ancho: int = ANCHO_PX,
    alto: int = ALTO_PX,
    wkt: str | None = WKT_UTM_19S,
    geotransform: list[float] | None = None,
    tipo: str = "Byte",
    bandas: int = 3,
    interpretacion: str = "Red",
    overviews: bool = True,
) -> dict:
    """Lo que `gdalinfo -json` diría de un archivo. `wkt=None` es «no declara sistema»."""
    info: dict = {
        "size": [ancho, alto],
        "bands": [
            {"band": n + 1, "type": tipo, "colorInterpretation": interpretacion if n == 0 else "x"}
            for n in range(bandas)
        ],
    }
    if overviews:
        info["bands"][0]["overviews"] = [{"size": [ancho // 2, alto // 2]}]
    if wkt is not None:
        info["coordinateSystem"] = {"wkt": wkt}
    info["geoTransform"] = (
        geotransform
        if geotransform is not None
        else [ESTE_NO_M, PASO_M, 0.0, NORTE_NO_M, 0.0, -PASO_M]
    )
    return info


def png_de(lado: int = 256, color=(10, 120, 200, 255)) -> bytes:
    salida = io.BytesIO()
    Image.new("RGBA", (lado, lado), color).save(salida, "PNG")
    return salida.getvalue()


class GdalDeMentira:
    """Sustituye a `motor.correr`: contesta como GDAL en lo que importa y **anota qué se le pidió**.

    - `gdalinfo` devuelve `info` (y con `-approx_stats`, `minimo` y `maximo`).
    - `gdalwarp` escribe un PNG de `lado_de_salida` píxeles en su último argumento, o **nada**
      con `escribir=False` (el caso de ODA y de GDAL: código 0 y ningún archivo).
    - `gdal_translate` escribe un VRT mínimo; `gdallocationinfo` devuelve `valores`.
    """

    def __init__(self, info: dict | None = None):
        self.info = info if info is not None else info_de_gdal()
        self.llamadas: list[tuple[str, list[str]]] = []
        self.escribir = True
        self.lado_de_salida = 256
        self.contenido: bytes | None = None
        self.minimo, self.maximo = 0.0, 4000.0
        self.valores = ["10", "20", "30"]
        self.fallar_con: motor.ErrorDeGdal | None = None

    def contar(self, nombre: str) -> int:
        return sum(1 for n, _ in self.llamadas if n == nombre)

    def __call__(self, nombre: str, argumentos: list[str], *, plazo_s: int):
        self.llamadas.append((nombre, list(argumentos)))
        if self.fallar_con is not None:
            raise self.fallar_con
        if nombre == "gdalinfo":
            info = json.loads(json.dumps(self.info))
            if "-approx_stats" in argumentos:
                info["bands"][0]["minimum"] = self.minimo
                info["bands"][0]["maximum"] = self.maximo
            return motor.Resultado(salida=json.dumps(info), errores="")
        if nombre == "gdallocationinfo":
            return motor.Resultado(salida="\n".join(self.valores) + "\n", errores="")
        destino = Path(argumentos[-1])
        if nombre == "gdalwarp" and self.escribir:
            destino.write_bytes(
                self.contenido if self.contenido is not None else png_de(self.lado_de_salida)
            )
        elif nombre == "gdal_translate" and self.escribir:
            destino.write_text("<VRTDataset rasterXSize='1'></VRTDataset>", encoding="utf-8")
        return motor.Resultado(salida="", errores="")


def crear_geotiff_sintetico(
    destino: Path,
    *,
    tipo: str = "Byte",
    bandas: int = 3,
    ancho: int = ANCHO_PX,
    alto: int = ALTO_PX,
    epsg: str | None = "EPSG:32719",
    caja: tuple[float, float, float, float] | None = None,
) -> Path:
    """Un GeoTIFF sintético **con GDAL de verdad** (solo para las pruebas `oraculo`).

    Un tablero de 20 píxeles de lado con un degradado en los otros canales: valores que se conocen,
    no una foto. `caja` es `(oeste, norte, este, sur)` en el sistema `epsg`.
    """
    caja = caja or (
        ESTE_NO_M,
        NORTE_NO_M,
        ESTE_NO_M + ancho * PASO_M,
        NORTE_NO_M - alto * PASO_M,
    )
    imagen = Image.new("RGB", (ancho, alto))
    puntos = imagen.load()
    for fila in range(alto):
        for columna in range(ancho):
            casilla = (columna // 20 + fila // 20) % 2
            puntos[columna, fila] = (
                255 if casilla else 0,
                min(255, columna * 255 // max(ancho - 1, 1)),
                min(255, fila * 255 // max(alto - 1, 1)),
            )
    intermedio = destino.with_suffix(".png")
    imagen.save(intermedio)
    argumentos = ["-q", "-a_ullr", *(repr(v) for v in caja), "-of", "GTiff"]
    if (
        epsg
    ):  # `None`: georreferenciado en metros pero **sin** sistema, para la prueba de la regla 3
        argumentos += ["-a_srs", epsg]
    if tipo != "Byte":
        argumentos += ["-ot", tipo, "-scale", "0", "255", "100", "3000"]
    if bandas == 1:
        argumentos += ["-b", "1"]
    argumentos += [str(intermedio), str(destino)]
    motor.correr("gdal_translate", argumentos, plazo_s=60)
    intermedio.unlink()
    return destino


def herramienta_externa(
    nombre: str, argumentos: list[str], entrada: str | None = None
) -> subprocess.CompletedProcess:
    """Una herramienta de GDAL **por su cuenta**, la del oráculo: sin pasar por `motor.correr`."""
    programa = motor.ejecutable(nombre)
    assert programa, f"No hay {nombre}"
    return subprocess.run(  # nosec B603
        [programa, *argumentos],
        input=entrada,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        timeout=120,
        env=motor.entorno(),
    )
