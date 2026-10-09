"""Sincronía de fotos (UAS sync): la posición corregida de cada foto del vuelo (F18.2).

Una cámara de dron dispara en momentos que se anotan (el `.MRK` de DJI trae uno por foto, con su
semana y segundo GPS). La trayectoria corregida por PPK (`vuelo_pos.py`) trae una posición cada
0,1 a 1 s. **Sincronizar es leer la trayectoria en el instante de cada disparo.**

## Lo que se garantiza

- **No se extrapola nunca.** Un disparo antes del primer punto de la trayectoria, después del
  último o dentro de un hueco largo **queda sin posición, con su motivo dicho**. Una posición
  inventada fuera de lo medido es peor que ninguna: nadie la distinguiría de una buena.
- **La calidad de la foto es la del peor de los dos puntos entre los que cae.** Una foto entre un
  punto fijo y uno flotante es flotante.
- **Interpolación lineal en latitud, longitud y altura.** En línea recta es exacta. En una curva
  el error máximo es la flecha del arco entre los dos puntos, `r·(1 − cos(Δθ/2))`: con 40 m de
  radio, 12 m/s y 5 Hz son unos 18 mm. Las pruebas lo miden contra esa cota. Las fotos de un
  vuelo de levantamiento se toman en líneas rectas, donde el error es cero.
- **El desfase de la antena se aplica**: el `.MRK` trae, por foto, cuánto está la cámara respecto
  de la antena en `N`, `E` y `V` (milímetros). **Norte y este se suman; `V` es positivo hacia
  abajo y se resta de la altura.** El signo no se supuso: se midió con un vuelo real de un
  Matrice 3E (2 505 fotos, 2025-12-29) contra las posiciones que entregó Trimble Business Center
  (su UAS sync): con estos signos la diferencia es de **0,3 mm de desviación y 0,9 mm en el peor
  caso**, que es el redondeo de su CSV; con cualquier otra combinación es de 6 a 170 mm. El
  desfase se puede apagar (`aplicar_desfase=False`), y una foto sin desfase en su disparo
  (una lista de tiempos, por ejemplo) sale con la posición de la antena **y el CSV lo dice**.
- **La altura es elipsoidal**, la que da el PPK. Se dice en el nombre de la columna.

## Lo que no hace

No conoce las fotos: empareja los eventos con una **lista de nombres** solo si hay **tantos
como disparos**; si no, se niega a emparejar. Pasar las coordenadas a otro sistema o a altura
ortométrica es otro paso.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime

from apps.documents.composicion import ComposicionInvalida

from .fotos_dron import Foto
from .vuelo_pos import INICIO_GPS, Trayectoria

SEGUNDOS_POR_SEMANA = 604_800

#: Del mejor al peor. Una foto toma la peor de las dos calidades vecinas.
ORDEN_DE_CALIDAD = (1, 2, 6, 4, 3, 5)

#: Con cuántas veces el intervalo típico de la trayectoria una foto se considera «en un hueco».
FACTOR_DE_HUECO = 3.0

#: Los sistemas cuyas coordenadas geográficas se pueden poner tal cual en un KML (que es WGS84).
COMPATIBLES_CON_WGS84 = ("wgs84", "sirgas", "itrf", "igs")


@dataclass(frozen=True)
class Disparo:
    numero: int
    t_gps_s: float
    desfase_n_mm: float | None = None
    desfase_e_mm: float | None = None
    desfase_v_mm: float | None = None
    # Lo que el propio `.MRK` dice de la posición de la antena en ese disparo (sirve para
    # comprobar que unas fotos son de este `.MRK`, y la altura que escribe el dron: `Ellh`).
    lat: float | None = None
    lon: float | None = None
    alt_elipsoidal_m: float | None = None


@dataclass(frozen=True)
class FotoSincronizada:
    disparo: Disparo
    nombre: str
    lat: float | None
    lon: float | None
    alt_m: float | None
    sdn_m: float | None
    sde_m: float | None
    sdu_m: float | None
    q: int | None
    motivo: str  # vacío si hay posición
    desfase_aplicado: bool = False  # la posición es la de la cámara y no la de la antena
    #: Si la calidad no es una de `CALIDADES` (una bandera RTK que no se reconoce, o sin solución),
    #: aquí va su texto: el código numérico no puede decirlo.
    calidad_texto: str = ""

    @property
    def con_posicion(self) -> bool:
        return self.lat is not None

    @property
    def calidad(self) -> str:
        """El texto de la calidad; vacío si no hay calidad que decir."""
        if self.calidad_texto:
            return self.calidad_texto
        return CALIDADES.get(self.q, f"código {self.q}") if self.q is not None else ""


# --- Los disparos --------------------------------------------------------------------------

_ETIQUETADO = re.compile(r"(-?\d+(?:\.\d+)?),\s*(N|E|V)\b")
_POSICION_MRK = re.compile(r"(-?\d+(?:\.\d+)?),\s*(Lat|Lon|Ellh)\b")


def leer_mrk(texto: str) -> list[Disparo]:
    """Los disparos de un `.MRK` de DJI: número, semana y segundo GPS, y el desfase N, E, V."""
    disparos: list[Disparo] = []
    for numero_de_linea, linea in enumerate(texto.splitlines(), start=1):
        if not linea.strip():
            continue
        campos = [c.strip() for c in linea.split("\t")]
        semana = re.search(r"\[(\d{3,5})\]", linea)
        if len(campos) < 3 or not campos[0].isdigit() or semana is None:
            raise ComposicionInvalida(
                f"La línea {numero_de_linea} no es un disparo de un .MRK "
                "(número, segundo GPS, [semana], desfases)."
            )
        try:
            tow = float(campos[1])
        except ValueError as fallo:
            raise ComposicionInvalida(
                f"La línea {numero_de_linea} del .MRK no trae un segundo GPS legible."
            ) from fallo
        desfases = {m.group(2): float(m.group(1)) for m in _ETIQUETADO.finditer(linea)}
        posicion = {m.group(2): float(m.group(1)) for m in _POSICION_MRK.finditer(linea)}
        disparos.append(
            Disparo(
                numero=int(campos[0]),
                t_gps_s=int(semana.group(1)) * SEGUNDOS_POR_SEMANA + tow,
                desfase_n_mm=desfases.get("N"),
                desfase_e_mm=desfases.get("E"),
                desfase_v_mm=desfases.get("V"),
                lat=posicion.get("Lat"),
                lon=posicion.get("Lon"),
                alt_elipsoidal_m=posicion.get("Ellh"),
            )
        )
    if not disparos:
        raise ComposicionInvalida("El .MRK no trae ningún disparo.")
    return disparos


def leer_lista_de_tiempos(texto: str) -> list[Disparo]:
    """Disparos, uno por línea: `semana segundo` o `AAAA/MM/DD hh:mm:ss.sss` en GPST."""
    disparos: list[Disparo] = []
    for numero_de_linea, linea in enumerate(texto.splitlines(), start=1):
        limpia = linea.strip()
        if not limpia or limpia.startswith("#"):
            continue
        calendario = re.fullmatch(
            r"(\d{4})/(\d{2})/(\d{2})[ T](\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", limpia
        )
        semana_tow = re.fullmatch(r"(\d{3,5})[\s,;]+(\d+(?:\.\d+)?)", limpia)
        try:
            if calendario:
                y, mo, d, h, mi, s = calendario.groups()
                entero = int(float(s))
                t = (
                    datetime(int(y), int(mo), int(d), int(h), int(mi), entero) - INICIO_GPS
                ).total_seconds() + (float(s) - entero)
            elif semana_tow:
                t = int(semana_tow.group(1)) * SEGUNDOS_POR_SEMANA + float(semana_tow.group(2))
            else:
                raise ValueError
        except ValueError as fallo:
            raise ComposicionInvalida(
                f"La línea {numero_de_linea} no es un tiempo GPS: «{limpia}». Se esperan "
                "«semana segundo» o «AAAA/MM/DD hh:mm:ss.sss» en GPST."
            ) from fallo
        disparos.append(Disparo(numero=len(disparos) + 1, t_gps_s=t))
    if not disparos:
        raise ComposicionInvalida("La lista de disparos está vacía.")
    return disparos


def emparejar(disparos: list[Disparo], nombres: list[str]) -> list[str]:
    """Un nombre por disparo, en orden. **Solo si hay tantos como disparos.**"""
    if len(nombres) != len(disparos):
        raise ComposicionInvalida(
            f"Hay {len(disparos)} disparos y {len(nombres)} fotos: no se pueden emparejar. Una "
            "foto borrada o repetida correría todos los nombres, y cada foto saldría con la "
            "posición de otra."
        )
    return list(nombres)


# --- La sincronía ---------------------------------------------------------------------------


def _mayor(x: float, y: float) -> float:
    """El mayor de dos incertidumbres; si alguna no se informó (NaN), la foto tampoco la tiene."""
    if math.isnan(x) or math.isnan(y):
        return math.nan
    return max(x, y)


def _peor(a: int, b: int) -> int:
    def rango(q: int) -> int:
        return ORDEN_DE_CALIDAD.index(q) if q in ORDEN_DE_CALIDAD else len(ORDEN_DE_CALIDAD)

    return a if rango(a) >= rango(b) else b


# WGS84 (y GRS80, que difiere en décimas de milímetro): para pasar metros a grados.
_A = 6_378_137.0
_E2 = 0.006_694_379_990_141_3


def _mover(lat: float, alt_m: float, norte_m: float, este_m: float) -> tuple[float, float]:
    """Cuántos grados de latitud y de longitud son `norte_m` y `este_m` en ese punto."""
    fi = math.radians(lat)
    s2 = math.sin(fi) ** 2
    radio_n = _A / math.sqrt(1 - _E2 * s2)  # el del primer vertical
    radio_m = _A * (1 - _E2) / (1 - _E2 * s2) ** 1.5  # el del meridiano
    return (
        math.degrees(norte_m / (radio_m + alt_m)),
        math.degrees(este_m / ((radio_n + alt_m) * math.cos(fi))),
    )


def sincronizar(
    trayectoria: Trayectoria,
    disparos: list[Disparo],
    nombres: list[str] | None = None,
    *,
    aplicar_desfase: bool = True,
) -> list[FotoSincronizada]:
    """La posición de cada disparo. Las que no se pueden dar salen sin posición y con motivo."""
    if nombres is not None:
        nombres = emparejar(disparos, nombres)
    epocas = trayectoria.epocas
    tipico = trayectoria.intervalo_tipico_s
    limite = FACTOR_DE_HUECO * tipico if tipico > 0 else 0.0
    primero, ultimo = epocas[0].t_gps_s, epocas[-1].t_gps_s

    resultado: list[FotoSincronizada] = []
    # Los tiempos están ordenados en el `.pos`, y los disparos casi siempre: se busca a mano con
    # un puntero que solo avanza, y se vuelve a empezar si un disparo viene antes que el anterior.
    puntero = 0
    for indice, disparo in enumerate(disparos):
        nombre = nombres[indice] if nombres else ""
        t = disparo.t_gps_s

        def sin_posicion(motivo: str, disparo=disparo, nombre=nombre):
            return FotoSincronizada(
                disparo, nombre, None, None, None, None, None, None, None, motivo
            )

        if t < primero - 1e-6:
            resultado.append(
                sin_posicion(f"antes del primer punto de la trayectoria ({primero - t:.2f} s)")
            )
            continue
        if t > ultimo + 1e-6:
            resultado.append(
                sin_posicion(f"después del último punto de la trayectoria ({t - ultimo:.2f} s)")
            )
            continue
        if puntero >= len(epocas) or epocas[puntero].t_gps_s > t:
            puntero = 0
        while puntero + 1 < len(epocas) and epocas[puntero + 1].t_gps_s <= t:
            puntero += 1
        a = epocas[puntero]
        b = epocas[puntero + 1] if puntero + 1 < len(epocas) else a
        paso = b.t_gps_s - a.t_gps_s

        if paso <= 1e-9 or abs(t - a.t_gps_s) < 1e-6:
            f, b = 0.0, a
        else:
            if limite and paso > limite:
                resultado.append(
                    sin_posicion(
                        f"en un hueco de la trayectoria de {paso:.1f} s "
                        f"(lo típico son {tipico:.2f} s)"
                    )
                )
                continue
            f = (t - a.t_gps_s) / paso

        def mezcla(x: float, y: float, f=f) -> float:
            return x + (y - x) * f

        lat, lon, alt = mezcla(a.lat, b.lat), mezcla(a.lon, b.lon), mezcla(a.alt_m, b.alt_m)
        aplicado = False
        if (
            aplicar_desfase
            and disparo.desfase_n_mm is not None
            and disparo.desfase_e_mm is not None
            and disparo.desfase_v_mm is not None
        ):
            dlat, dlon = _mover(lat, alt, disparo.desfase_n_mm / 1000, disparo.desfase_e_mm / 1000)
            # `V` es positivo hacia abajo: la cámara cuelga por debajo de la antena.
            lat, lon, alt = lat + dlat, lon + dlon, alt - disparo.desfase_v_mm / 1000
            aplicado = True

        resultado.append(
            FotoSincronizada(
                disparo=disparo,
                nombre=nombre,
                lat=lat,
                lon=lon,
                alt_m=alt,
                # La incertidumbre de la foto es la mayor de las dos vecinas: no se promedia.
                # Si una trayectoria no la informa (la de Trimble) queda sin dato, no en cero.
                sdn_m=_mayor(a.sdn_m, b.sdn_m),
                sde_m=_mayor(a.sde_m, b.sde_m),
                sdu_m=_mayor(a.sdu_m, b.sdu_m),
                q=_peor(a.q, b.q),
                motivo="",
                desfase_aplicado=aplicado,
            )
        )
    return resultado


# --- Lo que se entrega -----------------------------------------------------------------------

CALIDADES = {
    0: "no informada",
    1: "fija",
    2: "flotante",
    3: "SBAS",
    4: "DGPS",
    5: "simple",
    6: "PPP",
}

COLUMNAS_CSV = (
    "foto",
    "disparo",
    "lat",
    "lon",
    "altura_m",
    "referencia_de_altura",
    "sdn_m",
    "sde_m",
    "sdu_m",
    "calidad",
    "t_gps_s",
    "desfase_antena_n_mm",
    "desfase_antena_e_mm",
    "desfase_antena_v_mm",
    "desfase_aplicado",
    # La orientación del gimbal, tal como la escribe DJI (F18.10): cabeceo −90 = nadir. Vacías si
    # no hay de dónde leerla (ni las fotos ni el archivo de Trimble).
    "gimbal_guinada_deg",
    "gimbal_cabeceo_deg",
    "gimbal_alabeo_deg",
    "motivo",
)

#: La orientación del gimbal de una foto: guiñada, cabeceo y alabeo, en grados y como la da DJI.
Orientacion = tuple[float | None, float | None, float | None]


def _numero(valor, decimales: int) -> str:
    return "" if valor is None or math.isnan(valor) else f"{valor:.{decimales}f}"


def _o_nada(valor):
    """Para JSON: un NaN no es JSON válido."""
    return None if valor is None or math.isnan(valor) else valor


def a_csv(
    fotos: list[FotoSincronizada],
    referencia_de_altura: str = "elipsoidal",
    orientaciones: dict[str, Orientacion] | None = None,
) -> str:
    """El CSV para Pix4D, Metashape o QGIS. Las fotos sin posición van, con su motivo.

    `orientaciones` (nombre de la foto en minúsculas → guiñada, cabeceo y alabeo del gimbal) llena
    las tres columnas de orientación; la foto que no está queda con ellas **vacías**, no en cero.
    """
    orientaciones = orientaciones or {}
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\n")
    escritor.writerow(COLUMNAS_CSV)
    for f in fotos:
        d = f.disparo
        guinada, cabeceo, alabeo = orientaciones.get(f.nombre.lower(), (None, None, None))
        escritor.writerow(
            [
                f.nombre,
                d.numero,
                _numero(f.lat, 9),
                _numero(f.lon, 9),
                _numero(f.alt_m, 4),
                referencia_de_altura,
                _numero(f.sdn_m, 4),
                _numero(f.sde_m, 4),
                _numero(f.sdu_m, 4),
                f.calidad,
                f"{d.t_gps_s:.6f}",
                _numero(d.desfase_n_mm, 1),
                _numero(d.desfase_e_mm, 1),
                _numero(d.desfase_v_mm, 1),
                "si" if f.desfase_aplicado else "no",
                _numero(guinada, 2),
                _numero(cabeceo, 2),
                _numero(alabeo, 2),
                f.motivo,
            ]
        )
    return salida.getvalue()


def a_geojson(fotos: list[FotoSincronizada], sistema: str) -> str:
    rasgos = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [f.lon, f.lat, f.alt_m]},
            "properties": {
                "foto": f.nombre,
                "disparo": f.disparo.numero,
                "calidad": f.calidad,
                "sdn_m": _o_nada(f.sdn_m),
                "sde_m": _o_nada(f.sde_m),
                "sdu_m": _o_nada(f.sdu_m),
            },
        }
        for f in fotos
        if f.con_posicion
    ]
    return json.dumps(
        {"type": "FeatureCollection", "sistema": sistema, "features": rasgos}, ensure_ascii=False
    )


def es_compatible_con_wgs84(sistema: str) -> bool:
    return any(sistema.strip().lower().startswith(p) for p in COMPATIBLES_CON_WGS84)


def a_kml(fotos: list[FotoSincronizada], sistema: str) -> str:
    """El KML, **solo si el sistema se puede leer como WGS84**. Si no, se rechaza y se dice."""
    if not es_compatible_con_wgs84(sistema):
        raise ComposicionInvalida(
            f"Las posiciones están en «{sistema}», y un KML es WGS84: ponerlas ahí tal cual las "
            "movería. Use el GeoJSON o el CSV, o transforme antes de entregar."
        )
    from . import fotos_dron

    puestas = [
        (f.nombre or f"disparo {f.disparo.numero}", Foto(f.nombre, f.lat, f.lon, f.alt_m, None))
        for f in fotos
        if f.con_posicion
    ]
    if not puestas:
        raise ComposicionInvalida("Ninguna foto tiene posición: no hay nada que poner en el KML.")
    return fotos_dron.a_kml(puestas)


def resumen(fotos: list[FotoSincronizada]) -> dict:
    con = [f for f in fotos if f.con_posicion]
    por_calidad: dict[str, int] = {}
    for f in con:
        nombre = f.calidad
        por_calidad[nombre] = por_calidad.get(nombre, 0) + 1
    return {
        "fotos": len(fotos),
        "con_posicion": len(con),
        "sin_posicion": len(fotos) - len(con),
        "por_calidad": por_calidad,
        "motivos": sorted({f.motivo for f in fotos if f.motivo}),
    }
