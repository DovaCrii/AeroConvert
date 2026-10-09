"""Fotos de dron: **quitar la posición a propósito**, sacar dónde se tomó cada una y renombrar.

Un vuelo son cientos de JPEG que llevan dentro dónde y cuándo se tomaron. Antes de entregarlas a
un tercero hay que decidir si esa posición sale, y para el equipo conviene tener las posiciones en
un KMZ o un GeoJSON y las fotos con un nombre que ordene por hora.

## Cómo se quita el GPS (y por qué no se recodifica)

Se trabaja **sobre los bytes del JPEG**: los píxeles no se vuelven a comprimir, así que la foto
sale idéntica salvo lo que se pidió quitar. El bloque GPS del EXIF se **pone a cero en su sitio**
(sus entradas y sus valores) y queda como un bloque vacío válido; no se reescribe el EXIF entero,
porque las notas privadas del fabricante guardan desplazamientos que un reescrito rompería sin
avisar. También se quita el **XMP**, que en los DJI repite la latitud, la longitud y la altura.

Lo que **no** se toca: las notas privadas del fabricante. La pantalla lo dice.

Si el GPS se **conserva**, la foto pasa byte por byte (solo cambia el nombre, si se pidió).

## Qué no se hace en silencio

Una foto sin posición no entra en el KMZ y **se cuenta** aparte. Una foto sin fecha no se renombra
por fecha: es un error con su nombre, no un nombre inventado. Todo o nada: si una falla, no sale
un zip a medias con nombres que parecen completos.
"""

from __future__ import annotations

import html
import json
import struct
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from apps.documents.composicion import ComposicionInvalida

GPS = {
    "conservar": "Conservar la posición de cada foto",
    "quitar": "Quitar la posición (EXIF GPS y XMP)",
}

NOMBRES = {
    "igual": "Dejar los nombres como están",
    "fecha": "Por fecha y hora: 20260930_101502.jpg",
    "vuelo": "Por orden de toma: vuelo_0001.jpg",
}

POSICIONES = {
    "": "No sacar las posiciones",
    "geojson": "GeoJSON (QGIS, web)",
    "kmz": "KMZ (Google Earth)",
}

MAXIMO_FOTOS = 500

EXTENSIONES = frozenset({".jpg", ".jpeg"})

#: Bytes por valor de cada tipo TIFF: BYTE, ASCII, SHORT, LONG, RATIONAL, SBYTE, UNDEFINED,
#: SSHORT, SLONG, SRATIONAL, FLOAT, DOUBLE.
_TAMANO_TIPO = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}

_ETIQUETA_GPS = 0x8825
_ETIQUETA_EXIF = 0x8769
_FIRMA_EXIF = b"Exif\x00\x00"
_FIRMA_XMP = b"http://ns.adobe.com/xap/1.0/\x00"


@dataclass(frozen=True)
class Foto:
    nombre: str
    lat: float | None
    lon: float | None
    alt_m: float | None
    fecha: datetime | None

    @property
    def tiene_posicion(self) -> bool:
        return self.lat is not None and self.lon is not None


@dataclass(frozen=True)
class Salida:
    entrada: str
    salida: str
    tiene_posicion: bool


@dataclass(frozen=True)
class Resultado:
    fotos: list[Salida]
    posiciones: str  # nombre del archivo de posiciones, o vacío
    sin_posicion: int


def motivo_si_no_se_lee(nombre: str) -> str:
    if Path(nombre).suffix.lower() in EXTENSIONES:
        return ""
    return f"{nombre} no es un JPG: aquí se limpian las fotos de dron en JPG."


# --- Lectura (con Pillow: otro lector que el que escribe los bytes) ---------------------------


def _grados(valor, referencia) -> float | None:
    try:
        grados, minutos, segundos = (float(x) for x in valor)
    except (TypeError, ValueError):
        return None
    resultado = grados + minutos / 60 + segundos / 3600
    return -resultado if str(referencia).upper() in ("S", "W") else resultado


