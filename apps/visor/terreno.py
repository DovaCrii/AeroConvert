"""Terreno en el visor (F19.4): un DEM como sombreado o color por cota, y su perfil.

GDAL se ejecuta aparte, igual que en el resto del visor (`motor.correr`: lista de argumentos, plazo,
sin `shell=True`). Aquí no hay `osgeo`.

## Los tres modos de ver un DEM

- **`gris`**: la imagen escalada a 8 bits de siempre (`teselas.py`). No usa `gdaldem`.
- **`sombra`**: `gdaldem hillshade` de **todo el modelo** (las pendientes no se sacan de una tesela
  sin sus vecinas) a un GeoTIFF de 8 bits en la caché, y de ahí `gdalwarp` corta las teselas. Es
  una vez por juego de parámetros (azimut, altura del sol, exageración vertical y escala), y cada
  juego tiene **su propia clave**: cambiar el sol no sirve teselas del sol anterior.
- **`cota`**: por tesela, `gdalwarp` a `Float32` (con un «sin dato» propio) y `gdaldem color-relief`
  con la rampa que dice la capa. El color se calcula **después** de reproyectar el valor, no antes:
  mezclar colores en el remuestreo inventaría tonos que no son ninguna cota.

## Lo que se verifica (regla 1) y lo que se deja intacto (regla 5)

El sombreado entero se comprueba con `gdalinfo` (mismo tamaño, una banda de 8 bits) antes de
renombrarlo; cada tesela, abriéndola con Pillow. Todo va a `<destino>.parcial-<id>` y se
renombra con `os.replace()`. El original solo se lee; sin PAM no queda un `.aux.xml` a su lado.

## El perfil

Dos puntos con su longitud y su latitud (EPSG:4326, declarado: nunca un par suelto). Se reparte la
**geodésica del elipsoide WGS84** (`pyproj.Geod`) en `n` muestras a distancias iguales, y esa
distancia es geodésica y no la de la pantalla (una recta de Web Mercator no es el camino más corto).
Cada muestra cae en una celda del modelo; el valor es **el de esa celda, sin interpolar**. Lo que
cae fuera del modelo o en «sin dato» queda como **hueco** (`None`), jamás como cero ni interpolado.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import cache, dem, mercator, motor, punto, teselas
from .capa import Capa

MODOS = ("gris", "sombra", "cota")

AZIMUT_POR_OMISION_DEG = 315
ALTURA_POR_OMISION_DEG = 45
EXAGERACION_POR_OMISION = 1.0

AZIMUT_MAXIMO_DEG = 360  # [0, 360)
ALTURA_MINIMA_DEG = 1
ALTURA_MAXIMA_DEG = 90
EXAGERACION_MINIMA = 0.1
EXAGERACION_MAXIMA = 20.0

MUESTRAS_POR_OMISION = 101
MUESTRAS_MINIMAS = 2
MUESTRAS_MAXIMAS = 1000

#: Una sola construcción del sombreado a la vez en el proceso: seis teselas pedidas de golpe no son
#: seis `gdaldem` sobre el mismo modelo. Entre procesos de gunicorn no se coordinan (cada uno haría
#: el suyo y gana el último, idéntico): es trabajo repetido, no un archivo roto.
_cerrojo_del_sombreado = threading.Lock()


class ParametrosNoValidos(ValueError):
    """Un parámetro de la petición fuera de rango. El mensaje sale a la persona."""


class CapaNoEsDem(Exception):
    """Se pidió terreno de un archivo que no es un modelo de elevación."""


@dataclass(frozen=True)
class Modo:
    nombre: str = "gris"
    azimut_deg: int = AZIMUT_POR_OMISION_DEG
    altura_deg: int = ALTURA_POR_OMISION_DEG
    exageracion_z: float = EXAGERACION_POR_OMISION
    #: Ocho cifras hexadecimales de **todo lo que cambia lo que sale**; entra en el nombre del
    #: archivo y en el `ETag`.
    huella: str = ""

    @property
    def es_terreno(self) -> bool:
        return self.nombre != "gris"

    @property
    def sufijo(self) -> str:
        """`""` para la imagen en grises; `sombra-1a2b3c4d` o `cota-1a2b3c4d` para el terreno."""
        return f"{self.nombre}-{self.huella}" if self.es_terreno else ""


def _numero(consulta: Mapping, nombre: str, defecto: float) -> float:
    crudo = (consulta.get(nombre) or "").strip().replace(",", ".")
    if not crudo:
        return defecto
    try:
        valor = float(crudo)
    except ValueError as fallo:
        raise ParametrosNoValidos(f"«{nombre}» no es un número.") from fallo
    if not math.isfinite(valor):
        raise ParametrosNoValidos(f"«{nombre}» no es un número.")
    return valor


def modo_de(consulta: Mapping, capa: Capa) -> Modo:
    """El modo que pide la petición, con sus parámetros **comprobados** (no se recortan).

    `gris` ignora los parámetros del sol. Cualquier otro necesita que la capa sea un DEM.
    """
    nombre = (consulta.get("modo") or "gris").strip()
    if nombre not in MODOS:
        raise ParametrosNoValidos("El modo del mapa no existe: use gris, sombra o cota.")
    if nombre == "gris":
        return Modo()
    if not capa.es_dem:
        raise CapaNoEsDem
    if nombre == "cota":
        if not capa.rampa:
            raise ParametrosNoValidos("No se midió el rango de cotas, no hay con qué colorear.")
        huella = hashlib.sha256(dem.texto_de_rampa(capa.rampa).encode()).hexdigest()[:8]
        return Modo("cota", huella=huella)

    azimut = _numero(consulta, "az", AZIMUT_POR_OMISION_DEG)
    altura = _numero(consulta, "alt", ALTURA_POR_OMISION_DEG)
    exageracion = _numero(consulta, "zf", EXAGERACION_POR_OMISION)
    if not 0 <= azimut < AZIMUT_MAXIMO_DEG:
        raise ParametrosNoValidos("El azimut del sol va de 0° a menos de 360°.")
    if not ALTURA_MINIMA_DEG <= altura <= ALTURA_MAXIMA_DEG:
        raise ParametrosNoValidos("La altura del sol va de 1° a 90°.")
    if not EXAGERACION_MINIMA <= exageracion <= EXAGERACION_MAXIMA:
        raise ParametrosNoValidos("La exageración vertical va de 0,1 a 20.")
    az, alt, zf = round(azimut) % AZIMUT_MAXIMO_DEG, round(altura), round(exageracion, 1)
    clave = f"sombra|{az}|{alt}|{zf:g}|{capa.escala_sombreado!r}"
    return Modo("sombra", az, alt, zf, hashlib.sha256(clave.encode()).hexdigest()[:8])


# ---------------------------------------------------------------------------------------------
# Teselas de terreno
# ---------------------------------------------------------------------------------------------


def _verificar_sombreado(parcial: Path, capa: Capa) -> None:
    """El sombreado entero se **lee** con `gdalinfo` antes de darlo por bueno (regla 1)."""
    try:
        if not parcial.is_file() or parcial.stat().st_size == 0:
            raise motor.ErrorDeGdal("GDAL no dejó el sombreado.", "sin-salida")
        info = json.loads(
            motor.correr("gdalinfo", ["-json", str(parcial)], plazo_s=motor.PLAZO_INFO_S).salida
        )
    except (OSError, json.JSONDecodeError) as fallo:
        raise motor.ErrorDeGdal(
            f"El sombreado que dejó GDAL no se lee: {fallo}", "salida-invalida"
        ) from fallo
    bandas = info.get("bands") or []
    ok = (
        info.get("size") == [capa.ancho_px, capa.alto_px]
        and len(bandas) == 1
        and bandas[0].get("type") == "Byte"
    )
    if not ok:
        raise motor.ErrorDeGdal(
            "El sombreado que dejó GDAL no tiene el tamaño o la forma del modelo.",
            "salida-invalida",
        )


def fuente_de_sombra(ruta: Path, capa: Capa, clave: str, modo: Modo) -> Path:
    """El sombreado de todo el modelo, de la caché o recién calculado. El original no se toca."""
    destino = cache.carpeta_de(clave) / f"sombra-{modo.huella}.tif"
    if teselas._hay(destino):
        cache.tocar(destino)
        return destino
    with _cerrojo_del_sombreado:
        if teselas._hay(destino):  # otro hilo la hizo mientras se esperaba
            cache.tocar(destino)
            return destino
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = cache.nombre_de_parcial(destino)
        try:
            motor.correr(
                "gdaldem",
                [
                    "hillshade",
                    str(ruta),
                    str(parcial),
                    "-q",
                    "-of",
                    "GTiff",
                    "-b",
                    "1",
                    "-compute_edges",
                    "-z",
                    repr(modo.exageracion_z),
                    "-s",
                    repr(capa.escala_sombreado),
                    "-az",
                    str(modo.azimut_deg),
                    "-alt",
                    str(modo.altura_deg),
                    # **Solo DEFLATE, sin `TILED=YES`**: el oráculo lo vio (GDAL 3.12.4,
                    # 2026-10-09): con las dos opciones juntas `gdaldem hillshade` dejaba 24
                    # celdas distintas junto a un hueco de «sin dato» (media 185,831 contra
                    # 185,919 sin ellas). Por franjas y comprimido da lo mismo que sin opciones.
                    "-co",
                    "COMPRESS=DEFLATE",
                ],
                plazo_s=motor.PLAZO_SOMBREADO_S,
            )
            _verificar_sombreado(parcial, capa)
            tamano = parcial.stat().st_size
            cache.reemplazar(parcial, destino)
        finally:
            parcial.unlink(missing_ok=True)
    cache.anotar_escritura(tamano)
    return destino


def _tabla_de_colores(capa: Capa, clave: str, modo: Modo) -> Path:
    """El archivo de colores de `gdaldem color-relief`, en la caché y escrito de golpe."""
    tabla = cache.carpeta_de(clave) / f"cota-{modo.huella}.txt"
    if not teselas._hay(tabla):
        cache.escribir(tabla, dem.texto_de_rampa(capa.rampa).encode("ascii"))
    return tabla


def _cortar_cota(
    ruta: Path, capa: Capa, clave: str, modo: Modo, caja, destino: Path, parcial: Path
):
    """Una tesela de color por cota: valores reproyectados primero, colores después."""
    tabla = _tabla_de_colores(capa, clave, modo)
    flotante = cache.nombre_de_parcial(destino)
    try:
        motor.correr(
            "gdalwarp",
            [
                "-q",
                "-overwrite",
                "-of",
                "GTiff",
                "-t_srs",
                "EPSG:3857",
                "-te",
                *(repr(v) for v in caja),
                "-ts",
                str(teselas.LADO_PX),
                str(teselas.LADO_PX),
                "-r",
                teselas.REMUESTREO,
                "-ot",
                "Float32",
                "-dstnodata",
                dem.SIN_DATO_DE_LA_TESELA,
                str(ruta),
                str(flotante),
            ],
            plazo_s=motor.PLAZO_TESELA_S,
        )
        motor.correr(
            "gdaldem",
            [
                "color-relief",
                str(flotante),
                str(tabla),
                str(parcial),
                "-q",
                "-alpha",
                "-of",
                "PNG",
            ],
            plazo_s=motor.PLAZO_TESELA_S,
        )
    finally:
        flotante.unlink(missing_ok=True)


def tesela(ruta: Path, capa: Capa, clave: str, modo: Modo, z: int, x: int, y: int) -> bytes:
    """El PNG de la tesela `z/x/y` de un modo de terreno, de la caché o recién hecho."""
    caja = mercator.caja_de_tesela(z, x, y)
    if not mercator.se_cruzan(caja, tuple(capa.caja_3857)):
        return teselas.tesela_vacia()

    destino = cache.carpeta_de(clave) / f"{modo.sufijo}-{z}-{x}-{y}.png"
    guardada = cache.leer(destino)
    if guardada is not None:
        return guardada

    with teselas._cupo:
        guardada = cache.leer(destino)
        if guardada is not None:
            return guardada
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = cache.nombre_de_parcial(destino)
        try:
            if modo.nombre == "sombra":
                fuente = fuente_de_sombra(ruta, capa, clave, modo)
                motor.correr(
                    "gdalwarp",
                    teselas.argumentos_de_corte(fuente, parcial, caja),
                    plazo_s=motor.PLAZO_TESELA_S,
                )
            else:
                _cortar_cota(ruta, capa, clave, modo, caja, destino, parcial)
            teselas.verificar_png(parcial)
            contenido = parcial.read_bytes()
            cache.reemplazar(parcial, destino)
        finally:
            parcial.unlink(missing_ok=True)
    cache.anotar_escritura(len(contenido))
    return contenido


# ---------------------------------------------------------------------------------------------
# El perfil entre dos puntos
# ---------------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _elipsoide():
    from pyproj import Geod

    return Geod(ellps="WGS84")


@dataclass(frozen=True)
class Muestra:
    indice: int
    #: Distancia geodésica (WGS84) desde el primer punto, en metros.
    distancia_m: float
    lon: float
    lat: float
    #: En el sistema del archivo, o `None` si no se pudo llevar hasta allá.
    x: float | None
    y: float | None
    dentro: bool
    #: El valor de la celda en la unidad vertical del archivo, o `None`: **hueco** (fuera del modelo
    #: o «sin dato»). Nunca interpolado.
    cota: float | None


@dataclass(frozen=True)
class Perfil:
    muestras: tuple[Muestra, ...]
    longitud_m: float
    unidad_vertical: str
    referencia_vertical: str

    @property
    def con_cota(self) -> list[float]:
        return [m.cota for m in self.muestras if m.cota is not None]

    @property
    def fuera(self) -> int:
        return sum(1 for m in self.muestras if not m.dentro)

    @property
    def sin_dato(self) -> int:
        return sum(1 for m in self.muestras if m.dentro and m.cota is None)


def extremos_de(consulta: Mapping) -> tuple[float, float, float, float]:
    """`(lon1, lat1, lon2, lat2)` en EPSG:4326, comprobados. Sin valores por omisión."""
    valores = []
    for nombre, limite in (("lon1", 180), ("lat1", 90), ("lon2", 180), ("lat2", 90)):
        crudo = (consulta.get(nombre) or "").strip().replace(",", ".")
        try:
            valor = float(crudo)
        except ValueError as fallo:
            raise ParametrosNoValidos(
                "Faltan los dos puntos del perfil (longitud y latitud de cada uno)."
            ) from fallo
        if not (math.isfinite(valor) and -limite <= valor <= limite):
            raise ParametrosNoValidos("Longitud o latitud fuera de rango.")
        valores.append(valor)
    return valores[0], valores[1], valores[2], valores[3]


def muestras_de_de(consulta: Mapping) -> int:
    crudo = (consulta.get("n") or "").strip()
    if not crudo:
        return MUESTRAS_POR_OMISION
    try:
        n = int(crudo)
    except ValueError as fallo:
        raise ParametrosNoValidos("El número de muestras debe ser un entero.") from fallo
    if not MUESTRAS_MINIMAS <= n <= MUESTRAS_MAXIMAS:
        raise ParametrosNoValidos(
            f"El perfil lleva de {MUESTRAS_MINIMAS} a {MUESTRAS_MAXIMAS} muestras."
        )
    return n


def linea_geodesica(
    lon1: float, lat1: float, lon2: float, lat2: float, n: int
) -> tuple[list[tuple[float, float, float]], float]:
    """`([(distancia_m, lon, lat), …], longitud_m)`: `n` puntos a distancias iguales sobre la
    geodésica WGS84. El primero y el último son **los extremos exactos**."""
    if n < MUESTRAS_MINIMAS:
        raise ParametrosNoValidos("Un perfil lleva al menos dos muestras.")
    azimut, _, longitud = _elipsoide().inv(lon1, lat1, lon2, lat2)
    if longitud <= 0:
        raise ParametrosNoValidos("Los dos puntos del perfil son el mismo: marque dos distintos.")
    puntos = []
    for i in range(n):
        distancia = longitud * i / (n - 1)
        if i == 0:
            lon, lat = lon1, lat1
        elif i == n - 1:
            lon, lat = lon2, lat2
        else:
            lon, lat, _ = _elipsoide().fwd(lon1, lat1, azimut, distancia)
        puntos.append((distancia, lon, lat))
    return puntos, longitud


def perfil(ruta: Path, capa: Capa, extremos: tuple[float, float, float, float], n: int) -> Perfil:
    """El perfil de un DEM entre dos puntos: una sola llamada a `gdallocationinfo` por perfil."""
    if not capa.es_dem:
        raise CapaNoEsDem
    puntos, longitud = linea_geodesica(*extremos, n)
    localizados = [(d, punto.localizar(capa, lon, lat)) for d, lon, lat in puntos]

    # Solo se le pregunta a GDAL por lo que cae dentro; la columna y la fila son enteras, así que
    # cada pregunta tiene **exactamente una** respuesta y el recuento se puede comprobar.
    dentro = [p for _, p in localizados if p.dentro]
    valores: list[float | None] = []
    if dentro:
        entrada = "".join(f"{math.floor(p.columna)} {math.floor(p.fila)}\n" for p in dentro)
        salida = motor.correr(
            "gdallocationinfo",
            ["-valonly", "-b", "1", str(ruta)],
            plazo_s=motor.PLAZO_PERFIL_S,
            entrada=entrada,
        ).salida
        lineas = salida.splitlines()
        if len(lineas) != len(dentro):
            raise motor.ErrorDeGdal(
                f"GDAL contestó {len(lineas)} valores a {len(dentro)} preguntas.", "salida-invalida"
            )
        for linea in lineas:
            try:
                valor = float(linea.strip())
            except ValueError:
                valor = math.nan
            hueco = dem.es_sin_dato(valor, sin_dato=capa.nodata, es_nan=capa.nodata_es_nan)
            valores.append(None if hueco else valor)

    cotas = iter(valores)
    muestras = []
    for i, (distancia, p) in enumerate(localizados):
        muestras.append(
            Muestra(
                indice=i,
                distancia_m=distancia,
                lon=p.lon,
                lat=p.lat,
                x=p.x if math.isfinite(p.x) else None,
                y=p.y if math.isfinite(p.y) else None,
                dentro=p.dentro,
                cota=next(cotas) if p.dentro else None,
            )
        )
    return Perfil(tuple(muestras), longitud, capa.unidad_vertical, capa.referencia_vertical)


def a_dict(resultado: Perfil) -> dict:
    """El perfil como lo recibe el navegador (JSON sin `NaN`)."""
    cotas = resultado.con_cota
    return {
        "n": len(resultado.muestras),
        "longitud_m": round(resultado.longitud_m, 3),
        "unidad_vertical": resultado.unidad_vertical,
        "referencia_vertical": resultado.referencia_vertical,
        "minimo": min(cotas) if cotas else None,
        "maximo": max(cotas) if cotas else None,
        "fuera": resultado.fuera,
        "sin_dato": resultado.sin_dato,
        "muestras": [
            {
                "i": m.indice,
                "d": round(m.distancia_m, 3),
                "lon": round(m.lon, 8),
                "lat": round(m.lat, 8),
                "x": None if m.x is None else round(m.x, 3),
                "y": None if m.y is None else round(m.y, 3),
                "dentro": m.dentro,
                "cota": m.cota,
            }
            for m in resultado.muestras
        ],
    }


NO_DECLARADA = "no declarada"

COLUMNAS_DEL_CSV = (
    "muestra",
    "distancia_m",
    "longitud",
    "latitud",
    "x_archivo",
    "y_archivo",
    "cota",
    "unidad_vertical",
    "referencia_vertical",
)


def csv_del_perfil(resultado: Perfil) -> str:
    """El perfil en CSV (UTF-8, coma, punto decimal). **Un hueco es una celda vacía**, no un cero.

    La unidad y la referencia van en cada fila, y valen `no declarada` si el archivo no las trae:
    el CSV se lee solo, sin la pantalla al lado. Esos dos textos vienen del archivo y ya pasaron
    por `dem.texto_seguro`.
    """
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\r\n")
    escritor.writerow(COLUMNAS_DEL_CSV)
    unidad = resultado.unidad_vertical or NO_DECLARADA
    referencia = resultado.referencia_vertical or NO_DECLARADA

    def cifra(valor: float | None, decimales: int) -> str:
        return "" if valor is None else f"{valor:.{decimales}f}"

    for m in resultado.muestras:
        escritor.writerow(
            [
                m.indice,
                cifra(m.distancia_m, 3),
                cifra(m.lon, 8),
                cifra(m.lat, 8),
                cifra(m.x, 3),
                cifra(m.y, 3),
                cifra(m.cota, 4),
                unidad,
                referencia,
            ]
        )
    return salida.getvalue()
