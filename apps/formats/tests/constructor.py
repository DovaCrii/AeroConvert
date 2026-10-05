"""Construye TIFF diminutos byte a byte, para probar el lector sin GDAL.

## Por que a mano y no con una libreria

Porque la libreria y el lector se equivocarian igual. Si el fichero de prueba lo escribe
GDAL y lo lee nuestro codigo, lo unico que se comprueba es que los dos entienden lo mismo
por TIFF -- y ademas hace falta GDAL instalado, que es justo lo que el gate no puede exigir.

Escribiendolo aqui, el byte de version 43 esta puesto **a proposito y a la vista**: la
prueba de BigTIFF falla si el lector deja de mirarlo, que es exactamente el defecto que
haria que la aplicacion dejara de dar su diagnostico principal.

Los archivos salen de unos 400 bytes **diga lo que diga su cabecera**: los pixeles no se
escriben nunca. Eso es lo que permite probar el comportamiento con las dimensiones de una
ortofoto de gigabytes sin escribir una.
"""

from __future__ import annotations

import struct

#: Codigos de tipo TIFF que usa el constructor.
SHORT = 3
LONG = 4
DOUBLE = 12
LONG8 = 16

TAMANOS = {SHORT: 2, LONG: 4, DOUBLE: 8, LONG8: 8}
EMPAQUE = {SHORT: "H", LONG: "I", DOUBLE: "d", LONG8: "Q"}


#: Las geoclaves de un EPSG proyectado. La cabecera son cuatro enteros (version 1,
#: revision 1, revision menor 0, y cuantas claves vienen) y luego cuatro por clave:
#: identificador, donde vive el valor (0 = aqui mismo), cuantos, y el valor.
def geoclaves_epsg(codigo: int) -> tuple[int, ...]:
    return (
        1,
        1,
        0,
        2,  # cabecera: dos claves
        1024,
        0,
        1,
        1,  # GTModelType = 1 (proyectado)
        3072,
        0,
        1,
        codigo,  # ProjectedCSType = el EPSG
    )