def _fecha(texto) -> datetime | None:
    try:
        return datetime.strptime(str(texto).strip().strip("\x00"), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def leer(ruta: Path) -> Foto:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(ruta) as imagen:
            exif = imagen.getexif()
            gps = exif.get_ifd(_ETIQUETA_GPS)
            del_exif = exif.get_ifd(_ETIQUETA_EXIF)
            principal = dict(exif)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as fallo:
        raise ComposicionInvalida(f"{ruta.name} no se pudo abrir como imagen: {fallo}") from fallo

    lat = _grados(gps.get(2), gps.get(1)) if gps.get(2) is not None else None
    lon = _grados(gps.get(4), gps.get(3)) if gps.get(4) is not None else None
    alt = None
    if gps.get(6) is not None:
        try:
            alt = float(gps[6])
            if gps.get(5) in (1, b"\x01"):
                alt = -alt
        except (TypeError, ValueError):
            alt = None
    fecha = _fecha(del_exif.get(0x9003)) or _fecha(principal.get(0x0132))
    if lat is not None and lon is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
        lat = lon = None
    return Foto(ruta.name, lat, lon, alt, fecha)


# --- Quitar el GPS sobre los bytes ------------------------------------------------------------


def _segmentos(datos: bytes) -> tuple[list[tuple[int, bytes]], bytes]:
    """Los segmentos anteriores a los datos de imagen y **el resto tal cual** (desde SOS)."""
    if datos[:2] != b"\xff\xd8":
        raise ComposicionInvalida("No es un JPEG: no empieza con la marca FFD8.")
    segmentos: list[tuple[int, bytes]] = []
    i = 2
    while i + 4 <= len(datos):
        if datos[i] != 0xFF:
            raise ComposicionInvalida("El JPEG está dañado: falta una marca de segmento.")
        marca = datos[i + 1]
        if marca == 0xFF:  # relleno
            i += 1
            continue
        if marca == 0xDA:  # SOS: de aquí en adelante son los datos comprimidos
            return segmentos, datos[i:]
        (largo,) = struct.unpack(">H", datos[i + 2 : i + 4])
        if largo < 2 or i + 2 + largo > len(datos):
            raise ComposicionInvalida("El JPEG está cortado: un segmento no cabe.")
        segmentos.append((marca, datos[i + 4 : i + 2 + largo]))
        i += 2 + largo
    raise ComposicionInvalida("El JPEG está cortado: no llega a los datos de imagen.")


def _poner_a_cero_gps(exif: bytes) -> bytes:
    """El APP1 de EXIF con el bloque GPS vaciado **en su sitio** (mismos desplazamientos)."""
    cuerpo = bytearray(exif[len(_FIRMA_EXIF) :])
    if cuerpo[:2] == b"II":
        fin = "<"
    elif cuerpo[:2] == b"MM":
        fin = ">"
    else:
        return exif  # sin cabecera TIFF reconocible: no hay GPS que se pueda localizar
    (ifd0,) = struct.unpack_from(fin + "I", cuerpo, 4)
    if ifd0 + 2 > len(cuerpo):
        return exif
    (cuantas,) = struct.unpack_from(fin + "H", cuerpo, ifd0)
    for k in range(cuantas):
        base = ifd0 + 2 + 12 * k
        if base + 12 > len(cuerpo):
            break
        etiqueta, _tipo, _n, valor = struct.unpack_from(fin + "HHII", cuerpo, base)
        if etiqueta != _ETIQUETA_GPS:
            continue
        if valor + 2 > len(cuerpo):
            break
        (n_gps,) = struct.unpack_from(fin + "H", cuerpo, valor)
        for j in range(n_gps):
            entrada = valor + 2 + 12 * j
            if entrada + 12 > len(cuerpo):
                break
            _e, tipo, cuenta, donde = struct.unpack_from(fin + "HHII", cuerpo, entrada)
            largo = _TAMANO_TIPO.get(tipo, 1) * cuenta
            if largo > 4 and donde + largo <= len(cuerpo):
                cuerpo[donde : donde + largo] = bytes(largo)
            cuerpo[entrada : entrada + 12] = bytes(12)
        struct.pack_into(fin + "H", cuerpo, valor, 0)  # un bloque GPS vacío, pero válido
        break
    return _FIRMA_EXIF + bytes(cuerpo)


def quitar_gps(datos: bytes) -> bytes:
    """El mismo JPEG sin su posición: EXIF GPS a cero y sin XMP. Los píxeles no se tocan."""
    segmentos, resto = _segmentos(datos)
    salida = bytearray(b"\xff\xd8")
    for marca, carga in segmentos:
        if marca == 0xE1 and carga.startswith(_FIRMA_XMP):
            continue
        if marca == 0xE1 and carga.startswith(_FIRMA_EXIF):
            carga = _poner_a_cero_gps(carga)
        salida += bytes([0xFF, marca]) + struct.pack(">H", len(carga) + 2) + carga
    return bytes(salida) + resto


# --- Nombres y posiciones ---------------------------------------------------------------------


def _libre(base: str, extension: str, usados: set[str]) -> str:
    nombre = f"{base}{extension}"
    n = 2
    while nombre.lower() in usados:
        nombre = f"{base}_{n}{extension}"
        n += 1
    usados.add(nombre.lower())
    return nombre


def _nombres_nuevos(fotos: list[Foto], origenes: list[Path], como: str) -> list[str]:
    usados: set[str] = set()
    if como == "igual":
        return [_libre(r.stem, r.suffix.lower(), usados) for r in origenes]
    if como == "fecha":
        sin_fecha = [f.nombre for f in fotos if f.fecha is None]
        if sin_fecha:
            raise ComposicionInvalida(
                f"{sin_fecha[0]} no trae fecha de toma: no se puede renombrar por fecha."
                + (f" (y {len(sin_fecha) - 1} más)" if len(sin_fecha) > 1 else "")
            )
        return [
            _libre(f.fecha.strftime("%Y%m%d_%H%M%S"), ".jpg", usados)  # type: ignore[union-attr]
            for f in fotos
        ]
    orden = sorted(
        range(len(fotos)),
        key=lambda k: (fotos[k].fecha or datetime.max, fotos[k].nombre.lower()),
    )
    nuevos = [""] * len(fotos)
    for posicion, k in enumerate(orden, start=1):
        nuevos[k] = _libre(f"vuelo_{posicion:04d}", ".jpg", usados)
    return nuevos


def a_geojson(fotos: list[tuple[str, Foto]]) -> str:
    rasgos = []
    for nombre, f in fotos:
        coordenadas = [round(f.lon, 8), round(f.lat, 8)]  # type: ignore[arg-type]
        if f.alt_m is not None:
            coordenadas.append(round(f.alt_m, 3))
        rasgos.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coordenadas},
                "properties": {
                    "foto": nombre,
                    "fecha": f.fecha.isoformat() if f.fecha else None,
                    "altura_m": f.alt_m,
                },
            }
        )
    return json.dumps({"type": "FeatureCollection", "features": rasgos}, ensure_ascii=False)


