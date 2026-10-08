"""Escribir la posición corregida en una **copia** de la foto, sin recodificar los píxeles (F18.5).

Se trabaja sobre los bytes del JPEG, igual que `fotos_dron.quitar_gps`: todo lo que va desde el
marcador SOS (los datos comprimidos) pasa **byte por byte**, así que la imagen es la misma.

## Cómo se escribe sin romper lo del fabricante

No se reescribe el EXIF entero: las notas privadas del fabricante (`MakerNote`) guardan
desplazamientos absolutos y un reescrito los rompería sin avisar. En su lugar:

1. El bloque GPS que traía la foto se **pone a cero** (la posición del dron, sin corregir, no queda
   escondida en bytes huérfanos).
2. El bloque GPS nuevo se **añade al final** del bloque TIFF, y solo se apunta hacia él desde el
   IFD0. Nada de lo que ya estaba cambia de lugar.
3. Si la foto no traía puntero a GPS, el IFD0 se **copia al final** con una entrada más; sus valores
   siguen apuntando donde apuntaban.

El XMP de DJI repite la latitud, la longitud y la altura (`drone-dji:GpsLatitude`…): si se dejara,
la foto diría dos posiciones. Esos tres valores se **sustituyen en su sitio**; el resto del XMP (la
orientación de la cámara y del gimbal) no se toca.

## Lo que no hace

Ni el datum ni la altura se suponen. El datum es el que dice quien llama (el marco del sistema
elegido: WGS84, SIRGAS-Chile 2002, SIRGAS 2000) y se escribe tal cual en `GPSMapDatum`. La altura
solo se escribe si su referencia está declarada: el EXIF solo sabe de «sobre el nivel del mar» y
afirmaría algo que no se sabe. Sin altura, la `AbsoluteAltitude` del XMP del dron no se toca (se
dice en el aviso del trabajo).

Un MakerNote que guarde desplazamientos **relativos al archivo** (algunos de otras marcas) quedaría
corrido, porque el segmento crece unos 150 bytes. Con DJI se midió: no pasa. Para otras marcas no
se ha comprobado.
"""

from __future__ import annotations

import re
import struct
from fractions import Fraction

from .composicion import ComposicionInvalida
from .fotos_dron import (
    _ETIQUETA_GPS,
    _FIRMA_EXIF,
    _FIRMA_XMP,
    _poner_a_cero_gps,
    _segmentos,
)

#: Lo que cabe en un segmento JPEG (el largo son dos bytes e incluye los suyos).
MAXIMO_DEL_SEGMENTO = 65533

_BYTE, _ASCII, _LONG, _RATIONAL = 1, 2, 4, 5

#: Las etiquetas de DJI que repiten la posición. La de la longitud está mal escrita en sus propios
#: archivos (`GpsLongtitude`); se aceptan las dos formas.
_XMP = re.compile(rb'drone-dji:(GpsLatitude|GpsLongitude|GpsLongtitude|AbsoluteAltitude)="[^"]*"')


def _racional(valor: Fraction, fin: str) -> bytes:
    return struct.pack(fin + "II", valor.numerator, valor.denominator)


def _grados(valor: float, fin: str) -> bytes:
    """Grados, minutos y segundos como tres racionales; los segundos con 6 decimales."""
    valor = abs(valor)
    grados = int(valor)
    resto = (valor - grados) * 60
    minutos = int(resto)
    segundos = round((resto - minutos) * 60, 6)
    if segundos >= 60:  # el redondeo no puede dejar 60,000000 segundos
        segundos = 0.0
        minutos += 1
    if minutos >= 60:
        minutos = 0
        grados += 1
    return (
        _racional(Fraction(grados), fin)
        + _racional(Fraction(minutos), fin)
        + _racional(Fraction(segundos).limit_denominator(1_000_000), fin)
    )


def _entrada(etiqueta: int, tipo: int, cuenta: int, valor: bytes, fin: str) -> bytes:
    return struct.pack(fin + "HHI", etiqueta, tipo, cuenta) + valor.ljust(4, b"\x00")