class ConstructorTiff:
    """Arma un TIFF clasico o un BigTIFF con los campos que se le pidan."""

    def __init__(self, *, bigtiff: bool = False, little_endian: bool = True) -> None:
        self.bigtiff = bigtiff
        self.orden = "<" if little_endian else ">"
        self.campos: dict[int, tuple[int, tuple]] = {}

    def campo(self, etiqueta: int, tipo: int, valores) -> ConstructorTiff:
        self.campos[etiqueta] = (tipo, tuple(valores))
        return self

    def raster(
        self,
        *,
        ancho: int = 4,
        alto: int = 4,
        bandas: int = 1,
        compresion: int = 1,
        fotometria: int = 1,
        epsg: int | None = None,
        escala_m: float | None = None,
        origen: tuple[float, float] | None = None,
        alfa: bool = False,
    ) -> ConstructorTiff:
        """Los campos minimos de un raster que se pueda leer."""
        self.campo(256, SHORT, [ancho])
        self.campo(257, SHORT, [alto])
        self.campo(258, SHORT, [8] * bandas)
        self.campo(259, SHORT, [compresion])
        self.campo(262, SHORT, [fotometria])
        self.campo(277, SHORT, [bandas])
        self.campo(278, SHORT, [alto])
        if alfa:
            self.campo(338, SHORT, [2])  # alfa sin premultiplicar
        if escala_m is not None:
            self.campo(33550, DOUBLE, [escala_m, escala_m, 0.0])
        if origen is not None:
            self.campo(33922, DOUBLE, [0.0, 0.0, 0.0, origen[0], origen[1], 0.0])
        if epsg is not None:
            self.campo(34735, SHORT, geoclaves_epsg(epsg))

        # **Los pixeles NO se escriben, por muchos que declare la cabecera.**
        #
        # El lector nunca los toca: lee el IFD y sigue el `StripOffsets` solo para
        # declararlo, no para ir. Materializarlos convertia una prueba que declara las
        # dimensiones de la ortofoto real -- 14.526 x 14.443 x 4 -- en **839 MB de ceros en
        # disco**, y con varias de esas el CI se quedaba sin espacio. Paso.
        #
        # Asi el archivo mide unos 400 bytes diga lo que diga su cabecera, que es justo lo
        # que hace util a este constructor: se pueden probar las dimensiones de un archivo
        # de gigabytes sin escribir uno.
        self._pixeles = bytes(min(ancho * alto * bandas, 64))
        return self

    def bytes(self) -> bytes:
        orden = self.orden
        pixeles = getattr(self, "_pixeles", b"\x00" * 16)

        if self.bigtiff:
            cabecera = struct.pack(f"{orden}2sHHH", b"II" if orden == "<" else b"MM", 43, 8, 0)
            cabecera += struct.pack(f"{orden}Q", 16)
            inicio_ifd = 16
            tam_entrada, hueco = 20, 8
            fmt_cuenta, fmt_desp = "Q", "Q"
            cabecera_ifd = struct.pack(f"{orden}Q", len(self.campos) + 1)
        else:
            cabecera = struct.pack(f"{orden}2sHI", b"II" if orden == "<" else b"MM", 42, 8)
            inicio_ifd = 8
            tam_entrada, hueco = 12, 4
            fmt_cuenta, fmt_desp = "I", "I"
            cabecera_ifd = struct.pack(f"{orden}H", len(self.campos) + 1)

        # +1 por StripOffsets (273), que se anade al final porque su valor depende de
        # donde acabe todo lo demas.
        etiquetas = sorted([*self.campos.keys(), 273])
        tam_ifd = len(cabecera_ifd) + len(etiquetas) * tam_entrada + hueco
        inicio_valores = inicio_ifd + tam_ifd

        # Primera pasada: donde cae el valor de cada campo que no quepa en linea.
        desplazamiento = inicio_valores
        posiciones: dict[int, int] = {}
        for etiqueta in etiquetas:
            if etiqueta == 273:
                continue
            tipo, valores = self.campos[etiqueta]
            total = TAMANOS[tipo] * len(valores)
            if total > hueco:
                posiciones[etiqueta] = desplazamiento
                desplazamiento += total + (total % 2)  # los valores van a byte par

        inicio_pixeles = desplazamiento

        entradas = b""
        area_valores = bytearray()
        for etiqueta in etiquetas:
            if etiqueta == 273:
                tipo, valores = LONG, (inicio_pixeles,)
            else:
                tipo, valores = self.campos[etiqueta]
            empaquetado = struct.pack(f"{orden}{len(valores)}{EMPAQUE[tipo]}", *valores)
            entradas += struct.pack(f"{orden}HH", etiqueta, tipo)
            entradas += struct.pack(f"{orden}{fmt_cuenta}", len(valores))
            if len(empaquetado) <= hueco:
                entradas += empaquetado.ljust(hueco, b"\x00")
            else:
                posicion = posiciones[etiqueta]
                entradas += struct.pack(f"{orden}{fmt_desp}", posicion)
                relleno = posicion - inicio_valores - len(area_valores)
                area_valores += b"\x00" * relleno + empaquetado
                if len(empaquetado) % 2:
                    area_valores += b"\x00"

        sin_siguiente = struct.pack(f"{orden}{fmt_desp}", 0)
        salida = cabecera + cabecera_ifd + entradas + sin_siguiente + bytes(area_valores) + pixeles
        return salida


def geotiff_minimo(**kwargs) -> bytes:
    """Un GeoTIFF clasico de 4x4 en EPSG:32719, con escala y origen. ~400 bytes."""
    opciones = {
        "ancho": 4,
        "alto": 4,
        "bandas": 1,
        "epsg": 32719,
        "escala_m": 0.025577,
        "origen": (495003.2272575648, 7318841.801817955),
    }
    opciones.update(kwargs)
    return ConstructorTiff(bigtiff=False).raster(**opciones).bytes()


