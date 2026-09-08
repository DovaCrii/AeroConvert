"""Lector de cabecera TIFF y BigTIFF, sin GDAL.

## Por que existe si GDAL ya sabe leer TIFF

Tres razones, y la tercera es la que decide:

1. **Es barato.** Leer la cabecera son unos kilobytes y unos microsegundos. Abrir el mismo
   archivo con GDAL construye un dataset completo. La ficha del archivo aparece mientras la
   persona todavia esta soltando el raton.
2. **Funciona sin GDAL instalado**, que es lo que permite que la mitad de las pruebas del
   proyecto corran en una maquina limpia.
3. **GDAL no distingue lo que aca importa.** `gdalinfo` dice `Driver: GTiff` tanto para un
   TIFF clasico como para un BigTIFF -- son el mismo controlador. Pero **son formatos
   distintos para quien los tiene que abrir**: AutoCAD y Civil 3D leen el primero y no el
   segundo. Ese es exactamente el diagnostico que la aplicacion existe para dar, y hay que
   leer el byte de version para darlo.

## La diferencia entre los dos, en bytes

Un TIFF empieza con el orden de bytes (`II` o `MM`) y una marca de version:

    49 49 2A 00  ->  II, version 42  ->  TIFF clasico
    49 49 2B 00  ->  II, version 43  ->  BigTIFF

En el clasico, el desplazamiento al primer IFD son 4 bytes y cada entrada mide 12. En
BigTIFF los desplazamientos son de 8 bytes, la cuenta de entradas tambien, y cada entrada
mide 20. Confundirlos no da un error: da basura que parece un IFD.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

#: Marca de version del TIFF clasico.
VERSION_CLASICA = 42
#: Marca de version del BigTIFF.
VERSION_BIG = 43

# Etiquetas que nos interesan. Las demas se ignoran a proposito: esto no es una libreria
# de imagen, es un diagnostico.
#: `NewSubfileType`. Sus bits dicen que es cada directorio, y sin leerlo no se puede
#: distinguir una piramide de la banda de mascara: ambas son IFD encadenados.
TAG_TIPO_SUBARCHIVO = 254
#: Bit 0: es una version reducida de la imagen -- o sea, una piramide.
SUBARCHIVO_REDUCIDO = 0b001
#: Bit 2: es una mascara de transparencia.
SUBARCHIVO_MASCARA = 0b100

TAG_ANCHO = 256
TAG_ALTO = 257
TAG_BITS = 258
TAG_COMPRESION = 259
TAG_FOTOMETRIA = 262
TAG_MUESTRAS = 277
TAG_FILAS_POR_FRANJA = 278
TAG_PREDICTOR = 317
TAG_ANCHO_TESELA = 322
TAG_ALTO_TESELA = 323
TAG_MUESTRAS_EXTRA = 338
TAG_ESCALA_PIXEL = 33550
TAG_PUNTO_ATADURA = 33922
TAG_TRANSFORMACION = 34264
TAG_DIRECTORIO_GEOCLAVES = 34735
TAG_GEO_DOUBLE = 34736
TAG_GEO_ASCII = 34737
TAG_SOFTWARE = 305
TAG_NODATA = 42113

#: Geoclave con el codigo EPSG del sistema proyectado.
GEOCLAVE_PROYECTADO = 3072
#: Geoclave con el codigo EPSG del sistema geografico.
GEOCLAVE_GEOGRAFICO = 2048
#: Geoclave con el tipo de modelo: 1 proyectado, 2 geografico, 3 geocentrico.
GEOCLAVE_TIPO_MODELO = 1024

NOMBRES_COMPRESION = {
    1: "sin comprimir",
    2: "CCITT RLE",
    5: "LZW",
    7: "JPEG",
    8: "Deflate",
    32773: "PackBits",
    32946: "Deflate",
    34712: "JPEG 2000",
    34887: "LERC",
    50000: "ZSTD",
    50001: "WebP",
    50002: "JXL",
}

NOMBRES_FOTOMETRIA = {
    0: "blanco es cero",
    1: "negro es cero",
    2: "RGB",
    3: "paleta",
    4: "mascara",
    6: "YCbCr",
}

# Tamano en bytes de cada tipo de campo TIFF, indexado por su codigo.
TAMANO_TIPO = {
    1: 1,  # BYTE
    2: 1,  # ASCII
    3: 2,  # SHORT
    4: 4,  # LONG
    5: 8,  # RATIONAL
    6: 1,  # SBYTE
    7: 1,  # UNDEFINED
    8: 2,  # SSHORT
    9: 4,  # SLONG
    10: 8,  # SRATIONAL
    11: 4,  # FLOAT
    12: 8,  # DOUBLE
    13: 4,  # IFD
    16: 8,  # LONG8    (solo BigTIFF)
    17: 8,  # SLONG8   (solo BigTIFF)
    18: 8,  # IFD8     (solo BigTIFF)
}


class NoEsTiff(Exception):
    """El archivo no empieza como un TIFF."""


@dataclass(frozen=True)
class CabeceraTiff:
    """Lo que se puede saber de un TIFF leyendo solo su cabecera."""

    es_bigtiff: bool
    little_endian: bool
    ancho_px: int
    alto_px: int
    bandas: int
    bits_por_muestra: int
    compresion: int
    fotometria: int
    teselado: bool
    ancho_tesela: int | None
    alto_tesela: int | None
    filas_por_franja: int | None
    #: 0 = sin banda extra, 1 = alfa premultiplicado, 2 = alfa sin premultiplicar.
    muestras_extra: tuple[int, ...]
    #: (escala_x_m, escala_y_m) del `ModelPixelScale`, si lo trae.
    escala_pixel: tuple[float, float] | None
    #: Esquina superior izquierda en coordenadas del terreno.
    origen: tuple[float, float] | None
    #: Codigo EPSG leido de las geoclaves, si esta.
    epsg: int | None
    software: str
    #: Cuantos IFD hay encadenados en total, contando el principal.
    directorios: int
    #: Cuantos de ellos son reducciones de la imagen. **No es `directorios - 1`**: cuando
    #: el archivo lleva banda de mascara, sus reducciones son IFD tambien y contarlas como
    #: piramides infla la cifra al doble.
    reducciones: int = 0
    #: Cuantos son mascara de transparencia.
    mascaras: int = 0
    #: IFD mas pequenos que el principal pero **sin** declarar `NewSubfileType`. GDAL no
    #: los expone como overviews, asi que no cuentan como piramides utilizables. Se
    #: guardan para poder decirlo en la ficha en vez de callarlo.
    menores_sin_declarar: int = 0

    @property
    def nombre_compresion(self) -> str:
        return NOMBRES_COMPRESION.get(self.compresion, f"codigo {self.compresion}")

    @property
    def nombre_fotometria(self) -> str:
        return NOMBRES_FOTOMETRIA.get(self.fotometria, f"codigo {self.fotometria}")

    @property
    def tiene_alfa(self) -> bool:
        return bool(self.muestras_extra) and any(v in (1, 2) for v in self.muestras_extra)

    @property
    def megapixeles(self) -> float:
        return self.ancho_px * self.alto_px / 1_000_000

    @property
    def tiene_piramides_internas(self) -> bool:
        return self.reducciones > 0

    @property
    def bytes_sin_comprimir(self) -> int:
        return self.ancho_px * self.alto_px * self.bandas * (self.bits_por_muestra // 8)

    @property
    def gsd_cm(self) -> float | None:
        """Tamano de pixel en centimetros, si el archivo trae escala."""
        if self.escala_pixel is None:
            return None
        return abs(self.escala_pixel[0]) * 100

    @property
    def extension_terreno_m(self) -> tuple[float, float] | None:
        if self.escala_pixel is None:
            return None
        return (
            self.ancho_px * abs(self.escala_pixel[0]),
            self.alto_px * abs(self.escala_pixel[1]),
        )

    @property
    def necesitaba_bigtiff(self) -> bool:
        """`True` si el contenido justifica BigTIFF.

        El techo del TIFF clasico son 4 GB de desplazamiento. Se compara contra el tamano
        **sin comprimir** porque es lo que decide si los desplazamientos caben, y se deja
        un margen: un archivo justo en el limite es un archivo que va a fallar.
        """
        return self.bytes_sin_comprimir > 3_500_000_000


#: Tope de directorios que se recorren. Un TIFF legitimo tiene el principal y sus
#: piramides; nadie llega a 64. El tope existe porque un archivo hostil puede encadenar
#: IFD indefinidamente y esto se ejecuta al soltar un archivo en el navegador.
MAXIMO_DIRECTORIOS = 64
#: Tope de entradas por directorio, por la misma razon.
MAXIMO_ENTRADAS = 4096

FORMATOS_STRUCT = {
    1: "B",
    3: "H",
    4: "I",
    6: "b",
    7: "B",
    8: "h",
    9: "i",
    11: "f",
    12: "d",
    13: "I",
    16: "Q",
    17: "q",
    18: "Q",
}


def _valores(leer, orden: str, tipo: int, cuenta: int, crudo: bytes, desplazamiento: int):
    """Devuelve los valores de una entrada, esten en linea o apuntados.

    Cuando los valores no caben en el hueco de la entrada, el hueco lleva un
    desplazamiento a otra parte del archivo. `leer(desplazamiento, cuenta)` va a buscarlos.
    """
    tamano = TAMANO_TIPO.get(tipo)
    if tamano is None:
        return ()
    total = tamano * cuenta
    # Un `count` absurdo es un archivo corrupto o malicioso, no un dato.
    if total > 4_000_000:
        return ()
    fuente = crudo[:total] if total <= len(crudo) else leer(desplazamiento, total)
    if len(fuente) < total:
        return ()

    if tipo == 2:  # ASCII
        return (fuente.split(b"\x00")[0].decode("latin-1"),)
    formato = FORMATOS_STRUCT.get(tipo)
    if formato is None:  # RATIONAL y SRATIONAL: no los usamos
        return ()
    return struct.unpack(f"{orden}{cuenta}{formato}", fuente)


def leer_cabecera(ruta: Path) -> CabeceraTiff:
    """Lee la cabecera de un TIFF o BigTIFF.

    **Se navega el archivo con desplazamientos, no leyendo un prefijo.** La primera version
    de esto leia el primer megabyte y recorria los directorios ahi dentro; funcionaba para
    el IFD0 --las geoclaves y las escalas viven al principio-- pero contaba mal las
    piramides, porque en un TIFF grande los directorios de las reducciones estan repartidos
    por todo el archivo. Y las piramides son justo uno de los veredictos que se dan.

    Se leen unos pocos kilobytes en total: la cabecera, cada directorio y los valores que
    no caben en linea. Nunca un pixel.
    """
    with open(ruta, "rb") as archivo:
        return _leer_cabecera_de(archivo)


def _leer_cabecera_de(archivo) -> CabeceraTiff:
    def leer(desplazamiento: int, cuenta: int) -> bytes:
        if desplazamiento < 0 or cuenta <= 0:
            return b""
        try:
            archivo.seek(desplazamiento)
            return archivo.read(cuenta)
        except OSError:
            return b""

    datos = leer(0, 16)
    if len(datos) < 8:
        raise NoEsTiff("El archivo tiene menos de 8 bytes.")

    marca = datos[:2]
    if marca == b"II":
        orden = "<"
    elif marca == b"MM":
        orden = ">"
    else:
        raise NoEsTiff(f"No empieza con II ni MM, sino con {marca!r}.")

    version = struct.unpack(f"{orden}H", datos[2:4])[0]
    # Tres anchos distintos, y confundirlos es el error clasico al escribir esto:
    #   - `num_entradas`: cuantas entradas trae el IFD.       clasico 2  ·  BigTIFF 8
    #   - `cuenta_valores`: cuantos valores trae una entrada. clasico 4  ·  BigTIFF 8
    #   - `desplazamiento`: el hueco del valor y el puntero al IFD siguiente.
    #                                                          clasico 4  ·  BigTIFF 8
    # En BigTIFF los tres valen 8, asi que un error aca pasa desapercibido con BigTIFF y
    # revienta con el TIFF clasico. Por eso hay una prueba de cada variante.
    if version == VERSION_CLASICA:
        es_big = False
        desplazamiento_ifd = struct.unpack(f"{orden}I", datos[4:8])[0]
        tam_entrada = 12
        tam_num_entradas, fmt_num_entradas = 2, "H"
        tam_cuenta, fmt_cuenta = 4, "I"
        hueco, fmt_desplazamiento = 4, "I"
    elif version == VERSION_BIG:
        es_big = True
        # En BigTIFF los bytes 4-5 dicen el tamano de los desplazamientos (siempre 8) y
        # 6-7 son cero. El desplazamiento al IFD0 empieza en el byte 8.
        tamano_offset = struct.unpack(f"{orden}H", datos[4:6])[0]
        if tamano_offset != 8:
            raise NoEsTiff(f"BigTIFF con desplazamientos de {tamano_offset} bytes: no soportado.")
        desplazamiento_ifd = struct.unpack(f"{orden}Q", datos[8:16])[0]
        tam_entrada = 20
        tam_num_entradas, fmt_num_entradas = 8, "Q"
        tam_cuenta, fmt_cuenta = 8, "Q"
        hueco, fmt_desplazamiento = 8, "Q"
    else:
        raise NoEsTiff(f"Marca de version {version}: no es 42 (clasico) ni 43 (BigTIFF).")

    campos: dict[int, tuple] = {}
    directorios = 0
    reducciones = 0
    mascaras = 0
    menores = 0
    visitados: set[int] = set()

    while desplazamiento_ifd and desplazamiento_ifd not in visitados:
        if directorios >= MAXIMO_DIRECTORIOS:
            break
        visitados.add(desplazamiento_ifd)

        crudo_cuenta = leer(desplazamiento_ifd, tam_num_entradas)
        if len(crudo_cuenta) < tam_num_entradas:
            break
        cuenta_entradas = struct.unpack(f"{orden}{fmt_num_entradas}", crudo_cuenta)[0]
        if cuenta_entradas == 0 or cuenta_entradas > MAXIMO_ENTRADAS:
            break

        inicio = desplazamiento_ifd + tam_num_entradas
        bloque = leer(inicio, cuenta_entradas * tam_entrada + hueco)
        if len(bloque) < cuenta_entradas * tam_entrada + hueco:
            # El directorio esta truncado. Se cuenta como visto -- existe -- y se corta.
            directorios += 1
            break

        # Del IFD0 se leen todos los campos. De los demas, solo dos: `NewSubfileType`, que
        # dice si es piramide o mascara, y el ancho, que hace de respaldo cuando el
        # escritor no puso el primero. Leer el resto multiplicaria las lecturas por nada.
        bandera: int | None = None
        ancho_de_este: int | None = None

        for indice in range(cuenta_entradas):
            base = indice * tam_entrada
            etiqueta, tipo = struct.unpack(f"{orden}HH", bloque[base : base + 4])
            if directorios > 0 and etiqueta not in (TAG_TIPO_SUBARCHIVO, TAG_ANCHO):
                continue
            cuenta = struct.unpack(
                f"{orden}{fmt_cuenta}", bloque[base + 4 : base + 4 + tam_cuenta]
            )[0]
            hueco_valor = bloque[base + 4 + tam_cuenta : base + tam_entrada]
            desplazamiento_valor = struct.unpack(f"{orden}{fmt_desplazamiento}", hueco_valor)[0]
            valores = _valores(leer, orden, tipo, cuenta, hueco_valor, desplazamiento_valor)
            if directorios == 0:
                campos[etiqueta] = valores
            elif valores:
                if etiqueta == TAG_TIPO_SUBARCHIVO:
                    bandera = int(valores[0])
                else:
                    ancho_de_este = int(valores[0])

        if directorios > 0:
            ancho_principal = campos.get(TAG_ANCHO, (0,))[0]
            if bandera is not None and bandera & SUBARCHIVO_MASCARA:
                mascaras += 1
            elif bandera is not None and bandera & SUBARCHIVO_REDUCIDO:
                reducciones += 1
            elif ancho_de_este and ancho_principal and ancho_de_este < ancho_principal:
                # Un IFD mas estrecho que el principal y **sin** `NewSubfileType`.
                #
                # La tentacion es contarlo como piramide: es mas pequeno, tiene toda la
                # pinta. Pero se contrasto con el oraculo y no: sobre un DEM de Metashape
                # con cuatro IFD asi, `gdalinfo` reporta **cero** overviews. Sin la
                # etiqueta, GDAL no los usa -- y por tanto QGIS tampoco, ni nada que se
                # apoye en GDAL. Decir "tiene piramides" seria prometer un zoom rapido que
                # ningun programa va a dar.
                #
                # Asi que se cuentan aparte y no suman a `reducciones`. Es la diferencia
                # entre lo que el archivo contiene y lo que el software va a aprovechar, y
                # aca lo que importa es lo segundo.
                menores += 1

        directorios += 1
        fin = cuenta_entradas * tam_entrada
        desplazamiento_ifd = struct.unpack(
            f"{orden}{fmt_desplazamiento}", bloque[fin : fin + hueco]
        )[0]

    def primero(etiqueta: int, por_defecto=None):
        valores = campos.get(etiqueta)
        return valores[0] if valores else por_defecto

    ancho = primero(TAG_ANCHO)
    alto = primero(TAG_ALTO)
    if ancho is None or alto is None:
        raise NoEsTiff("El primer directorio no declara ancho y alto.")

    escala = campos.get(TAG_ESCALA_PIXEL)
    escala_pixel = (float(escala[0]), float(escala[1])) if escala and len(escala) >= 2 else None

    atadura = campos.get(TAG_PUNTO_ATADURA)
    origen = None
    if atadura and len(atadura) >= 6:
        # (i, j, k, x, y, z): el pixel (i,j) del raster esta en (x,y) del terreno.
        origen = (float(atadura[3]), float(atadura[4]))

    return CabeceraTiff(
        es_bigtiff=es_big,
        little_endian=(orden == "<"),
        ancho_px=int(ancho),
        alto_px=int(alto),
        bandas=int(primero(TAG_MUESTRAS, 1)),
        bits_por_muestra=int(primero(TAG_BITS, 8)),
        compresion=int(primero(TAG_COMPRESION, 1)),
        fotometria=int(primero(TAG_FOTOMETRIA, 1)),
        teselado=TAG_ANCHO_TESELA in campos,
        ancho_tesela=primero(TAG_ANCHO_TESELA),
        alto_tesela=primero(TAG_ALTO_TESELA),
        filas_por_franja=primero(TAG_FILAS_POR_FRANJA),
        muestras_extra=tuple(int(v) for v in campos.get(TAG_MUESTRAS_EXTRA, ())),
        escala_pixel=escala_pixel,
        origen=origen,
        epsg=_epsg_de_geoclaves(campos.get(TAG_DIRECTORIO_GEOCLAVES, ())),
        software=str(primero(TAG_SOFTWARE, "") or ""),
        directorios=directorios,
        reducciones=reducciones,
        mascaras=mascaras,
        menores_sin_declarar=menores,
    )


def _epsg_de_geoclaves(geoclaves) -> int | None:
    """Saca el codigo EPSG del `GeoKeyDirectoryTag`.

    El campo es una lista de enteros de 16 bits. Los cuatro primeros son la cabecera
    (version, revision, revision menor, numero de claves) y luego van cuatro por clave:
    identificador, donde vive el valor, cuantos, y el valor o su desplazamiento.

    Solo se leen las claves cuyo valor esta **en linea** (`ubicacion == 0`), que es donde
    viven los codigos EPSG. Las que apuntan a `GeoDoubleParams` o `GeoAsciiParams` son
    parametros de proyeccion, y para eso ya esta pyproj.
    """
    if len(geoclaves) < 4:
        return None
    numero = geoclaves[3]
    proyectado = None
    geografico = None
    for indice in range(numero):
        base = 4 + indice * 4
        if base + 3 >= len(geoclaves):
            break
        clave, ubicacion, _cuenta, valor = geoclaves[base : base + 4]
        if ubicacion != 0:
            continue
        # 32767 significa "definido por el usuario": no es un codigo EPSG.
        if valor in (0, 32767):
            continue
        if clave == GEOCLAVE_PROYECTADO:
            proyectado = int(valor)
        elif clave == GEOCLAVE_GEOGRAFICO:
            geografico = int(valor)
    # El proyectado manda: si el archivo esta en UTM, decir que esta en 4326 seria peor
    # que no decir nada.
    return proyectado or geografico
