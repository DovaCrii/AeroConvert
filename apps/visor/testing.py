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
import math
import re
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
    unidad: str | None = None,
    sin_dato: float | str | None = None,
) -> dict:
    """Lo que `gdalinfo -json` diría de un archivo. `wkt=None` es «no declara sistema».

    `unidad` y `sin_dato` son lo que declara la primera banda (`unit`, `noDataValue`): un DEM.
    """
    info: dict = {
        "size": [ancho, alto],
        "bands": [
            {"band": n + 1, "type": tipo, "colorInterpretation": interpretacion if n == 0 else "x"}
            for n in range(bandas)
        ],
    }
    if unidad is not None:
        info["bands"][0]["unit"] = unidad
    if sin_dato is not None:
        info["bands"][0]["noDataValue"] = sin_dato
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


def info_de_dem(**cambios) -> dict:
    """Lo que `gdalinfo -json` diría de un DEM: `Float32` en metros y `-9999` de «sin dato»."""
    base = {
        "bandas": 1,
        "tipo": "Float32",
        "interpretacion": "Gray",
        "unidad": "m",
        "sin_dato": -9999.0,
    }
    return info_de_gdal(**{**base, **cambios})


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
        #: Lo que se le mandó por stdin a cada llamada (en el mismo orden que `llamadas`).
        self.entradas: list[str | None] = []
        self.cotas_del_perfil: list[str] | None = None
        self.tipo_del_sombreado = "Byte"
        self.tamano_del_sombreado: tuple[int, int] | None = None

    def contar(self, nombre: str) -> int:
        return sum(1 for n, _ in self.llamadas if n == nombre)

    def __call__(
        self, nombre: str, argumentos: list[str], *, plazo_s: int, entrada: str | None = None
    ):
        self.llamadas.append((nombre, list(argumentos)))
        self.entradas.append(entrada)
        if self.fallar_con is not None:
            raise self.fallar_con
        if nombre == "gdalinfo":
            info = json.loads(json.dumps(self.info))
            if any("sombra-" in a for a in argumentos):
                # El sombreado entero: una banda de 8 bits del mismo tamaño que el modelo.
                info["bands"] = [{"band": 1, "type": self.tipo_del_sombreado}]
                if self.tamano_del_sombreado is not None:
                    info["size"] = list(self.tamano_del_sombreado)
            if "-approx_stats" in argumentos:
                info["bands"][0]["minimum"] = self.minimo
                info["bands"][0]["maximum"] = self.maximo
            return motor.Resultado(salida=json.dumps(info), errores="")
        if nombre == "gdallocationinfo":
            if entrada is not None:  # un perfil: una respuesta por pregunta, por stdin
                preguntas = entrada.splitlines()
                if self.cotas_del_perfil is not None:
                    respuestas = list(self.cotas_del_perfil)
                else:
                    respuestas = [str(100 + i) for i in range(len(preguntas))]
                return motor.Resultado(salida="\n".join(respuestas) + "\n", errores="")
            return motor.Resultado(salida="\n".join(self.valores) + "\n", errores="")
        if nombre == "gdaldem":
            if self.escribir and argumentos[0] == "hillshade":
                Path(argumentos[2]).write_bytes(b"II*\x00sombreado")
            elif self.escribir and argumentos[0] == "color-relief":
                Path(argumentos[3]).write_bytes(
                    self.contenido if self.contenido is not None else png_de(self.lado_de_salida)
                )
            return motor.Resultado(salida="", errores="")
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


#: El DEM sintético: un plano inclinado más una gaussiana, con un cuadrado de «sin dato».
#: `cota_conocida` es **la fórmula** que lo creó: lo que debe valer cada celda, sin leer el archivo.
SIN_DATO_DEL_DEM = -9999.0
HUECO_DEL_DEM = (60, 70, 20, 30)  # columnas [60, 70) y filas [20, 30)


