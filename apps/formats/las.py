"""Lector de cabecera LAS, LAZ y COPC, sin PDAL.

Gemelo de `tiff.py`, y por las mismas razones: es barato, funciona sin la herramienta
externa, y **distingue lo que la herramienta no distingue**. `pdal info` dice `readers.las`
tanto para un LAZ corriente como para un COPC, y para AeroBim eso es la diferencia entre
poder abrir la nube y no poder.

## Lo que sí es distinto de un TIFF

**El sistema de referencia de un LAS vive en dos sitios según la versión**, y ninguno es
obvio:

- LAS 1.0 a 1.3 lo guardan en VLR con las **mismas geoclaves de GeoTIFF** — literalmente el
  registro 34735 que ya sabe leer `tiff.py`. Por eso ese parser se reutiliza aquí en vez de
  escribirse otra vez.
- LAS 1.4 lo guarda como WKT en el VLR 2112, y avisa poniendo el bit 4 de `global_encoding`.

Un archivo puede traer los dos, o ninguno. Y **una nube sin CRS no se puede cruzar con
nada**: el dato se pierde para siempre si nadie lo apunta al entregarla.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

FIRMA = b"LASF"

#: Donde empieza el bloque de VLR: justo detrás de la cabecera, cuyo tamaño ella misma
#: declara. No es una constante porque cambia entre versiones (227, 235, 375).
_POS_TAMANO_CABECERA = 94

#: El bit de `global_encoding` que dice «mi CRS está en WKT, no en geoclaves».
BIT_WKT = 0b1_0000

#: Los VLR que interesan.
VLR_GEOCLAVES = 34735
VLR_GEO_ASCII = 34737
VLR_WKT = 2112
#: El VLR que convierte un LAZ en un COPC. Va **el primero**, justo tras la cabecera.
VLR_COPC = 1
USUARIO_COPC = b"copc"
USUARIO_PROYECCION = b"LASF_Projection"

#: Formatos de punto que admite COPC. Son los que llevan tiempo GPS y clase extendida.
FORMATOS_COPC = frozenset({6, 7, 8})


class NoEsLas(Exception):
    """El archivo no empieza como un LAS."""


@dataclass(frozen=True)
class CabeceraLas:
    """Lo que se sabe de una nube leyendo solo su cabecera y sus VLR."""

    version: tuple[int, int]
    puntos: int
    formato_de_punto: int
    #: `True` si los datos van comprimidos. Se detecta por el bit alto del formato.
    comprimido: bool
    es_copc: bool
    #: (min_x, min_y, min_z) y (max_x, max_y, max_z), ya en unidades del terreno.
    minimo: tuple[float, float, float]
    maximo: tuple[float, float, float]
    escala: tuple[float, float, float]
    desplazamiento: tuple[float, float, float]
    epsg: int | None
    wkt: str
    software: str
    #: Cuántos VLR trae. Útil para saber si hay metadatos que se van a perder al convertir.
    vlrs: int

    @property
    def extension_m(self) -> tuple[float, float, float]:
        return tuple(self.maximo[i] - self.minimo[i] for i in range(3))

    @property
    def densidad_por_m2(self) -> float | None:
        """Puntos por metro cuadrado. `None` si la extensión es degenerada."""
        ancho, alto, _ = self.extension_m
        area = ancho * alto
        return self.puntos / area if area > 0 else None

    @property
    def separacion_media_m(self) -> float | None:
        """La distancia típica entre puntos vecinos.

        Es lo que de verdad se mira para decidir un diezmado: «un punto cada 5 cm» se
        entiende, «cuatrocientos puntos por metro cuadrado» hay que traducirlo.
        """
        densidad = self.densidad_por_m2
        return (1 / densidad) ** 0.5 if densidad else None

    @property
    def bytes_sin_comprimir_estimados(self) -> int:
        return self.puntos * _TAMANO_DE_PUNTO.get(self.formato_de_punto, 34)

    @property
    def precision_suficiente_para_float32(self) -> bool:
        """`False` cuando pasar estas coordenadas a `float32` pierde precisión visible.

        Es el hallazgo caro de AeroBim: **en el norte UTM de Chile, `float32` pierde unos
        200 mm**. Un `float32` tiene 24 bits de mantisa, así que sobre un valor de 7,3
        millones el escalón es de unos 0,5 m. Hay que restar el desplazamiento de cabecera
        antes de convertir, y este indicador es lo que permite avisarlo antes.
        """
        mayor = max(abs(self.minimo[1]), abs(self.maximo[1]), abs(self.minimo[0]))
        if mayor == 0:
            return True
        # Escalón de un float32 en esa magnitud, contra el escalón declarado del archivo.
        import math

        escalon = 2 ** (math.floor(math.log2(mayor)) - 23)
        return escalon <= min(self.escala[0], self.escala[1])


#: Bytes por punto de cada formato del estándar. Sirve para estimar sin leer los datos.
_TAMANO_DE_PUNTO = {0: 20, 1: 28, 2: 26, 3: 34, 4: 57, 5: 63, 6: 30, 7: 36, 8: 38, 9: 59, 10: 67}


def leer_cabecera(ruta: Path) -> CabeceraLas:
    """Lee la cabecera y los VLR. No toca un solo punto."""
    with open(ruta, "rb") as archivo:
        cabecera = archivo.read(375)
        if len(cabecera) < 227 or not cabecera.startswith(FIRMA):
            raise NoEsLas("No empieza con LASF.")

        version = (cabecera[24], cabecera[25])
        # **Son dos campos distintos y no son intercambiables.** En 26-57 va el
        # «identificador de sistema» -- el equipo o el escaner -- y en 58-89 el «software
        # generador», que es lo que de verdad se quiere saber: quien escribio este archivo.
        # Muchos programas rellenan los dos, y por eso confundirlos pasa desapercibido hasta
        # que aparece uno que solo rellena el segundo.
        generador = cabecera[58:90].split(b"\x00")[0].decode("latin-1", "replace").strip()
        sistema = cabecera[26:58].split(b"\x00")[0].decode("latin-1", "replace").strip()
        software = generador or sistema
        codificacion = struct.unpack("<H", cabecera[6:8])[0]
        tamano_cabecera = struct.unpack("<H", cabecera[_POS_TAMANO_CABECERA:96])[0]
        desplazamiento_datos = struct.unpack("<I", cabecera[96:100])[0]
        numero_vlrs = struct.unpack("<I", cabecera[100:104])[0]

        # El bit alto del identificador de formato marca la compresión LAZ. Los seis bits
        # bajos son el formato de verdad; leerlo sin la máscara da 134 en vez de 6.
        crudo_formato = cabecera[104]
        comprimido = bool(crudo_formato & 0x80)
        formato_de_punto = crudo_formato & 0x3F

        puntos_legado = struct.unpack("<I", cabecera[107:111])[0]

        escala = struct.unpack("<3d", cabecera[131:155])
        desplazamiento = struct.unpack("<3d", cabecera[155:179])
        # El orden en la cabecera es max_x, min_x, max_y, min_y, max_z, min_z. Alternado, y
        # leerlo como dos ternas seguidas es el error clásico.
        limites = struct.unpack("<6d", cabecera[179:227])
        maximo = (limites[0], limites[2], limites[4])
        minimo = (limites[1], limites[3], limites[5])

        puntos = puntos_legado
        if version >= (1, 4) and len(cabecera) >= 255:
            # LAS 1.4 lleva la cuenta real en 64 bits; la de 32 queda a cero cuando no cabe.
            puntos_1_4 = struct.unpack("<Q", cabecera[247:255])[0]
            if puntos_1_4:
                puntos = puntos_1_4

        vlrs = _leer_vlrs(archivo, tamano_cabecera, numero_vlrs, desplazamiento_datos)

    epsg, wkt = _crs_de_vlrs(vlrs, prefiere_wkt=bool(codificacion & BIT_WKT))

    return CabeceraLas(
        version=version,
        puntos=puntos,
        formato_de_punto=formato_de_punto,
        comprimido=comprimido,
        es_copc=_es_copc(vlrs, formato_de_punto, version),
        minimo=minimo,
        maximo=maximo,
        escala=escala,
        desplazamiento=desplazamiento,
        epsg=epsg,
        wkt=wkt,
        software=software,
        vlrs=len(vlrs),
    )


@dataclass(frozen=True)
class Vlr:
    usuario: bytes
    registro: int
    datos: bytes
    #: Orden en el archivo. COPC exige que el suyo sea el primero.
    indice: int


def _leer_vlrs(archivo, tamano_cabecera: int, cuantos: int, tope: int) -> list[Vlr]:
    """Los VLR, hasta donde empiezan los puntos.

    Se acota por `tope` y por un máximo de VLR a propósito: un archivo corrupto puede
    declarar cuarenta mil, y esto corre al soltar un archivo en el navegador.
    """
    encontrados: list[Vlr] = []
    posicion = tamano_cabecera
    for indice in range(min(cuantos, 256)):
        if tope and posicion + 54 > tope:
            break
        archivo.seek(posicion)
        crudo = archivo.read(54)
        if len(crudo) < 54:
            break
        usuario = crudo[2:18].split(b"\x00")[0]
        registro, longitud = struct.unpack("<HH", crudo[18:22])
        if longitud > 4_000_000:
            break
        encontrados.append(Vlr(usuario, registro, archivo.read(longitud), indice))
        posicion += 54 + longitud
    return encontrados


def _es_copc(vlrs: list[Vlr], formato_de_punto: int, version: tuple[int, int]) -> bool:
    """COPC exige tres cosas a la vez, y las tres se comprueban.

    Un LAZ con un VLR llamado `copc` pero en formato de punto 3 **no es** un COPC: la
    especificación fija LAS 1.4 y formato 6, 7 u 8. Aceptarlo haría que AeroBim intentara
    leer un octree que no está.
    """
    if version < (1, 4) or formato_de_punto not in FORMATOS_COPC:
        return False
    return any(v.usuario == USUARIO_COPC and v.registro == VLR_COPC and v.indice == 0 for v in vlrs)


def _crs_de_vlrs(vlrs: list[Vlr], *, prefiere_wkt: bool) -> tuple[int | None, str]:
    """El CRS, de donde esté.

    Cuando el archivo trae los dos y su `global_encoding` dice WKT, gana el WKT: es lo que
    el escritor declaró como autoritativo, y las geoclaves suelen ser un residuo de una
    conversión anterior.
    """
    wkt = ""
    geoclaves: tuple[int, ...] = ()

    for vlr in vlrs:
        if vlr.registro == VLR_WKT:
            wkt = vlr.datos.split(b"\x00")[0].decode("utf-8", "replace")
        elif vlr.registro == VLR_GEOCLAVES and vlr.usuario == USUARIO_PROYECCION:
            cuantos = len(vlr.datos) // 2
            geoclaves = struct.unpack(f"<{cuantos}H", vlr.datos[: cuantos * 2])

    if wkt and (prefiere_wkt or not geoclaves):
        return _epsg_de_wkt(wkt), wkt

    if geoclaves:
        # El mismo parser que las geoclaves de un GeoTIFF: es literalmente el mismo formato.
        from .tiff import _epsg_de_geoclaves

        epsg = _epsg_de_geoclaves(geoclaves)
        if epsg:
            return epsg, wkt

    return (_epsg_de_wkt(wkt) if wkt else None), wkt


def _epsg_de_wkt(wkt: str) -> int | None:
    from .crs import desde_wkt

    resuelto = desde_wkt(wkt)
    if resuelto.conocido and resuelto.autoridad == "EPSG":
        return int(resuelto.codigo)
    return None