def bigtiff_minimo(**kwargs) -> bytes:
    """El mismo archivo, pero BigTIFF. La unica diferencia semantica es el byte 2."""
    opciones = {
        "ancho": 4,
        "alto": 4,
        "bandas": 1,
        "epsg": 32719,
        "escala_m": 0.025577,
        "origen": (495003.2272575648, 7318841.801817955),
    }
    opciones.update(kwargs)
    return ConstructorTiff(bigtiff=True).raster(**opciones).bytes()


# --- LAS ---------------------------------------------------------------------
#
# Mismo criterio que con el TIFF: se escribe a mano para que la prueba no dependa de PDAL y
# para que los bytes que importan -- la version, el bit de compresion, el VLR de COPC --
# esten a la vista en la prueba y no escondidos en una libreria.


def _vlr(usuario: bytes, registro: int, datos: bytes, descripcion: bytes = b"") -> bytes:
    """Un VLR: 54 bytes de cabecera y luego los datos."""
    return (
        struct.pack("<H", 0)
        + usuario.ljust(16, b"\x00")[:16]
        + struct.pack("<HH", registro, len(datos))
        + descripcion.ljust(32, b"\x00")[:32]
        + datos
    )


def vlr_geoclaves(codigo_epsg: int) -> bytes:
    """El VLR de proyeccion de un LAS 1.0-1.3: las **mismas geoclaves de GeoTIFF**."""
    claves = geoclaves_epsg(codigo_epsg)
    return _vlr(
        b"LASF_Projection", 34735, struct.pack(f"<{len(claves)}H", *claves), b"GeoTIFF keys"
    )


def vlr_wkt(wkt: str) -> bytes:
    """El VLR de un LAS 1.4: el CRS como texto."""
    return _vlr(b"LASF_Projection", 2112, wkt.encode("utf-8") + b"\x00", b"WKT")


def vlr_copc() -> bytes:
    """Los 160 bytes de informacion COPC. Su contenido no importa aqui: lo que se prueba es
    que se reconozca por estar **el primero** y con el identificador correcto."""
    return _vlr(b"copc", 1, bytes(160), b"COPC info")


def las_minimo(
    *,
    version: tuple[int, int] = (1, 2),
    puntos: int = 1000,
    formato_de_punto: int = 2,
    comprimido: bool = False,
    epsg: int | None = 32719,
    wkt: str = "",
    copc: bool = False,
    minimo: tuple[float, float, float] = (495003.24, 7318472.78, 3038.72),
    maximo: tuple[float, float, float] = (495373.63, 7318841.78, 3064.17),
    escala: tuple[float, float, float] = (0.01, 0.01, 0.01),
    desplazamiento: tuple[float, float, float] = (494000.0, 7318000.0, 3000.0),
    software: str = "AeroConvert pruebas",
) -> bytes:
    """Un LAS valido de unos 400 bytes, sin un solo punto dentro."""
    tamano_cabecera = 375 if version >= (1, 4) else 227

    vlrs = b""
    cuantos = 0
    # COPC exige ser el primero, asi que va antes que cualquier otro.
    if copc:
        vlrs += vlr_copc()
        cuantos += 1
    # Los dos pueden ir a la vez: es el caso real de un archivo que paso por una conversion
    # y arrastra las geoclaves viejas junto al WKT nuevo.
    if epsg is not None:
        vlrs += vlr_geoclaves(epsg)
        cuantos += 1
    if wkt:
        vlrs += vlr_wkt(wkt)
        cuantos += 1

    codificacion = 0b1_0000 if (wkt and version >= (1, 4)) else 0
    # El bit alto del identificador de formato es lo que marca la compresion LAZ.
    crudo_formato = formato_de_punto | (0x80 if comprimido else 0)

    cabecera = bytearray(tamano_cabecera)
    cabecera[0:4] = b"LASF"
    struct.pack_into("<H", cabecera, 6, codificacion)
    cabecera[24] = version[0]
    cabecera[25] = version[1]
    cabecera[58:90] = software.encode("latin-1").ljust(32, b"\x00")[:32]
    struct.pack_into("<H", cabecera, 94, tamano_cabecera)
    struct.pack_into("<I", cabecera, 96, tamano_cabecera + len(vlrs))
    struct.pack_into("<I", cabecera, 100, cuantos)
    cabecera[104] = crudo_formato
    struct.pack_into("<H", cabecera, 105, 26)
    # En 1.4 la cuenta de 32 bits queda a cero y manda la de 64.
    struct.pack_into("<I", cabecera, 107, 0 if version >= (1, 4) else puntos)
    struct.pack_into("<3d", cabecera, 131, *escala)
    struct.pack_into("<3d", cabecera, 155, *desplazamiento)
    # El orden es alternado: max, min, max, min, max, min. Leerlo como dos ternas es el
    # error clasico, y por eso la prueba usa valores distintos en cada eje.
    struct.pack_into(
        "<6d",
        cabecera,
        179,
        maximo[0],
        minimo[0],
        maximo[1],
        minimo[1],
        maximo[2],
        minimo[2],
    )
    if version >= (1, 4):
        struct.pack_into("<Q", cabecera, 247, puntos)

    return bytes(cabecera) + vlrs