def cota_conocida(columna: int, fila: int) -> float | None:
    """La cota de la celda `(columna, fila)` según la fórmula del DEM sintético (`None`: hueco)."""
    c0, c1, f0, f1 = HUECO_DEL_DEM
    if c0 <= columna < c1 and f0 <= fila < f1:
        return None
    plano = 500.0 + 0.2 * columna + 0.1 * fila
    cumbre = 80.0 * math.exp(-((columna - 140) ** 2 + (fila - 40) ** 2) / (2 * 15.0**2))
    return plano + cumbre


def crear_dem_sintetico(
    destino: Path,
    *,
    epsg: str | None = "EPSG:32719",
    unidad: str | None = "m",
    sin_dato: float | None = SIN_DATO_DEL_DEM,
) -> Path:
    """Un DEM `Float32` sintético **con GDAL de verdad** (solo para las pruebas `oraculo`).

    La unidad vertical se escribe pasando por un VRT (`gdal_translate` no tiene opción para ella).
    `unidad=None` y `sin_dato=None` son «el archivo no lo declara».
    """
    import numpy as np

    datos = np.empty((ALTO_PX, ANCHO_PX), dtype="float32")
    for fila in range(ALTO_PX):
        for columna in range(ANCHO_PX):
            cota = cota_conocida(columna, fila)
            datos[fila, columna] = SIN_DATO_DEL_DEM if cota is None else cota
    crudo = destino.with_name(destino.stem + "-crudo.tif")
    Image.fromarray(datos, mode="F").save(crudo)
    vrt = destino.with_suffix(".vrt")
    argumentos = [
        "-q",
        "-of",
        "VRT",
        "-a_ullr",
        *(repr(v) for v in (ESTE_NO_M, NORTE_NO_M, ESTE_NO_M + ANCHO_PX * PASO_M)),
        repr(NORTE_NO_M - ALTO_PX * PASO_M),
    ]
    if epsg:
        argumentos += ["-a_srs", epsg]
    if sin_dato is not None:
        argumentos += ["-a_nodata", repr(sin_dato)]
    motor.correr("gdal_translate", [*argumentos, str(crudo), str(vrt)], plazo_s=60)
    if unidad:
        texto = vrt.read_text(encoding="utf-8")
        texto = re.sub(
            r"(<VRTRasterBand[^>]*>)", rf"\1<UnitType>{unidad}</UnitType>", texto, count=1
        )
        vrt.write_text(texto, encoding="utf-8")
    motor.correr("gdal_translate", ["-q", "-of", "GTiff", str(vrt), str(destino)], plazo_s=60)
    crudo.unlink()
    vrt.unlink()
    return destino


#: Seis puntos del GeoTIFF sintético, **medidos con `gdaltransform`** (GDAL 3.12.4, 2026-10-09) de
#: EPSG:32719 a EPSG:4326 y a EPSG:3857: `(este, norte, lon, lat, x_3857, y_3857)`. Son el otro
#: lector: se copiaron de su salida, no de nuestra cuenta. Sirven al CI (sin GDAL) como valores
#: conocidos de la proyección del vuelo, y a las pruebas `oraculo` como control del propio control.
PUNTOS_DE_GDAL = (
    (
        345000.0,
        6295100.0,
        -70.6681004961076,
        -33.4723648674549,
        -7866736.96255459,
        -3958171.6572418,
    ),
    (
        345100.0,
        6295000.0,
        -70.6670419679731,
        -33.4732809301211,
        -7866619.12774166,
        -3958293.90855355,
    ),
    (
        345200.0,
        6295050.0,
        -70.6659575305621,
        -33.4728446044647,
        -7866498.40872126,
        -3958235.67942417,
    ),
    (
        345300.0,
        6294950.0,
        -70.6648989734458,
        -33.4737606496285,
        -7866380.57068211,
        -3958357.92907697,
    ),
    (
        345400.0,
        6294900.0,
        -70.6638317758094,
        -33.4742258926039,
        -7866261.77078465,
        -3958420.01798675,
    ),
    (
        345040.0,
        6295060.0,
        -70.6676770875254,
        -33.4727312935397,
        -7866689.82892681,
        -3958220.55774731,
    ),
)

#: El origen (redondeado a 100 m) que usa el `vuelo.json` sintético, como el del trabajo real.
ORIGEN_DEL_VUELO = (345000.0, 6294900.0)

