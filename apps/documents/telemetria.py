"""La telemetría de un video de dron: el `.SRT` de DJI, a una traza GPX o KML.

Los DJI graban junto a cada video un `.SRT` que, además de los subtítulos, lleva **una línea por
fotograma con la posición del dron**. Es la forma más barata de saber por dónde voló: no hace
falta el registro de vuelo, solo ese archivo. Aquí se lee y se entrega como traza, que es lo que
abre QGIS, Google Earth o AeroLink.

## Los dos formatos que se leen

- **Nuevo** (Mini, Air 2S, Mavic 3…): `[latitude: -33.1] [longitude: -70.1] [rel_alt: 36.8
  abs_alt: 569.3]`.
- **Antiguo** (Phantom, Mavic Pro/2): `GPS(-70.1,-33.1,36)` — **longitud primero** —, con la altura
  del barómetro a un lado.

Un fotograma sin posición (el dron aún no fijó satélites: coordenadas `0, 0`) **se descarta y se
cuenta**, no se dibuja en el golfo de Guinea.

## La hora

La línea de fecha del SRT es la **hora de la cámara, sin zona**. Escribirla en un GPX como si fuera
UTC pondría la traza horas corrida de sus fotos, así que **solo se escribe si la persona dice
cuántas horas de diferencia con UTC tiene la cámara**; sin eso, la traza va sin hora y se entiende
como lo que es: un recorrido, no una sincronización.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

from .composicion import ComposicionInvalida

FORMATOS = {
    "gpx": "GPX — para QGIS y la mayoría de los programas",
    "kml": "KML — para Google Earth",
}

#: Un fotograma por cada N segundos; 0 es todos. Un video de una hora a 30 cuadros por segundo son
#: unos cien mil puntos: valen para medir, y para mirar sobran.
INTERVALOS_S = {0: "Todos los fotogramas", 1: "Uno por segundo", 5: "Uno cada 5 segundos"}

#: El SRT de un video largo pesa unos pocos megas; más que esto no es un SRT.
MAXIMO_BYTES = 200 * 1024 * 1024

_TIEMPO = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})")
_FECHA = re.compile(r"(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)(?:\.(\d+))?")
_NUMERO = r"(-?\d+(?:\.\d+)?)"
_LAT = re.compile(rf"\[latitude\s*:\s*{_NUMERO}\]", re.IGNORECASE)
_LON = re.compile(rf"\[longitude\s*:\s*{_NUMERO}\]", re.IGNORECASE)
_ABS = re.compile(rf"abs_alt\s*:\s*{_NUMERO}", re.IGNORECASE)
_REL = re.compile(rf"rel_alt\s*:\s*{_NUMERO}", re.IGNORECASE)
_GPS_ANTIGUO = re.compile(rf"GPS\s*\(\s*{_NUMERO}\s*,\s*{_NUMERO}\s*(?:,\s*{_NUMERO})?\s*\)")


@dataclass(frozen=True)
class Punto:
    #: Segundos desde el inicio del video, del código de tiempo del subtítulo.
    t_s: float
    lat: float
    lon: float
    alt: float | None
    #: La hora de la cámara, sin zona; `None` si el SRT no la trae.
    camara: datetime | None


@dataclass(frozen=True)
class Lectura:
    puntos: tuple[Punto, ...]
    #: Cuántos fotogramas había en total (con o sin posición).
    entradas: int
    #: Cuántos no traían una posición utilizable.
    sin_posicion: int


def _segundos(texto: str) -> float:
    m = _TIEMPO.search(texto)
    if not m:
        return 0.0
    h, mi, s, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def _posicion(bloque: str) -> tuple[float, float, float | None] | None:
    lat, lon = _LAT.search(bloque), _LON.search(bloque)
    if lat and lon:
        alto = _ABS.search(bloque) or _REL.search(bloque)
        return float(lat.group(1)), float(lon.group(1)), float(alto.group(1)) if alto else None
    antiguo = _GPS_ANTIGUO.search(bloque)
    if antiguo:
        lon_a, lat_a, alt_a = antiguo.groups()
        return float(lat_a), float(lon_a), float(alt_a) if alt_a is not None else None
    return None


def leer(origen: str | Path) -> Lectura:
    """Los puntos del SRT, en orden. Levanta si el archivo no trae ni uno."""
    origen = Path(origen)
    if origen.stat().st_size > MAXIMO_BYTES:
        raise ComposicionInvalida(f"{origen.name} es demasiado grande para ser un SRT.")
    texto = origen.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    bloques = [b for b in re.split(r"\n\s*\n", texto) if b.strip()]

    puntos: list[Punto] = []
    sin_posicion = 0
    entradas = 0
    for bloque in bloques:
        lineas = bloque.strip().split("\n")
        codigo = next((ln for ln in lineas if "-->" in ln), None)
        if codigo is None:
            continue
        entradas += 1
        posicion = _posicion(bloque)
        if posicion is None:
            sin_posicion += 1
            continue
        lat, lon, alt = posicion
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            sin_posicion += 1
            continue
        fecha = _FECHA.search(bloque)
        camara = None
        if fecha:
            a, mes, d, h, mi, s, frac = fecha.groups()
            camara = datetime(int(a), int(mes), int(d), int(h), int(mi), int(s)) + timedelta(
                microseconds=int((frac or "0").ljust(6, "0")[:6])
            )
        puntos.append(Punto(_segundos(codigo.split("-->")[0]), lat, lon, alt, camara))

    if not entradas:
        raise ComposicionInvalida(
            f"{origen.name} no parece un SRT: no tiene subtítulos con tiempo."
        )
    if not puntos:
        raise ComposicionInvalida(
            f"{origen.name} no trae ninguna posición: el dron no había fijado satélites, o el "
            "SRT no es de un DJI con GPS."
        )
    return Lectura(tuple(puntos), entradas, sin_posicion)


def _adelgazar(puntos: tuple[Punto, ...], cada_s: int) -> list[Punto]:
    if cada_s <= 0:
        return list(puntos)
    elegidos: list[Punto] = []
    siguiente = -1.0
    for p in puntos:
        if p.t_s >= siguiente:
            elegidos.append(p)
            siguiente = p.t_s + cada_s
    if elegidos[-1] is not puntos[-1]:
        elegidos.append(puntos[-1])  # el último, para que la traza llegue donde terminó
    return elegidos


def _hora_utc(p: Punto, desfase_h: float | None) -> str | None:
    if desfase_h is None or p.camara is None:
        return None
    utc = p.camara - timedelta(hours=desfase_h)
    return utc.strftime("%Y-%m-%dT%H:%M:%S") + f".{utc.microsecond // 1000:03d}Z"


def a_gpx(
    lectura: Lectura, nombre: str, *, cada_s: int = 0, desfase_h: float | None = None
) -> tuple[str, int]:
    """El XML GPX y cuántos puntos lleva."""
    puntos = _adelgazar(lectura.puntos, cada_s)
    filas = []
    for p in puntos:
        extra = f"<ele>{p.alt:.3f}</ele>" if p.alt is not None else ""
        hora = _hora_utc(p, desfase_h)
        extra += f"<time>{hora}</time>" if hora else ""
        filas.append(f'<trkpt lat="{p.lat:.7f}" lon="{p.lon:.7f}">{extra}</trkpt>')
    cuerpo = "\n      ".join(filas)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="AeroConvert" xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"  <trk>\n    <name>{escape(nombre)}</name>\n    <trkseg>\n      {cuerpo}\n"
        "    </trkseg>\n  </trk>\n</gpx>\n",
        len(puntos),
    )


def a_kml(lectura: Lectura, nombre: str, *, cada_s: int = 0) -> tuple[str, int]:
    """El XML KML (una línea y dos marcas: dónde empezó y dónde acabó) y cuántos puntos lleva."""
    puntos = _adelgazar(lectura.puntos, cada_s)
    coordenadas = " ".join(
        f"{p.lon:.7f},{p.lat:.7f},{p.alt if p.alt is not None else 0:.3f}" for p in puntos
    )
    inicio, fin = puntos[0], puntos[-1]

    def marca(titulo: str, p: Punto) -> str:
        return (
            f"<Placemark><name>{titulo}</name><Point><coordinates>{p.lon:.7f},{p.lat:.7f},"
            f"{p.alt if p.alt is not None else 0:.3f}</coordinates></Point></Placemark>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"<name>{escape(nombre)}</name>"
        f"<Placemark><name>{escape(nombre)}</name><LineString><altitudeMode>absolute</altitudeMode>"
        f"<coordinates>{coordenadas}</coordinates></LineString></Placemark>"
        f"{marca('Inicio', inicio)}{marca('Final', fin)}"
        "</Document></kml>\n",
        len(puntos),
    )


def convertir(
    origen: str | Path,
    destino: str | Path,
    formato: str,
    *,
    cada_s: int = 0,
    desfase_h: float | None = None,
) -> tuple[Lectura, int]:
    """Escribe la traza. Devuelve la lectura y cuántos puntos quedaron en el archivo."""
    if formato not in FORMATOS:
        raise ComposicionInvalida(f"«{formato}» no es un formato de traza de los que se hacen.")
    if cada_s not in INTERVALOS_S:
        raise ComposicionInvalida(f"«{cada_s}» no es un intervalo de los que se ofrecen.")
    if desfase_h is not None and not -14 <= desfase_h <= 14:
        raise ComposicionInvalida("La diferencia con UTC va de −14 a +14 horas.")

    origen, destino = Path(origen), Path(destino)
    lectura = leer(origen)
    nombre = origen.stem
    if formato == "gpx":
        xml, cuantos = a_gpx(lectura, nombre, cada_s=cada_s, desfase_h=desfase_h)
    else:
        xml, cuantos = a_kml(lectura, nombre, cada_s=cada_s)
    destino.write_text(xml, encoding="utf-8")
    return lectura, cuantos