def copc_minimo(**kwargs) -> bytes:
    """Un COPC valido: LAS 1.4, formato de punto 7, comprimido, con su VLR el primero."""
    opciones = {
        "version": (1, 4),
        "formato_de_punto": 7,
        "comprimido": True,
        "copc": True,
    }
    opciones.update(kwargs)
    return las_minimo(**opciones)


#: Un Arc/Info ASCII Grid de doce lineas. Texto plano, sin firma: sirve para probar que la
#: deteccion por extension existe y que su confianza se reporta mas baja.
ASC_MINIMO = """\
ncols 4
nrows 4
xllcorner 495003.227
yllcorner 7318841.802
cellsize 0.025577
NODATA_value -9999
3042.1 3042.2 3042.3 3042.4
3043.1 3043.2 3043.3 3043.4
3044.1 3044.2 3044.3 3044.4
3045.1 3045.2 3045.3 3045.4
"""

#: El `.prj` que escribe Metashape. Se guarda literal porque su rareza es el caso de
#: prueba: pyproj no lo identifica ni con confianza 20, y aun asi declara su EPSG.
PRJ_METASHAPE = (
    'PROJCS["WGS 84 / UTM zone 19S",GEOGCS["WGS 84",DATUM["World Geodetic System 1984 '
    'ensemble",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],'
    'TOWGS84[0,0,0,0,0,0,0],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,'
    'AUTHORITY["EPSG","8901"]],UNIT["degree",0.01745329251994328,AUTHORITY["EPSG","9102"]],'
    'AUTHORITY["EPSG","4326"]],PROJECTION["Transverse_Mercator",AUTHORITY["EPSG","9807"]],'
    'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-69],'
    'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],'
    'PARAMETER["false_northing",10000000],UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
    'AUTHORITY["EPSG","32719"]]'
)


# --- GNSS -----------------------------------------------------------------------------------


def trimble_minimo(
    *,
    modelo: str = "TRIMBLE NETR9",
    serie: str = "5303K49763",
    nivel_bzip2: int = 1,
    carpeta: str = "/Internal/VUELOS/2023/01/31",
) -> bytes:
    """Un crudo de Trimble reducido a lo que el lector mira: la cabecera y el primer bloque.

    La estructura es la que se midio en dos archivos reales (un T02 de un NetR9 y un T04 de
    un R12i): `00 00 00 0d`, 17 bytes mas hasta el offset 21, y ahi un bloque bzip2 que
    descomprime a registros con `ReceiverId`, `SystemUptime` y `filePath`. Los bytes de
    relleno no significan nada: el lector no los interpreta, y fingir que si seria inventar
    un formato que Trimble no publica.
    """
    import bz2

    texto = (
        b")\x10\xc7ReceiverId:76,"
        + modelo.encode("latin-1")
        + b","
        + serie.encode("latin-1")
        + b"\x17\x10\xc7SystemUptime:3136987\x00\x00\x00="
        + b"\x00\x00filePath:"
        + carpeta.encode("latin-1")
        + b"/GMLA202301311700A.T0"
        + b"B\x00\x00\x00TRMB\x00\x00"
    )
    return b"\x00\x00\x00\x0d" + bytes(range(17)) + bz2.compress(texto, nivel_bzip2)


