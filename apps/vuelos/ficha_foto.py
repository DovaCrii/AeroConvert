"""La ficha de una foto de dron: cámara, GNSS y dron, leídos **del archivo** (F18.8, F18.9, F18.10).

Un JPEG de DJI guarda sus datos en dos sitios, y aquí se leen los dos:

- el **EXIF** (cámara: modelo, focal, apertura, exposición, ISO, dimensiones; y el GPS en grados,
  minutos y segundos), con Pillow;
- el **XMP** (`drone-dji:…`: calidad RTK, desviaciones, posición con nueve decimales, altura,
  orientación del gimbal y del dron, velocidades), como **texto**, con una expresión regular. No se
  usa un lector de XML: el XMP viene de un archivo ajeno y un lector de XML sería una superficie
  de ataque a cambio de nada, porque lo que se necesita son atributos simples.

Se lee **solo la cabecera** del JPEG (EXIF y XMP están antes de los datos de imagen, en unos 35 kB):
un vuelo de 2 505 fotos de 10 MB no se lee entero. El archivo se abre en **solo lectura** (regla 5).

## Lo que no se supone

- **La calidad RTK sale de `RtkFlag`**, no de `GpsStatus`: en el vuelo real con que se midió
  (Matrice 3E, PPK, sin corrección en el aire) `GpsStatus` dice «RTK» en las 2 505 fotos y
  `RtkFlag` vale 16 (posición simple) en todas. Los códigos son los que publica DJI (50 fija, 34
  flotante, 16 simple, 0 sin solución); **solo el 16 se ha visto en un archivo real**. Un código
  que no está en la tabla se dice «no reconocida (código N)», y una foto sin la bandera, «no
  informada»: nunca se completa.
- **La altura se da con su origen**: `AbsoluteAltitude` del XMP si está, si no la del EXIF. Qué
  referencia tiene (elipsoidal o no) no lo dice la foto: se comprueba contra el `.MRK`
  (`vuelo_rtk.py`) y, sin él, no se afirma.
- **La orientación no se convierte.** Se informa tal como la escribe DJI (cabeceo −90° = cámara
  mirando al nadir). Los ejes de Metashape o de Pix4D tienen otra convención.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from apps.documents.composicion import ComposicionInvalida

from .fotos_dron import _FIRMA_EXIF, _FIRMA_XMP, _segmentos

#: Cuánto se lee de la cabecera antes de ampliar. Un DJI trae su EXIF y su XMP en ~35 kB.
CABECERA_INICIAL = 192 * 1024

#: Los códigos de `RtkFlag` que publica DJI. **Solo el 16 se ha visto en un archivo real.**
CALIDAD_RTK = {50: "fija", 34: "flotante", 16: "simple", 0: "sin solución"}

#: De la bandera al código de calidad de `vuelo_sync.CALIDADES` (1 fija, 2 flotante, 5 simple).
CODIGO_DE_CALIDAD = {50: 1, 34: 2, 16: 5}

_ATRIBUTO = re.compile(rb'drone-dji:(\w+)\s*=\s*"([^"]*)"')
_ELEMENTO = re.compile(rb"<drone-dji:(\w+)>([^<]*)</drone-dji:\1>")
_FECHA_XMP = re.compile(rb'xmp:CreateDate\s*=\s*"([^"]*)"')


def calidad_de_la_bandera(bandera: int | None) -> str:
    """El texto de la calidad de una posición según `RtkFlag`. No se completa lo que falta."""
    if bandera is None:
        return "no informada"
    return CALIDAD_RTK.get(bandera, f"no reconocida (código {bandera})")


@dataclass(frozen=True)
class FichaFoto:
    """Todo lo que la foto dice de sí misma. Lo que no trae queda en `None`."""

    nombre: str
    fuente: str = "foto"  # `foto` (su EXIF y su XMP) o `trimble` (el export_extended)
    # Cámara
    marca: str | None = None
    modelo: str | None = None
    focal_mm: float | None = None
    focal_35mm_mm: float | None = None
    apertura_f: float | None = None
    exposicion_s: float | None = None
    iso: int | None = None
    ancho_px: int | None = None
    alto_px: int | None = None
    fecha: str | None = None
    # GNSS
    rtk_bandera: int | None = None
    gps_estado: str | None = None
    tipo_de_altura: str | None = None
    lat: float | None = None
    lon: float | None = None
    alt_m: float | None = None
    posicion_de: str = ""  # `XMP`, `EXIF` o vacío
    rtk_desv_lat_m: float | None = None
    rtk_desv_lon_m: float | None = None
    rtk_desv_alt_m: float | None = None
    rtk_edad_dif_s: float | None = None
    datum: str | None = None
    # Dron
    gimbal_guinada_deg: float | None = None
    gimbal_cabeceo_deg: float | None = None
    gimbal_alabeo_deg: float | None = None
    dron_guinada_deg: float | None = None
    dron_cabeceo_deg: float | None = None
    dron_alabeo_deg: float | None = None
    velocidad_x_ms: float | None = None
    velocidad_y_ms: float | None = None
    velocidad_z_ms: float | None = None
    altura_relativa_m: float | None = None

    @property
    def con_posicion(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def calidad(self) -> str:
        return calidad_de_la_bandera(self.rtk_bandera)

    @property
    def con_orientacion(self) -> bool:
        return self.gimbal_guinada_deg is not None and self.gimbal_cabeceo_deg is not None


# --- Lectura del archivo ----------------------------------------------------------------------


def _numero(texto) -> float | None:
    try:
        valor = float(str(texto).strip())
    except (TypeError, ValueError):
        return None
    return valor if math.isfinite(valor) else None


def _entero(texto) -> int | None:
    valor = _numero(texto)
    return int(valor) if valor is not None and valor == int(valor) else None


def _cabecera(ruta: Path) -> list[tuple[int, bytes]]:
    """Los segmentos de la cabecera del JPEG. Lee poco, y amplía solo si no alcanzó."""
    tamano = ruta.stat().st_size
    pedido = CABECERA_INICIAL
    while True:
        with ruta.open("rb") as archivo:  # solo lectura
            datos = archivo.read(pedido)
        try:
            return _segmentos(datos)[0]
        except ComposicionInvalida:
            if len(datos) >= tamano:
                raise
            pedido *= 8


def _xmp_de_dji(segmentos: list[tuple[int, bytes]]) -> tuple[dict[str, str], str | None]:
    atributos: dict[str, str] = {}
    fecha = None
    for marca, carga in segmentos:
        if marca != 0xE1 or not carga.startswith(_FIRMA_XMP):
            continue
        for coincidencia in (*_ATRIBUTO.finditer(carga), *_ELEMENTO.finditer(carga)):
            clave = coincidencia.group(1).decode("ascii", "replace")
            atributos.setdefault(clave, coincidencia.group(2).decode("utf-8", "replace").strip())
        creada = _FECHA_XMP.search(carga)
        if creada:
            fecha = creada.group(1).decode("utf-8", "replace")
    return atributos, fecha


def _grados(valor, referencia) -> float | None:
    try:
        g, m, s = (float(x) for x in valor)
    except (TypeError, ValueError):
        return None
    resultado = g + m / 60 + s / 3600
    return -resultado if str(referencia).strip("\x00").upper() in ("S", "W") else resultado


def _exif(segmentos: list[tuple[int, bytes]]):
    from PIL import Image

    for marca, carga in segmentos:
        if marca == 0xE1 and carga.startswith(_FIRMA_EXIF):
            exif = Image.Exif()
            try:
                exif.load(carga)
            except Exception:  # noqa: BLE001 - un EXIF dañado no tumba la ficha: queda sin cámara
                return None
            return exif
    return None


def leer_ficha(ruta: Path) -> FichaFoto:
    """La ficha de una foto. Levanta `ComposicionInvalida` si no es un JPEG legible."""
    try:
        segmentos = _cabecera(Path(ruta))
    except OSError as fallo:
        raise ComposicionInvalida(f"{Path(ruta).name} no se pudo abrir: {fallo}") from fallo
    return ficha_de_segmentos(Path(ruta).name, segmentos)


def leer_ficha_de_bytes(nombre: str, datos: bytes) -> FichaFoto:
    """Lo mismo, desde los bytes de un JPEG (las pruebas, y lo que ya está en memoria)."""
    return ficha_de_segmentos(nombre, _segmentos(datos)[0])


def ficha_de_segmentos(nombre: str, segmentos: list[tuple[int, bytes]]) -> FichaFoto:
    dji, creada = _xmp_de_dji(segmentos)
    exif = _exif(segmentos)
    principal: dict = dict(exif) if exif is not None else {}
    del_exif = exif.get_ifd(0x8769) if exif is not None else {}
    gps = exif.get_ifd(0x8825) if exif is not None else {}

    def flotante(etiqueta):
        v = del_exif.get(etiqueta)
        return _numero(v) if v is not None else None

    alt = _numero(dji.get("AbsoluteAltitude"))
    lat, lon, posicion_de = None, None, ""
    posicion_xmp = (
        _numero(dji.get("GpsLatitude")),
        _numero(dji.get("GpsLongitude", dji.get("GpsLongtitude"))),
    )
    posicion_exif = (
        _grados(gps.get(2), gps.get(1)) if gps.get(2) is not None else None,
        _grados(gps.get(4), gps.get(3)) if gps.get(4) is not None else None,
    )
    # La del XMP tiene nueve decimales (0,1 mm); la del EXIF, segundos con cuatro (3 mm). Una que no
    # es una latitud y longitud posible se descarta y se prueba la otra.
    for fuente, (a, b) in (("XMP", posicion_xmp), ("EXIF", posicion_exif)):
        if a is not None and b is not None and -90 <= a <= 90 and -180 <= b <= 180:
            lat, lon, posicion_de = a, b, fuente
            break
    if alt is None and gps.get(6) is not None:
        alt = _numero(gps.get(6))
        if alt is not None and gps.get(5) in (1, b"\x01"):
            alt = -alt

    def texto(valor) -> str | None:
        limpio = str(valor).strip().strip("\x00").strip() if valor is not None else ""
        return limpio or None

    fecha = creada or texto(del_exif.get(0x9003)) or texto(principal.get(0x0132))
    return FichaFoto(
        nombre=nombre,
        marca=texto(principal.get(0x010F)),
        modelo=texto(principal.get(0x0110)),
        focal_mm=flotante(0x920A),
        focal_35mm_mm=flotante(0xA405),
        apertura_f=flotante(0x829D),
        exposicion_s=flotante(0x829A),
        iso=_entero(del_exif.get(0x8827)),
        ancho_px=_entero(del_exif.get(0xA002)),
        alto_px=_entero(del_exif.get(0xA003)),
        fecha=fecha,
        rtk_bandera=_entero(dji.get("RtkFlag")),
        gps_estado=texto(dji.get("GpsStatus")),
        tipo_de_altura=texto(dji.get("AltitudeType")),
        lat=lat,
        lon=lon,
        alt_m=alt,
        posicion_de=posicion_de,
        rtk_desv_lat_m=_numero(dji.get("RtkStdLat")),
        rtk_desv_lon_m=_numero(dji.get("RtkStdLon")),
        rtk_desv_alt_m=_numero(dji.get("RtkStdHgt")),
        rtk_edad_dif_s=_numero(dji.get("RtkDiffAge")),
        datum=texto(gps.get(18)),
        gimbal_guinada_deg=_numero(dji.get("GimbalYawDegree")),
        gimbal_cabeceo_deg=_numero(dji.get("GimbalPitchDegree")),
        gimbal_alabeo_deg=_numero(dji.get("GimbalRollDegree")),
        dron_guinada_deg=_numero(dji.get("FlightYawDegree")),
        dron_cabeceo_deg=_numero(dji.get("FlightPitchDegree")),
        dron_alabeo_deg=_numero(dji.get("FlightRollDegree")),
        velocidad_x_ms=_numero(dji.get("FlightXSpeed")),
        velocidad_y_ms=_numero(dji.get("FlightYSpeed")),
        velocidad_z_ms=_numero(dji.get("FlightZSpeed")),
        altura_relativa_m=_numero(dji.get("RelativeAltitude")),
    )