def _bloque_gps(
    lat: float, lon: float, alt_m: float | None, datum: str, fin: str, donde: int
) -> bytes:
    """El IFD de GPS entero, para ir **a partir del desplazamiento `donde`** del bloque TIFF."""
    # Primero los valores que no caben en los cuatro bytes de la entrada; van detrás de la tabla.
    campos: list[
        tuple[int, int, int, bytes | None, bytes]
    ] = []  # etiqueta, tipo, cuenta, dato, en línea
    campos.append((0, _BYTE, 4, None, bytes([2, 3, 0, 0])))
    campos.append((1, _ASCII, 2, None, b"N\x00" if lat >= 0 else b"S\x00"))
    campos.append((2, _RATIONAL, 3, _grados(lat, fin), b""))
    campos.append((3, _ASCII, 2, None, b"E\x00" if lon >= 0 else b"W\x00"))
    campos.append((4, _RATIONAL, 3, _grados(lon, fin), b""))
    if alt_m is not None:
        campos.append((5, _BYTE, 1, None, b"\x00" if alt_m >= 0 else b"\x01"))
        campos.append(
            (6, _RATIONAL, 1, _racional(Fraction(round(abs(alt_m) * 1000), 1000), fin), b"")
        )
    marco = datum.encode("ascii", "replace") + b"\x00"
    campos.append((18, _ASCII, len(marco), marco, b""))

    tabla = 2 + 12 * len(campos) + 4
    cola = bytearray()
    entradas = bytearray()
    for etiqueta, tipo, cuenta, dato, en_linea in campos:
        if dato is None:
            entradas += _entrada(etiqueta, tipo, cuenta, en_linea, fin)
        else:
            cuando = donde + tabla + len(cola)
            entradas += _entrada(etiqueta, tipo, cuenta, struct.pack(fin + "I", cuando), fin)
            cola += dato + (b"\x00" if len(dato) % 2 else b"")
    return struct.pack(fin + "H", len(campos)) + bytes(entradas) + bytes(4) + bytes(cola)


def _tiff_nuevo(lat: float, lon: float, alt_m: float | None, datum: str) -> bytes:
    """Un bloque TIFF mínimo (solo el puntero a GPS) para una foto que no traía EXIF."""
    fin = "<"
    cabecera = b"II*\x00" + struct.pack(fin + "I", 8)
    ifd0 = (
        struct.pack(fin + "H", 1)
        + struct.pack(fin + "HHII", _ETIQUETA_GPS, _LONG, 1, 26)
        + bytes(4)
    )
    return cabecera + ifd0 + _bloque_gps(lat, lon, alt_m, datum, fin, 26)


def _poner_en_el_tiff(
    cuerpo: bytes, lat: float, lon: float, alt_m: float | None, datum: str
) -> bytes:
    cuerpo_b = bytearray(cuerpo)
    if len(cuerpo_b) < 8:
        raise ComposicionInvalida("El EXIF de la foto está cortado: no llega a su cabecera TIFF.")
    if cuerpo_b[:2] == b"II":
        fin = "<"
    elif cuerpo_b[:2] == b"MM":
        fin = ">"
    else:
        raise ComposicionInvalida("El EXIF de la foto no tiene una cabecera TIFF reconocible.")
    (ifd0,) = struct.unpack_from(fin + "I", cuerpo_b, 4)
    if ifd0 + 2 > len(cuerpo_b):
        raise ComposicionInvalida("El EXIF de la foto está cortado: no llega a su primera tabla.")
    (cuantas,) = struct.unpack_from(fin + "H", cuerpo_b, ifd0)
    fin_de_tabla = ifd0 + 2 + 12 * cuantas
    if fin_de_tabla + 4 > len(cuerpo_b):
        raise ComposicionInvalida("El EXIF de la foto está cortado: su primera tabla no cabe.")

    if len(cuerpo_b) % 2:
        cuerpo_b += b"\x00"
    nuevo_gps = len(cuerpo_b)
    cuerpo_b += _bloque_gps(lat, lon, alt_m, datum, fin, nuevo_gps)

    for k in range(cuantas):
        base = ifd0 + 2 + 12 * k
        (etiqueta,) = struct.unpack_from(fin + "H", cuerpo_b, base)
        if etiqueta == _ETIQUETA_GPS:
            struct.pack_into(fin + "HHII", cuerpo_b, base, _ETIQUETA_GPS, _LONG, 1, nuevo_gps)
            return bytes(cuerpo_b)

    # Sin puntero a GPS: el IFD0 se copia al final con la entrada nueva, en su lugar por orden.
    entradas = [bytes(cuerpo_b[ifd0 + 2 + 12 * k : ifd0 + 14 + 12 * k]) for k in range(cuantas)]
    entradas.append(struct.pack(fin + "HHII", _ETIQUETA_GPS, _LONG, 1, nuevo_gps))
    entradas.sort(key=lambda e: struct.unpack_from(fin + "H", e)[0])
    siguiente = bytes(cuerpo_b[fin_de_tabla : fin_de_tabla + 4])
    if len(cuerpo_b) % 2:
        cuerpo_b += b"\x00"
    nuevo_ifd0 = len(cuerpo_b)
    cuerpo_b += struct.pack(fin + "H", len(entradas)) + b"".join(entradas) + siguiente
    struct.pack_into(fin + "I", cuerpo_b, 4, nuevo_ifd0)
    return bytes(cuerpo_b)