def rinex_minimo(
    *,
    version: str = "3.04",
    epocas: int = 5,
    intervalo_s: float = 30.0,
    satelites: tuple[str, ...] = ("G01", "G02", "R05"),
    huecos_en: tuple[int, ...] = (),
    truncar_la_ultima: bool = False,
    con_fin_de_cabecera: bool = True,
    marcador: str = "GMLA",
    fin_de_linea: str = "\n",
) -> str:
    """Un RINEX de observacion de pocas lineas, de la version 2.11, 3.0x o 4.0x.

    `huecos_en` son los numeros de epoca (desde 0) que **faltan** a mitad del archivo: la
    epoca no se escribe, y el escaner tiene que verlo como un salto. `truncar_la_ultima`
    corta el archivo a mitad de la ultima epoca, que es lo que deja un convertidor muerto
    o un disco lleno.
    """
    from datetime import datetime, timedelta

    v2 = version.startswith("2")
    tipos = "C1C L1C D1C S1C"
    inicio = datetime(2023, 1, 31, 17, 0, 0)

    def linea(texto: str, nombre: str) -> str:
        return f"{texto:<60}{nombre}"

    cabecera = [
        linea(f"{version:>9}           OBSERVATION DATA    M", "RINEX VERSION / TYPE"),
        linea(
            "AeroConvert pruebas  sintetico            20230131 170000 UTC", "PGM / RUN BY / DATE"
        ),
        linea(marcador, "MARKER NAME"),
        linea("5303K49763           TRIMBLE NETR9       5.48", "REC # / TYPE / VERS"),
        linea("                    TRM57971.00     NONE", "ANT # / TYPE"),
        linea("  1948450.2000 -5475860.9000 -2656160.3000", "APPROX POSITION XYZ"),
        linea(f"{intervalo_s:10.3f}", "INTERVAL"),
    ]
    if v2:
        cabecera.append(linea("     4    C1    L1    D1    S1", "# / TYPES OF OBSERV"))
    else:
        cabecera.append(linea(f"G    4 {tipos}", "SYS / # / OBS TYPES"))
        cabecera.append(linea(f"R    4 {tipos}", "SYS / # / OBS TYPES"))
    cabecera.append(
        linea("  2023     1    31    17     0    0.0000000     GPS", "TIME OF FIRST OBS")
    )
    if con_fin_de_cabecera:
        cabecera.append(linea("", "END OF HEADER"))

    cuerpo: list[str] = []
    for n in range(epocas):
        if n in huecos_en:
            continue
        t = inicio + timedelta(seconds=n * intervalo_s)
        observaciones = "".join(f"{20000000.0 + k:14.3f}  " for k in range(4))
        if v2:
            cuerpo.append(
                f" {t.year % 100:02d} {t.month:2d} {t.day:2d} {t.hour:2d} {t.minute:2d}"
                f"{t.second:11.7f}  0{len(satelites):3d}{''.join(satelites[:12])}"
            )
            cuerpo.extend(observaciones for _ in satelites)
        else:
            cuerpo.append(
                f"> {t.year:4d} {t.month:02d} {t.day:02d} {t.hour:02d} {t.minute:02d}"
                f"{t.second:11.7f}  0{len(satelites):3d}"
            )
            cuerpo.extend(sat + observaciones for sat in satelites)

    if truncar_la_ultima and cuerpo:
        cuerpo = cuerpo[:-1]
    return fin_de_linea.join(cabecera + cuerpo) + fin_de_linea
