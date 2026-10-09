"""Importar lo que entrega Trimble Business Center de un vuelo y medir su sistema (F18.6).

Quien procesa el PPK en Trimble Business Center (TBC) exporta tres archivos de texto:

- **la trayectoria** (`009.csv`, sin cabecera): `nombre, Este, Norte, Altura, , fecha-hora` a 5 Hz;
- **las posiciones de las fotos** (`… export.csv`): `foto, Este, Norte, Altura`;
- **las posiciones de las fotos, ampliadas** (`… export_extended.csv`): lo mismo más latitud y
  longitud, la calidad (`PPK`), la actitud del dron y de la cámara y los datos de la toma.

Ninguno dice **en qué sistema están** su Este y su Norte, ni en qué escala de tiempo va la hora.
Aquí no se supone nada de eso (regla 3 de `AGENTS.md`):

- **El sistema se mide.** Con el archivo ampliado, que trae latitud y longitud al lado de Este
  y Norte, se prueba cada sistema candidato y se dice **cuál coincide y a cuántos milímetros**.
  Con un vuelo real (Matrice 3E, 2 505 fotos, UTM zona 19S) coinciden WGS84, SIRGAS-Chile 2002
  y SIRGAS 2000, a menos de un milímetro entre sí, y PSAD56 y SAD69 quedan a 418 m y 73 m:
  se distinguen de sobra. Los tres que coinciden **no se distinguen entre sí** y el informe lo
  dice así: a este nivel son el mismo marco.
- **La hora de la trayectoria es GPST** salvo que se diga otra cosa: con ese vuelo, leerla así deja
  las posiciones de las fotos a 0,3 mm de las de Trimble; en UTC quedarían a metros.
- **La altura se deja como viene.** La del archivo de Trimble **no es la elipsoidal** del `.MRK`
  (difieren unos 35 m en ese vuelo, la ondulación del geoide más el error del tiempo real) y aquí
  no hay un modelo de geoide con que pasar de una a otra: se entrega con su referencia dicha.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from apps.documents.composicion import ComposicionInvalida

from .vuelo_pos import INICIO_GPS, Epoca, Trayectoria

#: Los sistemas que se prueban, por su código EPSG. **Todos UTM, zonas 18, 19 y 20 Sur** (Chile).
#: Los tres primeros grupos son del marco ITRF y coinciden entre sí a nivel de milímetros en
#: proyección; PSAD56 y SAD69 son los antiguos, con cientos de metros de diferencia.
CANDIDATOS = {
    32718: "WGS 84 / UTM 18S",
    32719: "WGS 84 / UTM 19S",
    32720: "WGS 84 / UTM 20S",
    5362: "SIRGAS-Chile 2002 / UTM 18S",
    5361: "SIRGAS-Chile 2002 / UTM 19S",
    31978: "SIRGAS 2000 / UTM 18S",
    31979: "SIRGAS 2000 / UTM 19S",
    31980: "SIRGAS 2000 / UTM 20S",
    24878: "PSAD56 / UTM 18S",
    24879: "PSAD56 / UTM 19S",
    24880: "PSAD56 / UTM 20S",
    29188: "SAD69 / UTM 18S",
    29189: "SAD69 / UTM 19S",
    29190: "SAD69 / UTM 20S",
}

#: Los que se pueden usar para pasar a latitud y longitud **sin** transformación de datum: del marco
#: ITRF, donde los tres coinciden. Los antiguos necesitan parámetros de transformación que aquí no
#: se adivinan.
USABLES = frozenset({32718, 32719, 32720, 5362, 5361, 31978, 31979, 31980})

#: Con cuántos metros de diferencia media se dice que un sistema «coincide».
UMBRAL_DE_COINCIDENCIA_M = 0.01

#: GPST − UTC en segundos, por fecha de entrada en vigor (desde 1999; el último salto, 2017-01-01).
SALTOS_GPS_UTC = (
    (datetime(2017, 1, 1), 18),
    (datetime(2015, 7, 1), 17),
    (datetime(2012, 7, 1), 16),
    (datetime(2009, 1, 1), 15),
    (datetime(2006, 1, 1), 14),
    (datetime(1999, 1, 1), 13),
)

ESCALAS_DE_TIEMPO = {"GPST": "GPST (la de RTKLIB y la del .MRK)", "UTC": "UTC"}


@dataclass(frozen=True)
class PuntoDeTrayectoria:
    nombre: str
    este: float
    norte: float
    altura: float
    t_gps_s: float


#: Las columnas del archivo ampliado que sirven para la ficha de la foto y para la orientación de
#: la cámara (F18.9, F18.10). Se guardan **como texto**: quien las interpreta es `ficha_foto`.
COLUMNAS_DE_FICHA = (
    "Fecha",
    "Modelo",
    "Apertura",
    "Tiempo exp.",
    "F Number",
    "Focal",
    "Focal 35 mm",
    "ISO Speed",
    "Dimensiones",
    "Alt. abs. vuelo",
    "Alt.rel.vuelo",
    "Gimbal Roll",
    "Gimbal Yaw",
    "Gimbal Pitch",
    "UAV Roll",
    "UAV Yaw",
    "UAV Pitch",
    "V. UAV X",
    "V. UAV Y",
    "V. UAV Z",
)


@dataclass(frozen=True)
class PosicionDeFoto:
    nombre: str
    este: float
    norte: float
    altura: float
    lat: float | None = None
    lon: float | None = None
    calidad: str = ""
    extras: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Candidato:
    epsg: int
    nombre: str
    error_medio_m: float
    error_maximo_m: float
    usable: bool

    @property
    def coincide(self) -> bool:
        return self.error_medio_m <= UMBRAL_DE_COINCIDENCIA_M


def _decodificar(datos: bytes) -> str:
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return datos.decode("cp1252")


def _gps_menos_utc(fecha: datetime) -> int:
    for desde, saltos in SALTOS_GPS_UTC:
        if fecha >= desde:
            return saltos
    raise ComposicionInvalida(
        "La trayectoria está en UTC y es anterior a 1999: no hay cómo pasarla a GPST aquí."
    )


def leer_trayectoria(datos: bytes, *, escala_de_tiempo: str = "GPST") -> list[PuntoDeTrayectoria]:
    """La trayectoria de TBC. Una línea mala se rechaza con su número: es un archivo de máquina."""
    if escala_de_tiempo not in ESCALAS_DE_TIEMPO:
        raise ComposicionInvalida(
            f"«{escala_de_tiempo}» no es una escala de tiempo de las que hay."
        )
    puntos: list[PuntoDeTrayectoria] = []
    for numero, fila in enumerate(csv.reader(io.StringIO(_decodificar(datos))), start=1):
        if not fila or not any(c.strip() for c in fila):
            continue
        if len(fila) < 6:
            raise ComposicionInvalida(
                f"La línea {numero} no es un punto de trayectoria de Trimble "
                "(nombre, Este, Norte, Altura, vacío, fecha y hora)."
            )
        try:
            fecha = datetime.strptime(fila[5].strip()[:26], "%Y-%m-%d %H:%M:%S.%f")
            t = (fecha - INICIO_GPS).total_seconds()
            if escala_de_tiempo == "UTC":
                t += _gps_menos_utc(fecha)
            puntos.append(
                PuntoDeTrayectoria(
                    fila[0].strip(), float(fila[1]), float(fila[2]), float(fila[3]), t
                )
            )
        except ValueError as fallo:
            raise ComposicionInvalida(
                f"La línea {numero} de la trayectoria no se entiende: {fallo}"
            ) from fallo
    if not puntos:
        raise ComposicionInvalida("El archivo no trae ningún punto de trayectoria.")
    return puntos


def leer_posiciones_por_foto(datos: bytes) -> list[PosicionDeFoto]:
    """Las posiciones de las fotos: el archivo corto o el ampliado (los dice su cabecera)."""
    texto = _decodificar(datos)
    primera = texto.lstrip().splitlines()[0] if texto.strip() else ""
    posiciones: list[PosicionDeFoto] = []

    if primera.startswith("ID,") and "Este" in primera:
        for numero, fila in enumerate(csv.DictReader(io.StringIO(texto)), start=2):
            try:
                altura = next(v for k, v in fila.items() if k and k.startswith("Elevaci"))
                posiciones.append(
                    PosicionDeFoto(
                        fila["ID"],
                        float(fila["Este"]),
                        float(fila["Norte"]),
                        float(altura),
                        float(fila["Latitud"]),
                        float(fila["Longitud"]),
                        (fila.get("Calidad") or "").strip(),
                        {
                            c: (fila.get(c) or "").strip()
                            for c in COLUMNAS_DE_FICHA
                            if (fila.get(c) or "").strip()
                        },
                    )
                )
            except (KeyError, ValueError, StopIteration) as fallo:
                raise ComposicionInvalida(
                    f"La línea {numero} del archivo ampliado no se entiende: {fallo}"
                ) from fallo
    else:
        for numero, fila in enumerate(csv.reader(io.StringIO(texto)), start=1):
            if not fila or not any(c.strip() for c in fila):
                continue
            try:
                posiciones.append(
                    PosicionDeFoto(fila[0].strip(), float(fila[1]), float(fila[2]), float(fila[3]))
                )
            except (IndexError, ValueError) as fallo:
                raise ComposicionInvalida(
                    f"La línea {numero} no es una posición de foto de Trimble "
                    "(foto, Este, Norte, Altura)."
                ) from fallo
    if not posiciones:
        raise ComposicionInvalida("El archivo no trae ninguna posición de foto.")
    return posiciones


def identificar_sistema(
    referencias: list[PosicionDeFoto], *, muestra: int = 500
) -> list[Candidato]:
    """Prueba cada sistema candidato contra las fotos que traen **Este/Norte y latitud/longitud**.

    Devuelve todos, del que mejor coincide al que peor. Un sistema «coincide» si el error medio es
    de menos de `UMBRAL_DE_COINCIDENCIA_M`. Sin referencias con latitud y longitud no hay con qué
    medir, y se dice.
    """
    import math

    from pyproj import Transformer

    con_ll = [r for r in referencias if r.lat is not None and r.lon is not None]
    if not con_ll:
        raise ComposicionInvalida(
            "Ninguna posición trae latitud y longitud junto al Este y el Norte: sin ellas no hay "
            "con qué medir el sistema. Use el archivo ampliado («… export_extended») o declare "
            "el sistema a mano."
        )
    paso = max(1, len(con_ll) // muestra)
    elegidas = con_ll[::paso]
    candidatos: list[Candidato] = []
    for epsg, nombre in CANDIDATOS.items():
        transformador = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
        errores = []
        for r in elegidas:
            lon, lat = transformador.transform(r.este, r.norte)
            dlat = (lat - r.lat) * 111_132.0
            dlon = (lon - r.lon) * 111_320.0 * math.cos(math.radians(r.lat))
            errores.append(math.hypot(dlat, dlon))
        candidatos.append(
            Candidato(
                epsg=epsg,
                nombre=nombre,
                error_medio_m=sum(errores) / len(errores),
                error_maximo_m=max(errores),
                usable=epsg in USABLES,
            )
        )
    return sorted(candidatos, key=lambda c: c.error_medio_m)


def veredicto(candidatos: list[Candidato]) -> str:
    """Una frase con lo que se midió, sin dar por único a uno que no se distingue de otros."""
    coinciden = [c for c in candidatos if c.coincide]
    if not coinciden:
        mejor = candidatos[0]
        return (
            f"Ningún sistema de los que se probaron coincide: el mejor, {mejor.nombre}, queda a "
            f"{mejor.error_medio_m:.1f} m. Las coordenadas están en otro sistema, o en otra zona."
        )
    nombres = ", ".join(c.nombre for c in coinciden)
    peor = max(c.error_maximo_m for c in coinciden) * 1000
    if len(coinciden) == 1:
        return f"Coincide {nombres}, a {peor:.1f} mm como máximo."
    return (
        f"Coinciden {nombres}, a {peor:.1f} mm como máximo: **no se distinguen entre sí**, son el "
        "mismo marco para este trabajo."
    )


def a_trayectoria(puntos: list[PuntoDeTrayectoria], epsg: int) -> Trayectoria:
    """La trayectoria en latitud y longitud, con el sistema **declarado**. Calidad: no informada.

    Solo con un sistema ITRF (`USABLES`): con PSAD56 o SAD69 haría falta una transformación de datum
    que no se adivina.
    """
    from pyproj import Transformer

    if epsg not in CANDIDATOS:
        raise ComposicionInvalida(f"EPSG:{epsg} no es uno de los sistemas que se saben leer aquí.")
    if epsg not in USABLES:
        raise ComposicionInvalida(
            f"{CANDIDATOS[epsg]} es un sistema antiguo: pasarlo a latitud y longitud necesita una "
            "transformación de datum que no se adivina. Use el archivo en SIRGAS o WGS84."
        )
    transformador = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    trayectoria = Trayectoria(referencia_de_altura="la del archivo de Trimble (no declarada)")
    for p in puntos:
        lon, lat = transformador.transform(p.este, p.norte)
        nan = float("nan")  # lo que Trimble no informa queda sin dato, no en cero
        trayectoria.epocas.append(
            Epoca(
                p.t_gps_s,
                INICIO_GPS + timedelta(seconds=p.t_gps_s),
                lat,
                lon,
                p.altura,
                0,
                0,
                nan,
                nan,
                nan,
                0.0,
                0.0,
            )  # fmt: skip
        )
    return trayectoria