def _formato(valor: float, decimales: int) -> bytes:
    return f"{valor:.{decimales}f}".encode("ascii")


def _actualizar_xmp(carga: bytes, lat: float, lon: float, alt_m: float | None) -> bytes:
    """Sustituye en el XMP de DJI la posición que repite; lo demás queda igual."""
    valores = {
        b"GpsLatitude": _formato(lat, 8),
        b"GpsLongitude": _formato(lon, 8),
        b"GpsLongtitude": _formato(lon, 8),
    }
    if alt_m is not None:
        valores[b"AbsoluteAltitude"] = _formato(alt_m, 3)

    def cambiar(m: re.Match[bytes]) -> bytes:
        valor = valores.get(m.group(1))
        return m.group(0) if valor is None else b'drone-dji:%s="%s"' % (m.group(1), valor)

    return _XMP.sub(cambiar, carga)


def poner_posicion(
    datos: bytes, lat: float, lon: float, alt_m: float | None, datum: str = "WGS-84"
) -> bytes:
    """El mismo JPEG con esta posición en su EXIF (y en el XMP de DJI si lo trae).

    `datum` es el marco de la latitud y la longitud, y **se escribe tal cual** en `GPSMapDatum`:
    quien llama dice cuál es, aquí no se supone. Sin `alt_m` no se escribe altura ninguna.
    """
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ComposicionInvalida(f"La posición {lat}, {lon} no es una latitud y longitud válidas.")
    try:
        return _poner(datos, lat, lon, alt_m, datum)
    except struct.error as fallo:  # un EXIF cortado o dañado: se dice cuál foto, no un traspié
        raise ComposicionInvalida(f"El EXIF de la foto está dañado o cortado ({fallo}).") from fallo


def _poner(datos: bytes, lat: float, lon: float, alt_m: float | None, datum: str) -> bytes:
    segmentos, resto = _segmentos(datos)

    salida = bytearray(b"\xff\xd8")
    puesto = False
    for marca, carga in segmentos:
        if marca == 0xE1 and carga.startswith(_FIRMA_EXIF) and not puesto:
            limpio = _poner_a_cero_gps(carga)
            carga = _FIRMA_EXIF + _poner_en_el_tiff(
                limpio[len(_FIRMA_EXIF) :], lat, lon, alt_m, datum
            )
            puesto = True
        elif marca == 0xE1 and carga.startswith(_FIRMA_EXIF):
            carga = _poner_a_cero_gps(carga)  # un segundo bloque EXIF: su posición tampoco queda
        elif marca == 0xE1 and carga.startswith(_FIRMA_XMP):
            carga = _actualizar_xmp(carga, lat, lon, alt_m)
        if len(carga) > MAXIMO_DEL_SEGMENTO - 2:
            raise ComposicionInvalida(
                "El EXIF de la foto, con la posición nueva, no cabe en un segmento de JPEG."
            )
        salida += bytes([0xFF, marca]) + struct.pack(">H", len(carga) + 2) + carga
    if not puesto:
        carga = _FIRMA_EXIF + _tiff_nuevo(lat, lon, alt_m, datum)
        bloque = bytes([0xFF, 0xE1]) + struct.pack(">H", len(carga) + 2) + carga
        # Tras el APP0 (JFIF) si lo hay: el estándar quiere el EXIF pegado al principio.
        if segmentos and segmentos[0][0] == 0xE0:
            corte = 2 + 4 + len(segmentos[0][1])
            salida = salida[:corte] + bloque + salida[corte:]
        else:
            salida = salida[:2] + bloque + salida[2:]
    return bytes(salida) + resto