def a_kml(fotos: list[tuple[str, Foto]]) -> str:
    marcas = []
    for nombre, f in fotos:
        alto = f.alt_m if f.alt_m is not None else 0
        cuando = f"<TimeStamp><when>{f.fecha.isoformat()}</when></TimeStamp>" if f.fecha else ""
        marcas.append(
            f"<Placemark><name>{html.escape(nombre)}</name>{cuando}<Point>"
            f"<altitudeMode>absolute</altitudeMode>"
            f"<coordinates>{f.lon:.8f},{f.lat:.8f},{alto:.3f}</coordinates></Point></Placemark>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Fotos del vuelo</name>'
        + "".join(marcas)
        + "</Document></kml>\n"
    )


def _escribir_kmz(kml: str, destino: Path) -> None:
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as paquete:
        paquete.writestr("doc.kml", kml)


def procesar(
    origenes: list[Path],
    carpeta: Path,
    *,
    gps: str = "conservar",
    nombres: str = "igual",
    posiciones: str = "",
    progreso: Callable[[float], None] | None = None,
) -> Resultado:
    """Escribe en `carpeta` una foto por entrada y, si se pidió, el archivo de posiciones."""
    if gps not in GPS:
        raise ComposicionInvalida(f"«{gps}» no es una opción de posición de las que se ofrecen.")
    if nombres not in NOMBRES:
        raise ComposicionInvalida(f"«{nombres}» no es una forma de nombrar de las que se ofrecen.")
    if posiciones not in POSICIONES:
        raise ComposicionInvalida(f"«{posiciones}» no es un formato de posiciones de los que hay.")
    if not origenes:
        raise ComposicionInvalida("No indicó ninguna foto.")
    if len(origenes) > MAXIMO_FOTOS:
        raise ComposicionInvalida(f"El máximo son {MAXIMO_FOTOS} fotos por vez.")

    rutas = [Path(r) for r in origenes]
    fotos = [leer(r) for r in rutas]
    nuevos = _nombres_nuevos(fotos, rutas, nombres)
    con_posicion = [(n, f) for n, f in zip(nuevos, fotos, strict=True) if f.tiene_posicion]
    if posiciones and not con_posicion:
        raise ComposicionInvalida(
            "Ninguna de las fotos trae posición: no hay nada que poner en el archivo de posiciones."
        )

    escritas: list[Path] = []
    informe: list[Salida] = []
    try:
        for indice, (ruta, nuevo, foto) in enumerate(zip(rutas, nuevos, fotos, strict=True), 1):
            datos = ruta.read_bytes()
            if gps == "quitar":
                datos = quitar_gps(datos)
            destino = carpeta / nuevo
            destino.write_bytes(datos)
            escritas.append(destino)
            informe.append(Salida(ruta.name, nuevo, foto.tiene_posicion))
            if progreso is not None:
                progreso(indice / len(rutas))
        archivo = ""
        if posiciones == "geojson":
            archivo = "posiciones.geojson"
            (carpeta / archivo).write_text(a_geojson(con_posicion), encoding="utf-8")
        elif posiciones == "kmz":
            archivo = "posiciones.kmz"
            _escribir_kmz(a_kml(con_posicion), carpeta / archivo)
    except Exception:
        for hecha in escritas:
            hecha.unlink(missing_ok=True)
        raise
    return Resultado(informe, archivo, len(fotos) - len(con_posicion))