CALIDADES_DEL_VUELO = ("PPK", "flotante", "simple", "")


def datos_de_vuelo_sintetico(
    *,
    epsg: int | None = 32719,
    con_trayectoria: bool = True,
    puntos_de_control: list[dict] | None = None,
    con_carpeta: bool = False,
    fotos_lonlat: list[tuple[float, float]] | None = None,
) -> dict:
    """El `vuelo.json` de un vuelo de cinco disparos, con posiciones que se conocen de antemano.

    Los disparos 1 a 4 caen en `PUNTOS_DE_GDAL[1:5]` (con sus lon/lat de GDAL), y el 5 **no tiene
    posición**. La trayectoria pasa por los cinco primeros puntos, relativa al origen. Con
    `fotos_lonlat`, los disparos caen en **esas** posiciones (lon, lat) y no en las de GDAL.
    """
    este0, norte0 = ORIGEN_DEL_VUELO
    fotos = []
    posiciones = (
        [(p[0], p[1], p[2], p[3]) for p in PUNTOS_DE_GDAL[1:5]]
        if fotos_lonlat is None
        else [(este0, norte0, lon, lat) for lon, lat in fotos_lonlat]
    )
    for n, (este, norte, lon, lat) in enumerate(posiciones, start=1):
        foto = {
            "n": n,
            "nombre": f"DJI_{n:04d}.JPG",
            "x": este - este0,
            "y": norte - norte0,
            "lat": lat,
            "lon": lon,
            "alt": 100.0 + n,
            "calidad": CALIDADES_DEL_VUELO[n - 1],
            "t_gps_s": 1000.0 + n,
            "miniatura": con_carpeta,
        }
        if con_carpeta:
            foto["archivo"] = foto["nombre"]
        fotos.append(foto)
    fotos.append({"n": 5, "nombre": "DJI_0005.JPG", "motivo": "El disparo no tiene posición."})
    trayectoria = [[e - este0, n - norte0] for e, n, *_ in PUNTOS_DE_GDAL[:5]]
    datos = {
        "version": 1,
        "sistema": {
            "epsg": epsg,
            "nombre": "WGS 84 / UTM zone 19S",
            "como": "medido",
            "geografico": "WGS84",
            "equivalentes": [],
        },
        "altura": None,
        "origen": {"este": este0, "norte": norte0},
        "trayectoria_total": len(trayectoria) if con_trayectoria else 0,
        "trayectoria": trayectoria if con_trayectoria else [],
        "fotos": fotos,
    }
    if puntos_de_control is not None:
        datos["puntos_de_control"] = puntos_de_control
    return datos


def crear_vuelo_sintetico(usuario, carpeta: Path, *, carpeta_de_fotos: Path | None = None, **datos):
    """Un trabajo «Corregir un vuelo de dron» **terminado**, de `usuario`, con su zip en `carpeta`.

    No corre la herramienta: escribe el zip que ella escribiría (el `vuelo.json` y un CSV mínimo) y
    deja la fila en la base. Los datos son los de `datos_de_vuelo_sintetico`.
    """
    import zipfile

    from django.utils import timezone

    from apps.jobs.models import HECHO, ConversionJob

    carpeta.mkdir(parents=True, exist_ok=True)
    cuerpo = datos_de_vuelo_sintetico(con_carpeta=carpeta_de_fotos is not None, **datos)
    salida = carpeta / f"vuelo{ConversionJob.objects.count() + 1}_vuelo.zip"
    with zipfile.ZipFile(salida, "w") as paquete:
        paquete.writestr("vuelo.json", json.dumps(cuerpo))
        paquete.writestr("fotos.csv", "foto,disparo\n")
    return ConversionJob.objects.create(
        owner=usuario,
        source_name="009.csv",
        target_format_code="zip",
        herramienta="vuelo_dron",
        status=HECHO,
        output_path=str(salida),
        finished_at=timezone.now(),
        options={"carpeta_de_fotos": str(carpeta_de_fotos)} if carpeta_de_fotos else {},
    )


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
