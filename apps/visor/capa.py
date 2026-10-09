"""Una capa del mapa: lo que GDAL dice de un GeoTIFF o un COG, y nada que se adivine.

## Lo que se **lee** y lo que se **calcula**

De `gdalinfo -json` se leen el tamaño, el sistema de referencia, la matriz de transformación, el
tipo de dato, las bandas y las vistas previas. De ahí, con PROJ (`pyproj`), se calculan las esquinas
y el centro en EPSG:4326 y la caja en EPSG:3857, que es lo que necesita el mapa. La prueba con
oráculo compara esas esquinas con `wgs84Extent` de `gdalinfo` y el centro con `gdaltransform`.

## Qué se niega a dibujar (regla 3)

- **Sin sistema de referencia**, o con uno que no ubica en la Tierra (un sistema local de obra): no
  hay forma honrada de decir dónde está. No se pinta, se dice por qué (`capa-sin-crs`) y **no se
  sugiere «el más probable»**. Quien conozca el EPSG lo declara en «Convertir».
- **Sin matriz de transformación** (`capa-sin-georreferencia`): una imagen sin georreferencia es un
  dibujo, no una capa.
- **Fuera del alcance de Web Mercator** (`capa-fuera-del-mapa`): pasa de ±85,05° de latitud o cruza
  el antimeridiano.

## Cómo se decide el rango de zoom

El máximo es el nivel cuyo píxel de mapa es **el píxel de la imagen**, más uno: acercar más allá es
inventar detalle (la imagen se ve a bloques) y el segundo nivel de sobreaumento deja ver el píxel.
El mínimo deja la capa en unos 64 píxeles de ancho: más lejos no se distingue y solo gasta teselas.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import cache, mercator, motor

registro = logging.getLogger(__name__)

#: Los archivos que GDAL no abrió, por clave (ruta + tamaño + mtime):
#: `(código, mensaje, instante)`. En memoria y acotado; vive lo que el proceso. Diez minutos: un
#: fallo de plazo o de un disco de red puede arreglarse solo, y no debe quedar para siempre.
_fallos: OrderedDict[str, tuple[str, str, float]] = OrderedDict()
MAXIMO_DE_FALLOS_RECORDADOS = 256
SEGUNDOS_QUE_SE_RECUERDA_UN_FALLO = 600

#: Metros por grado de un meridiano (o de un paralelo en el ecuador) en la esfera de Web Mercator.
METROS_POR_GRADO = mercator.RADIO_M * math.pi / 180

#: Tipos de dato que el PNG de 8 bits lleva tal cual. Cualquier otro se escala a 8 bits.
TIPO_DE_8_BITS = "Byte"

#: Más píxeles que esto sin pirámide de vistas previas y las teselas lejanas tardan: se avisa.
PIXELES_SIN_PIRAMIDE = 64_000_000

#: Puntos por lado al calcular el contorno: una arista recta en el sistema del archivo no lo es en
#: Web Mercator, y con cuatro esquinas el dibujo cortaría esquinas.
SEGMENTOS_POR_LADO = 16


@dataclass
class Capa:
    nombre: str
    ancho_px: int
    alto_px: int
    bandas: int
    tipo: str
    #: Nombre del sistema («WGS 84 / UTM zone 19S») y su EPSG si lo tiene, ambos tal como los dice
    #: el archivo; nunca uno supuesto.
    sistema: str = ""
    epsg: str = ""
    unidad: str = ""
    #: El sistema completo, tal cual lo dijo el archivo. No sale al navegador: sirve para convertir
    #: el punto del cursor a coordenadas del archivo.
    wkt: str = ""
    geotransform: list[float] = field(default_factory=list)
    #: Noroeste, noreste, sureste y suroeste **de la imagen** (no del norte verdadero: una imagen
    #: girada tiene su noroeste «arriba a la izquierda»).
    esquinas: list[list[float]] = field(default_factory=list)
    esquinas_4326: list[list[float]] = field(default_factory=list)
    centro: list[float] = field(default_factory=list)
    centro_4326: list[float] = field(default_factory=list)
    caja_3857: list[float] = field(default_factory=list)
    contorno_3857: list[list[float]] = field(default_factory=list)
    pixel_size_m: float | None = None
    zoom_minimo: int = 0
    zoom_maximo: int = 0
    sin_piramide: bool = False
    #: Para las que no son de 8 bits o tienen paleta o muchas bandas: cómo preparar la fuente.
    necesita_vrt: bool = False
    paleta: bool = False
    escala: list[float] = field(default_factory=list)
    #: Si se puede dibujar. Si no, `motivo` es un código de `apps/jobs/motivos.py`.
    dibujable: bool = True
    motivo: str = ""
    detalle: str = ""

    def a_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def de_dict(cls, datos: dict) -> Capa:
        conocidos = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in datos.items() if k in conocidos})


def _no_dibujable(base: dict, motivo: str, detalle: str) -> Capa:
    return Capa(**base, dibujable=False, motivo=motivo, detalle=detalle)


def _crs_de(info: dict):
    """El `pyproj.CRS` del archivo, o `None` si no declara uno que lo ubique en la Tierra."""
    from pyproj import CRS
    from pyproj.exceptions import CRSError

    wkt = ((info.get("coordinateSystem") or {}).get("wkt") or "").strip()
    if not wkt:
        return None
    try:
        crs = CRS.from_wkt(wkt)
    except CRSError:
        return None
    # Un sistema local de obra (`LOCAL_CS`, ingeniería) tiene metros pero no sabe dónde está.
    if not (crs.is_geographic or crs.is_projected):
        return None
    return crs


def _epsg_de(crs) -> str:
    """El EPSG **si el archivo lo trae**. Con confianza baja no se afirma."""
    from pyproj.exceptions import CRSError

    try:
        autoridad = crs.to_authority(min_confidence=100)
    except CRSError:  # sin EPSG no es un error: se dice solo el nombre
        return ""
    if autoridad and autoridad[0] == "EPSG":
        return str(autoridad[1])
    return ""


def desde_gdalinfo(info: dict, nombre: str) -> Capa:
    """La capa a partir del JSON de `gdalinfo -json` (y, si no es de 8 bits, de `-approx_stats`)."""
    ancho, alto = (info.get("size") or [0, 0])[:2]
    bandas = info.get("bands") or []
    tipo = bandas[0].get("type", "") if bandas else ""
    base = {
        "nombre": nombre,
        "ancho_px": int(ancho),
        "alto_px": int(alto),
        "bandas": len(bandas),
        "tipo": tipo,
    }
    if not ancho or not alto or not bandas:
        return _no_dibujable(base, "origen-no-legible", "GDAL no encontró bandas en el archivo.")

    crs = _crs_de(info)
    if crs is None:
        return _no_dibujable(
            base,
            "capa-sin-crs",
            "El archivo no declara un sistema de referencia que lo ubique en la Tierra.",
        )
    geotransform = info.get("geoTransform")
    if not geotransform or len(geotransform) != 6:
        return _no_dibujable(
            base, "capa-sin-georreferencia", "El archivo no trae su matriz de transformación."
        )
    gt = [float(v) for v in geotransform]

    from pyproj import Transformer

    a_grados = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    a_mercator = Transformer.from_crs(crs, "EPSG:3857", always_xy=True)

    def en_su_sistema(col: float, fila: float) -> tuple[float, float]:
        return (gt[0] + col * gt[1] + fila * gt[2], gt[3] + col * gt[4] + fila * gt[5])

    esquinas = [
        en_su_sistema(0, 0),
        en_su_sistema(ancho, 0),
        en_su_sistema(ancho, alto),
        en_su_sistema(0, alto),
    ]
    centro = en_su_sistema(ancho / 2, alto / 2)
    esquinas_4326 = [a_grados.transform(x, y) for x, y in esquinas]
    centro_4326 = a_grados.transform(*centro)

    todos = [*esquinas_4326, centro_4326]
    if not all(math.isfinite(v) for punto in todos for v in punto):
        return _no_dibujable(
            base, "capa-fuera-del-mapa", "Las coordenadas del archivo no se pueden llevar a grados."
        )
    lons = [p[0] for p in esquinas_4326]
    lats = [p[1] for p in esquinas_4326]
    if max(lons) - min(lons) > 180 or any(abs(v) > mercator.LATITUD_MAXIMA for v in lats):
        return _no_dibujable(
            base,
            "capa-fuera-del-mapa",
            "La capa pasa de los ±85,05° de latitud o cruza el antimeridiano, y el mapa no llega.",
        )

    # El contorno, con varios puntos por lado, en Web Mercator.
    vueltas = (
        ((0, 0), (ancho, 0)),
        ((ancho, 0), (ancho, alto)),
        ((ancho, alto), (0, alto)),
        ((0, alto), (0, 0)),
    )
    contorno: list[list[float]] = []
    for (c0, f0), (c1, f1) in vueltas:
        for i in range(SEGMENTOS_POR_LADO):
            t = i / SEGMENTOS_POR_LADO
            x, y = en_su_sistema(c0 + (c1 - c0) * t, f0 + (f1 - f0) * t)
            contorno.append(list(a_mercator.transform(x, y)))
    if not all(math.isfinite(v) for punto in contorno for v in punto):
        return _no_dibujable(
            base, "capa-fuera-del-mapa", "El contorno de la capa no cabe en Web Mercator."
        )
    xs = [p[0] for p in contorno]
    ys = [p[1] for p in contorno]
    caja = [min(xs), min(ys), max(xs), max(ys)]

    # Píxel: metros reales (para decirlo) y metros de Mercator (para elegir el zoom).
    unidad = crs.axis_info[0].unit_name if crs.axis_info else ""
    lat_centro = centro_4326[1]
    ladox = math.hypot(gt[1], gt[4])
    if crs.is_geographic:
        pixel_m = ladox * METROS_POR_GRADO * math.cos(math.radians(lat_centro))
        resolucion_mercator = ladox * METROS_POR_GRADO
    else:
        factor = crs.axis_info[0].unit_conversion_factor or 1.0
        pixel_m = ladox * factor
        resolucion_mercator = pixel_m / max(math.cos(math.radians(lat_centro)), 1e-6)

    z_nativo = math.log2(mercator.RESOLUCION_NIVEL_0_M / max(resolucion_mercator, 1e-9))
    zoom_maximo = min(mercator.ZOOM_MAXIMO, max(0, math.ceil(z_nativo) + 1))
    lado_m = max(caja[2] - caja[0], caja[3] - caja[1], 1e-6)
    z_cabe = math.log2(2 * mercator.ORIGEN_M / lado_m)  # a este nivel la capa mide 256 px
    zoom_minimo = min(max(0, math.floor(z_cabe) - 2), zoom_maximo)

    primera = bandas[0]
    paleta = (primera.get("colorInterpretation") or "").lower() == "palette"
    necesita_vrt = tipo != TIPO_DE_8_BITS or paleta or len(bandas) > 4
    sin_piramide = not primera.get("overviews") and ancho * alto > PIXELES_SIN_PIRAMIDE

    return Capa(
        **base,
        sistema=crs.name,
        epsg=_epsg_de(crs),
        unidad=unidad,
        wkt=((info.get("coordinateSystem") or {}).get("wkt") or ""),
        geotransform=gt,
        esquinas=[list(p) for p in esquinas],
        esquinas_4326=[list(p) for p in esquinas_4326],
        centro=list(centro),
        centro_4326=list(centro_4326),
        caja_3857=caja,
        contorno_3857=contorno,
        pixel_size_m=pixel_m,
        zoom_minimo=zoom_minimo,
        zoom_maximo=zoom_maximo,
        sin_piramide=sin_piramide,
        necesita_vrt=necesita_vrt,
        paleta=paleta,
    )


def _extremos(info_con_estadisticas: dict) -> list[float]:
    """`[mínimo, máximo]` aproximados de la primera banda, o `[]` si GDAL no los da."""
    bandas = info_con_estadisticas.get("bands") or []
    if not bandas:
        return []
    minimo, maximo = bandas[0].get("minimum"), bandas[0].get("maximum")
    if minimo is None or maximo is None or maximo <= minimo:
        return []
    return [float(minimo), float(maximo)]


def leer(ruta: Path) -> Capa:
    """Pregunta a GDAL por el archivo. **Solo lectura**: sin PAM no deja un `.aux.xml` al lado."""
    try:
        crudo = motor.correr("gdalinfo", ["-json", str(ruta)], plazo_s=motor.PLAZO_INFO_S).salida
        info = json.loads(crudo)
    except motor.ErrorDeGdal as fallo:
        raise motor.ErrorDeGdal(
            f"GDAL no pudo abrir {ruta.name} como imagen: {fallo}", "origen-no-legible"
        ) from fallo
    except json.JSONDecodeError as fallo:
        raise motor.ErrorDeGdal(
            f"GDAL no devolvió una ficha legible de {ruta.name}.", "origen-no-legible"
        ) from fallo

    capa = desde_gdalinfo(info, ruta.name)
    if capa.dibujable and capa.necesita_vrt and capa.tipo != TIPO_DE_8_BITS and not capa.paleta:
        # No es de 8 bits: se necesitan el mínimo y el máximo para escalarla a 8. Aproximados
        # (`-approx_stats` lee una muestra), porque los exactos en una imagen grande tardan minutos.
        try:
            crudo = motor.correr(
                "gdalinfo", ["-json", "-approx_stats", str(ruta)], plazo_s=motor.PLAZO_INFO_S
            ).salida
            capa.escala = _extremos(json.loads(crudo))
        except (motor.ErrorDeGdal, json.JSONDecodeError):
            capa.escala = []
        if not capa.escala:
            capa.dibujable = False
            capa.motivo = "origen-no-legible"
            capa.detalle = "No se pudo medir el rango de valores para pasarla a 8 bits."
    return capa


def con_cache(ruta: Path, clave: str) -> Capa:
    """La capa, de la caché si ya se leyó. La ficha vive junto a las teselas de ese archivo."""
    ficha = cache.carpeta_de(clave) / "capa.json"
    guardada = cache.leer(ficha)
    if guardada is not None:
        try:
            return Capa.de_dict(json.loads(guardada))
        except (json.JSONDecodeError, TypeError):
            registro.info("La ficha guardada de %s no se lee; se rehace.", ruta.name)
    recordado = _fallos.get(clave)
    if (
        recordado is not None
        and time.monotonic() - recordado[2] < SEGUNDOS_QUE_SE_RECUERDA_UN_FALLO
    ):
        raise motor.ErrorDeGdal(recordado[1], recordado[0])
    try:
        capa = leer(ruta)
    except motor.ErrorDeGdal as fallo:
        # Sin esto, cada tesela que pide el navegador volvería a lanzar `gdalinfo` (hasta 120 s)
        # sobre un archivo que ya se sabe que no abre. La clave lleva ruta, tamaño y mtime: si el
        # archivo cambia, se vuelve a intentar.
        _fallos[clave] = (fallo.codigo, str(fallo), time.monotonic())
        while len(_fallos) > MAXIMO_DE_FALLOS_RECORDADOS:
            _fallos.popitem(last=False)
        raise
    _fallos.pop(clave, None)
    cache.escribir(ficha, json.dumps(capa.a_dict()).encode("utf-8"))
    return capa
