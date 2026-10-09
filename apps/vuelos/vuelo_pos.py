"""Leer el `.pos` que escribe RTKLIB (`rnx2rtkp`): la trayectoria corregida de un vuelo (F18.1).

El PPK lo hace RTKLIB, un programa de fuera (ver `docs/VUELOS_DE_DRON_Y_PPK.md`). Aquí se **lee
lo que dejó** y se dice con franqueza cómo salió: cuántas posiciones son **fijas**, cuántas
**flotantes**, cuántas **simples** y dónde hay huecos. Un `.pos` no trae «el error de la foto»:
trae el de cada época, y es lo que se transmite.

## El formato que se admite

El de salida por omisión de RTKLIB: líneas de cabecera que empiezan por `%` y, por época,

    fecha hora  latitud  longitud  altura  Q  ns  sdn sde sdu sdne sdeu sdun  edad  razón

- **Posiciones en latitud, longitud y altura elipsoidal** (`llh`). Si el archivo las trae en ECEF,
  ENU o NMEA se dice, y no se adivina la conversión.
- **Escala de tiempo GPST**, la de RTKLIB por omisión y la de las marcas de disparo de las fotos.
  Un `.pos` en UTC o en hora local se rechaza con su escala dicha: restar los segundos intercalares
  «de memoria» es la clase de ajuste que se hace mal sin que se note.

## Lo que no hace

No corrige, no interpola y no extrapola: eso es la sincronía de fotos (`vuelo_sync.py`).
Una línea que no se entiende **se cuenta y se dice con su número de línea**, y no tumba la lectura;
pero un archivo sin ninguna posición legible no es un `.pos`, y se rechaza.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime

from apps.documents.composicion import ComposicionInvalida

#: El inicio del tiempo GPS.
INICIO_GPS = datetime(1980, 1, 6)

#: Los códigos de calidad de RTKLIB y cómo se llaman aquí.
CALIDADES = {
    0: "no informada",
    1: "fija",
    2: "flotante",
    3: "SBAS",
    4: "DGPS",
    5: "simple",
    6: "PPP",
}

#: Con cuántas veces el intervalo típico se considera un hueco en la trayectoria.
FACTOR_DE_HUECO = 5.0

_EPOCA = re.compile(r"^\s*(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)\s+(.*)$")
_ESCALA = re.compile(r"^%\s+(GPST|UTC|JST|TAI|GST|BDT|QZSST)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Epoca:
    t_gps_s: float  # segundos desde el 1980-01-06 00:00:00 (GPST)
    fecha: datetime  # lo mismo, como fecha
    lat: float
    lon: float
    alt_m: float
    q: int
    ns: int
    sdn_m: float
    sde_m: float
    sdu_m: float
    edad_s: float
    razon: float

    @property
    def calidad(self) -> str:
        return CALIDADES.get(self.q, f"código {self.q}")


@dataclass(frozen=True)
class Hueco:
    desde_gps_s: float
    hasta_gps_s: float

    @property
    def duracion_s(self) -> float:
        return self.hasta_gps_s - self.desde_gps_s


@dataclass
class Trayectoria:
    epocas: list[Epoca] = field(default_factory=list)
    ilegibles: list[int] = field(default_factory=list)  # números de línea que no se entendieron
    escala_de_tiempo: str = "GPST"
    #: A qué se refiere la altura. La de RTKLIB es elipsoidal; la de un archivo de otro programa
    #: se dice como viene, y no se llama elipsoidal si no se sabe.
    referencia_de_altura: str = "elipsoidal"

    @property
    def n(self) -> int:
        return len(self.epocas)

    def por_calidad(self) -> dict[str, int]:
        cuentas: dict[str, int] = {}
        for e in self.epocas:
            cuentas[e.calidad] = cuentas.get(e.calidad, 0) + 1
        return cuentas

    def porcentaje(self, q: int) -> float:
        return 100.0 * sum(1 for e in self.epocas if e.q == q) / self.n if self.n else 0.0

    @property
    def intervalo_tipico_s(self) -> float:
        pasos = [b.t_gps_s - a.t_gps_s for a, b in zip(self.epocas, self.epocas[1:], strict=False)]
        return statistics.median(pasos) if pasos else 0.0

    def huecos(self) -> list[Hueco]:
        """Donde faltan épocas: RTKLIB no escribe las que no pudo resolver."""
        tipico = self.intervalo_tipico_s
        if tipico <= 0:
            return []
        limite = FACTOR_DE_HUECO * tipico
        return [
            Hueco(a.t_gps_s, b.t_gps_s)
            for a, b in zip(self.epocas, self.epocas[1:], strict=False)
            if b.t_gps_s - a.t_gps_s > limite
        ]


def _flotante(texto: str) -> float:
    return float(texto)


def leer(texto: str) -> Trayectoria:
    """La trayectoria de un `.pos`, en el orden del archivo. Ver el docstring del módulo."""
    trayectoria = Trayectoria()
    hay_cabecera = False
    formato_de_posicion = "llh"
    for numero, linea in enumerate(texto.splitlines(), start=1):
        if not linea.strip():
            continue
        if linea.lstrip().startswith("%"):
            hay_cabecera = True
            escala = _ESCALA.match(linea.strip())
            if escala:
                trayectoria.escala_de_tiempo = escala.group(1).upper()
            minuscula = linea.lower()
            if "x-ecef" in minuscula:
                formato_de_posicion = "ecef"
            elif "e-baseline" in minuscula or "n-baseline" in minuscula:
                formato_de_posicion = "enu"
            continue
        coincidencia = _EPOCA.match(linea)
        if not coincidencia:
            trayectoria.ilegibles.append(numero)
            continue
        y, mo, d, h, mi, s, resto = coincidencia.groups()
        campos = resto.split()
        if len(campos) < 13:
            trayectoria.ilegibles.append(numero)
            continue
        try:
            segundos = float(s)
            fecha = datetime(int(y), int(mo), int(d), int(h), int(mi), int(segundos)).replace(
                microsecond=round((segundos - int(segundos)) * 1_000_000)
            )
            epoca = Epoca(
                t_gps_s=(fecha - INICIO_GPS).total_seconds(),
                fecha=fecha,
                lat=_flotante(campos[0]),
                lon=_flotante(campos[1]),
                alt_m=_flotante(campos[2]),
                q=int(campos[3]),
                ns=int(campos[4]),
                sdn_m=_flotante(campos[5]),
                sde_m=_flotante(campos[6]),
                sdu_m=_flotante(campos[7]),
                edad_s=_flotante(campos[11]),
                razon=_flotante(campos[12]),
            )
        except ValueError:
            trayectoria.ilegibles.append(numero)
            continue
        if not (-90 <= epoca.lat <= 90 and -180 <= epoca.lon <= 180):
            trayectoria.ilegibles.append(numero)
            continue
        trayectoria.epocas.append(epoca)

    if formato_de_posicion != "llh":
        raise ComposicionInvalida(
            f"Este .pos trae las posiciones en {formato_de_posicion.upper()}: se esperan latitud, "
            "longitud y altura (en RTKLIB, «Output Solution Format: Lat/Lon/Height»). "
            "No se adivina la conversión."
        )
    if not trayectoria.epocas:
        motivo = (
            "no trae ninguna posición legible"
            if hay_cabecera
            else "no tiene cabecera ni posiciones: no parece un .pos de RTKLIB"
        )
        raise ComposicionInvalida(f"Este archivo {motivo}.")
    if trayectoria.escala_de_tiempo != "GPST":
        raise ComposicionInvalida(
            f"Este .pos está en la escala de tiempo {trayectoria.escala_de_tiempo}, y las marcas "
            "de disparo de las fotos van en GPST. Vuelva a correr RTKLIB con «Time Format: GPST»; "
            "restar los segundos intercalares de memoria es la clase de ajuste que se hace mal."
        )
    return trayectoria


def a_markdown(t: Trayectoria, nombre: str) -> str:
    """Cómo salió el PPK, en texto: lo que se midió y lo que no se puede afirmar."""
    inicio, fin = t.epocas[0], t.epocas[-1]
    lineas = [
        f"# Calidad de la trayectoria de {nombre}",
        "",
        f"- Posiciones: **{t.n}**, de {inicio.fecha:%Y-%m-%d %H:%M:%S} a {fin.fecha:%H:%M:%S} GPST "
        f"({fin.t_gps_s - inicio.t_gps_s:.1f} s).",
        f"- Intervalo típico: {t.intervalo_tipico_s:.3f} s.",
        "",
        "## Calidad de las posiciones",
        "",
    ]
    for q in sorted({e.q for e in t.epocas}):
        etiqueta = CALIDADES.get(q, f"código {q}")
        lineas.append(f"- {etiqueta.capitalize()}: {t.porcentaje(q):.1f} %")
    fijas = t.porcentaje(1)
    lineas += [""]
    if fijas >= 95:
        lineas.append("Casi toda la trayectoria tiene la ambigüedad resuelta (solución fija).")
    elif fijas > 0:
        lineas.append(
            f"**Solo el {fijas:.1f} % de las posiciones es fijo.** Las flotantes y simples tienen "
            "un error mayor: revise antes de usarlas para fotogrametría de precisión."
        )
    else:
        lineas.append(
            "**Ninguna posición es fija.** Sin ambigüedad resuelta no hay precisión de "
            "centímetro; revise la base, los satélites comunes y el tiempo de observación."
        )
    huecos = t.huecos()
    lineas += ["", "## Huecos", ""]
    if huecos:
        mayor = max(h.duracion_s for h in huecos)
        lineas.append(
            f"Hay **{len(huecos)}** hueco(s); el mayor dura {mayor:.1f} s. RTKLIB no "
            "escribe las épocas que no pudo resolver, y aquí no se inventan."
        )
    else:
        lineas.append("Sin huecos.")
    if t.ilegibles:
        lineas += [
            "",
            f"**Líneas que no se entendieron:** {len(t.ilegibles)} "
            f"(la primera, la {t.ilegibles[0]}).",
        ]
    lineas.append("")
    return "\n".join(lineas)
