"""El proceso PPK de un vuelo con RTKLIB `rnx2rtkp` (F18.3).

PPK es corregir la trayectoria del dron con las observaciones de una **estación base** de
posición conocida. El cálculo lo hace **RTKLIB** (`rnx2rtkp`, BSD-2): un programa de fuera, que se
**sondea y se ejecuta aparte** (decisión D1), nunca se importa. Aquí está lo de alrededor:

1. **La base se declara, con su sistema.** El `APPROX POSITION` del RINEX está a metros de la verdad
   y, usado como si fuera la coordenada de la base, corre toda la trayectoria esos metros. La regla
   3 de `AGENTS.md` aplica entera: las coordenadas **no se toman en silencio**. Se declaran con el
   sistema en que están (SIRGAS, ITRF, WGS84…), y contra el RINEX se comprueba solo que **no estén
   a más de `DISTANCIA_MAXIMA_BASE_M` metros**: un error de signo, de zona o de estación se ve
   ahí, porque sale en kilómetros.
2. **Los archivos se miran antes de lanzar nada**: que el del dron y el de la base sean de
   observación, que haya efemérides de navegación y que el RINEX sea de una versión que RTKLIB lee.
3. **El código de salida no prueba nada** (regla 1). `rnx2rtkp` sale con `0` aunque no resuelva una
   sola época. Lo que se comprueba es el `.pos`: que exista, que `vuelo_pos.leer()` lo entienda y
   que traiga posiciones; y se dice qué porcentaje es fijo.
4. **La orden se arma sin shell**, con una lista de argumentos y las rutas **absolutas** (una ruta
   que empezara por `-` se leería como opción).
5. **El avance se lee en vivo** (F18.7): `rnx2rtkp` escribe en stderr líneas `processing : <hora>`
   separadas por retornos de carro; con la primera y la última observación del dron sale la
   fracción, y sin la última solo la etiqueta. Un plazo máximo corta lo que se cuelga.

## Lo que no hace

No elige por la persona: el modo, la máscara de elevación, los sistemas satelitales y el umbral de
resolución de ambigüedades son opciones con su valor a la vista. Tampoco pasa la trayectoria a otro
sistema de coordenadas.
"""

from __future__ import annotations

import math
import os
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings

from apps.documents.composicion import ComposicionInvalida

from . import vuelo_pos

#: La coordenada declarada de la base no puede estar a más de esto del `APPROX POSITION` del RINEX.
#: El de un RINEX de receptor de navegación es bueno a decenas de metros, y un error de zona o de
#: estación es de kilómetros: el umbral separa unos de otros.
DISTANCIA_MAXIMA_BASE_M = 1_000.0

#: Versiones de RINEX que RTKLIB 2.4.3 lee.
VERSIONES_ADMITIDAS = (
    "2.10",
    "2.11",
    "2.12",
    "3.00",
    "3.01",
    "3.02",
    "3.03",
    "3.04",
    "3.05",
    "4.00",
)

SISTEMAS = {
    "G": "GPS",
    "R": "GLONASS",
    "E": "Galileo",
    "J": "QZSS",
    "C": "BeiDou",
    "I": "NavIC",
}

#: Los modos de `rnx2rtkp -p` que sirven para un vuelo.
MODOS = {"cinematico": "2", "estatico": "3"}

TIEMPO_MAXIMO_S = 3_600


@dataclass(frozen=True)
class Base:
    """La estación base: su posición **declarada**, con el sistema en que está."""

    lat: float
    lon: float
    alt_elipsoidal_m: float
    sistema: str

    def __post_init__(self) -> None:
        if not self.sistema or not self.sistema.strip():
            raise ComposicionInvalida(
                "Falta el sistema de las coordenadas de la base (SIRGAS, ITRF, WGS84…). "
                "No se supone: adivinarlo corre toda la trayectoria."
            )
        if not -90 <= self.lat <= 90:
            raise ComposicionInvalida(f"La latitud de la base ({self.lat}) no es válida.")
        if not -180 <= self.lon <= 180:
            raise ComposicionInvalida(f"La longitud de la base ({self.lon}) no es válida.")
        if not -500 <= self.alt_elipsoidal_m <= 10_000:
            raise ComposicionInvalida(
                f"La altura de la base ({self.alt_elipsoidal_m} m) no es creíble. Se espera la "
                "altura **elipsoidal**, no la sobre el nivel del mar."
            )


@dataclass(frozen=True)
class Opciones:
    modo: str = "cinematico"
    mascara_elevacion_deg: int = 15
    sistemas: str = "G,R,E,C"
    frecuencias: int = 2
    umbral_ambiguedad: float = 3.0
    intervalo_s: float | None = None
    combinada: bool = False  # adelante y atrás

    def validar(self) -> None:
        if self.modo not in MODOS:
            raise ComposicionInvalida(f"«{self.modo}» no es un modo de los que se ofrecen.")
        if not 0 <= self.mascara_elevacion_deg <= 45:
            raise ComposicionInvalida("La máscara de elevación va de 0 a 45 grados.")
        if self.frecuencias not in (1, 2, 3):
            raise ComposicionInvalida("Las frecuencias son 1, 2 o 3.")
        if not 0 <= self.umbral_ambiguedad <= 20:
            raise ComposicionInvalida("El umbral de ambigüedades va de 0 a 20.")
        if self.intervalo_s is not None and not 0.05 <= self.intervalo_s <= 60:
            raise ComposicionInvalida("El intervalo va de 0,05 a 60 segundos.")
        letras = [s.strip().upper() for s in self.sistemas.split(",") if s.strip()]
        if not letras or any(s not in SISTEMAS for s in letras):
            raise ComposicionInvalida(
                "Los sistemas satelitales son letras separadas por comas: "
                + ", ".join(f"{k} ({v})" for k, v in SISTEMAS.items())
                + "."
            )


# --- La sonda ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Disponible:
    programa: str = ""
    motivo: str = ""
    sugerencia: str = ""

    def __bool__(self) -> bool:
        return bool(self.programa)


def ruta_de_rnx2rtkp() -> str:
    """Lo configurado, luego junto a `convbin` (viven en el mismo paquete) y luego el `PATH`."""
    configurada = (getattr(settings, "RTKLIB_RNX2RTKP", "") or "").strip().strip('"')
    if configurada:
        return configurada
    convbin = (getattr(settings, "RTKLIB_CONVBIN", "") or "").strip().strip('"')
    if convbin:
        vecino = Path(convbin).with_name("rnx2rtkp" + Path(convbin).suffix)
        if vecino.is_file():
            return str(vecino)
    return shutil.which("rnx2rtkp") or ""


def sondar() -> Disponible:
    """Si esta máquina tiene `rnx2rtkp`. **No lo ejecuta** (una sonda no corre una conversión)."""
    ruta = ruta_de_rnx2rtkp()
    if not ruta:
        return Disponible(
            motivo="Esta máquina no tiene RTKLIB (rnx2rtkp), que es lo que corrige la trayectoria.",
            sugerencia=(
                "Es de código abierto (BSD-2). En Ubuntu: «sudo apt install rtklib». Si no está en "
                "el PATH, ponga su ruta en AEROCONVERT_RTKLIB_RNX2RTKP."
            ),
        )
    if not Path(ruta).is_file():
        return Disponible(
            motivo=f"AEROCONVERT_RTKLIB_RNX2RTKP apunta a {ruta}, y ahí no hay ningún archivo."
        )
    return Disponible(programa=ruta)


# --- Mirar los RINEX antes de lanzar -------------------------------------------------------


@dataclass(frozen=True)
class CabeceraRinex:
    nombre: str
    version: str
    tipo: str  # «O» observación, «N» navegación
    posicion_aproximada: tuple[float, float, float] | None
    receptor: str
    primera_observacion: str
    intervalo_s: float | None
    ultima_observacion: str = ""

    @property
    def desde(self) -> datetime | None:
        return hora_de_rinex(self.primera_observacion)

    @property
    def hasta(self) -> datetime | None:
        return hora_de_rinex(self.ultima_observacion)


def hora_de_rinex(texto: str) -> datetime | None:
    """`2025 12 29 15 40 0.0000000` (lo que trae `TIME OF FIRST/LAST OBS`) como fecha, o `None`."""
    campos = (texto or "").split()
    if len(campos) < 6:
        return None
    try:
        segundos = float(campos[5])
        return datetime(*(int(c) for c in campos[:5]), int(segundos)) + timedelta(
            microseconds=round((segundos - int(segundos)) * 1_000_000)
        )
    except ValueError:
        return None


_ETIQUETA = slice(60, 80)


def leer_cabecera(ruta: str | Path) -> CabeceraRinex:
    """La cabecera de un RINEX. Rechaza lo vacío, lo binario y lo que no es RINEX, con motivo."""
    ruta = Path(ruta)
    try:
        crudo = ruta.read_bytes()[:200_000]
    except OSError as fallo:
        raise ComposicionInvalida(f"{ruta.name} no se pudo abrir: {fallo}") from fallo
    if not crudo.strip():
        raise ComposicionInvalida(f"{ruta.name} está vacío.")
    if b"\x00" in crudo[:4096]:
        raise ComposicionInvalida(
            f"{ruta.name} es un archivo binario, no un RINEX. Pásele antes por «Datos de un "
            "receptor GNSS a RINEX»."
        )
    lineas = crudo.decode("latin-1").splitlines()
    primera = lineas[0] if lineas else ""
    if "RINEX VERSION / TYPE" not in primera[_ETIQUETA]:
        raise ComposicionInvalida(
            f"{ruta.name} no empieza con una cabecera RINEX (falta «RINEX VERSION / TYPE»)."
        )
    version = primera[:9].strip()
    tipo = primera[20:21].strip().upper()
    if tipo == "N" or "NAV" in primera[20:40].upper():
        tipo = "N"
    elif "OBS" in primera[20:40].upper():
        tipo = "O"
    if not re.fullmatch(r"\d\.\d{2}", version) or version not in VERSIONES_ADMITIDAS:
        raise ComposicionInvalida(
            f"{ruta.name} es RINEX {version or '?'}: se leen "
            + ", ".join(VERSIONES_ADMITIDAS)
            + "."
        )

    posicion = None
    receptor = primera_obs = ultima_obs = ""
    intervalo = None
    for linea in lineas[1:]:
        etiqueta = linea[_ETIQUETA].strip()
        if etiqueta == "END OF HEADER":
            break
        if etiqueta == "APPROX POSITION XYZ":
            try:
                x, y, z = (float(v) for v in linea[:42].split())
                posicion = (x, y, z)
            except ValueError:
                posicion = None
        elif etiqueta == "REC # / TYPE / VERS":
            receptor = linea[20:40].strip()
        elif etiqueta == "TIME OF FIRST OBS":
            primera_obs = " ".join(linea[:43].split())
        elif etiqueta == "TIME OF LAST OBS":
            ultima_obs = " ".join(linea[:43].split())
        elif etiqueta == "INTERVAL":
            try:
                intervalo = float(linea[:10])
            except ValueError:
                intervalo = None
    return CabeceraRinex(
        ruta.name, version, tipo, posicion, receptor, primera_obs, intervalo, ultima_obs
    )


def distancia_a_la_base_m(cabecera: CabeceraRinex, base: Base) -> float | None:
    """Metros entre la coordenada declarada y el `APPROX POSITION` del RINEX; `None` si no hay."""
    if cabecera.posicion_aproximada is None or cabecera.posicion_aproximada == (0.0, 0.0, 0.0):
        return None
    from pyproj import Transformer

    a_ecef = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)
    bx, by, bz = a_ecef.transform(base.lon, base.lat, base.alt_elipsoidal_m)
    x, y, z = cabecera.posicion_aproximada
    return math.dist((bx, by, bz), (x, y, z))


@dataclass
class Revision:
    rover: CabeceraRinex
    base: CabeceraRinex
    navegacion: list[CabeceraRinex]
    distancia_base_m: float | None
    avisos: list[str] = field(default_factory=list)


def revisar(rover, base_obs, navegacion: list, base: Base) -> Revision:
    """Que los archivos sean los que dicen ser **antes** de gastar minutos de RTKLIB."""
    c_rover = leer_cabecera(rover)
    c_base = leer_cabecera(base_obs)
    c_nav = [leer_cabecera(n) for n in navegacion]
    if c_rover.tipo != "O":
        raise ComposicionInvalida(f"{c_rover.nombre} no es de observación: el del dron lo es.")
    if c_base.tipo != "O":
        raise ComposicionInvalida(f"{c_base.nombre} no es de observación: el de la base lo es.")
    if not c_nav:
        raise ComposicionInvalida("Falta el archivo de efemérides (navegación).")
    for n in c_nav:
        if n.tipo != "N":
            raise ComposicionInvalida(f"{n.nombre} no es de navegación (efemérides).")

    avisos: list[str] = []
    distancia = distancia_a_la_base_m(c_base, base)
    if distancia is None:
        avisos.append(
            f"{c_base.nombre} no trae la posición aproximada de la estación: no se pudo comprobar "
            "la coordenada declarada de la base contra el archivo."
        )
    elif distancia > DISTANCIA_MAXIMA_BASE_M:
        raise ComposicionInvalida(
            f"La base declarada está a {distancia / 1000:.1f} km de donde dice estar "
            f"{c_base.nombre}. "
            "Es el error de siempre: una estación equivocada, una zona o un signo. Corrija la "
            "coordenada antes de correr nada."
        )
    return Revision(c_rover, c_base, c_nav, distancia, avisos)


# --- La orden ------------------------------------------------------------------------------


def construir_orden(
    programa: str | list[str],
    *,
    rover,
    base_obs,
    navegacion: list,
    salida,
    base: Base,
    opciones: Opciones | None = None,
) -> list[str]:
    """La lista de argumentos de `rnx2rtkp`. **Pura**: se prueba sin RTKLIB."""
    opciones = opciones or Opciones()
    opciones.validar()
    prefijo = [programa] if isinstance(programa, str) else list(programa)
    orden = [
        *prefijo,
        "-p", MODOS[opciones.modo],
        "-m", str(opciones.mascara_elevacion_deg),
        "-sys", ",".join(s.strip().upper() for s in opciones.sistemas.split(",") if s.strip()),
        "-f", str(opciones.frecuencias),
        "-v", f"{opciones.umbral_ambiguedad:g}",
        # Hora en calendario y en GPST, la que lee `vuelo_pos`; por omisión RTKLIB escribe
        # semana y segundo, y las posiciones en grados decimales.
        "-t",
        "-d", "3",
    ]  # fmt: skip
    if opciones.intervalo_s is not None:
        orden += ["-ti", f"{opciones.intervalo_s:g}"]
    if opciones.combinada:
        orden.append("-c")
    orden += ["-l", f"{base.lat:.9f}", f"{base.lon:.9f}", f"{base.alt_elipsoidal_m:.4f}"]
    orden += ["-o", str(Path(salida).resolve())]
    # Rover primero y base después, como lo pide RTKLIB; luego las efemérides. Rutas absolutas:
    # una que empezara por «-» se leería como opción.
    orden += [str(Path(rover).resolve()), str(Path(base_obs).resolve())]
    orden += [str(Path(n).resolve()) for n in navegacion]
    return orden


@dataclass
class Resultado:
    trayectoria: vuelo_pos.Trayectoria
    revision: Revision
    mensajes: list[str]  # lo último que dijo RTKLIB

    @property
    def porcentaje_fijo(self) -> float:
        return self.trayectoria.porcentaje(1)


#: Lo que `rnx2rtkp` escribe en stderr mientras trabaja, con retornos de carro entre línea y línea:
#: `processing : 2025/12/29 15:40:00.0 Q=1 ns=14`.
_PROCESANDO = re.compile(
    r"processing\s*:\s*(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)(?:\s+Q=(\d))?"
)

#: Cuánto tiene que avanzar la barra para que valga la pena avisar (RTKLIB escribe una línea por
#: época: a 5 Hz son miles).
PASO_MINIMO_DE_AVANCE = 0.01

#: Una «línea» de stderr sin salto ni retorno de carro no puede crecer sin fin en memoria.
TOPE_DE_LINEA_B = 64 * 1024

#: Cada cuánto despierta el hilo principal a entregar el avance y a mirar el plazo.
SONDEO_S = 0.2


def _fraccion(hora: datetime, desde: datetime | None, hasta: datetime | None) -> float | None:
    if desde is None or hasta is None or hasta <= desde:
        return None
    return max(0.0, min(1.0, (hora - desde).total_seconds() / (hasta - desde).total_seconds()))


def _hora_de_linea(encontrada: re.Match) -> tuple[datetime, int | None] | None:
    """La hora y la calidad de una línea `processing`, o `None` si no es una hora de verdad
    (un `15:59:60` por un segundo intercalar, un mes 13…): se descarta, no se cae."""
    y, mo, d, h, mi, s, q = encontrada.groups()
    try:
        hora = datetime(int(y), int(mo), int(d), int(h), int(mi), int(float(s)))
    except ValueError:
        return None
    return hora, (int(q) if q is not None else None)


def _leer_avance(flujo, mensajes: deque, avances: queue.Queue) -> None:
    """Vacía el stderr de RTKLIB **sin parar**: guarda lo que no es la barra y **encola** el resto.

    Este hilo no llama a nadie ni calcula nada que pueda fallar fuera de lo previsto: si se
    muriera, nadie vaciaría el pipe y `rnx2rtkp` se bloquearía hasta el plazo. Quien entrega el
    avance es el hilo principal.
    """
    pendiente = b""
    while True:
        trozo = flujo.read1(4096) if hasattr(flujo, "read1") else flujo.read(4096)
        if not trozo:
            break
        pendiente += trozo
        *lineas, pendiente = re.split(rb"[\r\n]", pendiente)
        pendiente = pendiente[-TOPE_DE_LINEA_B:]
        for cruda in lineas:
            linea = cruda.decode("utf-8", errors="replace").strip()
            if not linea:
                continue
            encontrada = _PROCESANDO.search(linea)
            if not encontrada:
                mensajes.append(linea)  # lo que no es la barra: avisos y errores de RTKLIB
                continue
            hora = _hora_de_linea(encontrada)
            if hora is not None and avances.qsize() < 10_000:
                avances.put(hora)
    resto = pendiente.decode("utf-8", errors="replace").strip()
    if resto and not _PROCESANDO.search(resto):
        mensajes.append(resto)


class _Avisador:
    """Convierte las horas que dice RTKLIB en llamadas a `progreso`, en el hilo de quien llama.

    Nunca baja, avisa solo si la barra avanzó lo suficiente y, si `progreso` lanza, deja de
    llamarlo: un fallo de la barra no puede tumbar el cálculo.
    """

    def __init__(self, progreso, desde, hasta) -> None:
        self.progreso = progreso
        self.desde = desde
        self.hasta = hasta
        self.ultima = -1.0
        self.roto = False

    def entregar(self, avances: queue.Queue) -> None:
        while True:
            try:
                hora, q = avances.get_nowait()
            except queue.Empty:
                return
            if self.progreso is None or self.roto:
                continue
            fraccion = _fraccion(hora, self.desde, self.hasta)
            etiqueta = f"RTKLIB va en {hora:%Y-%m-%d %H:%M:%S} GPST"
            if q is not None:
                etiqueta += f" ({vuelo_pos.CALIDADES.get(q, 'sin calidad')})"
            if fraccion is not None:
                if fraccion - self.ultima < PASO_MINIMO_DE_AVANCE:
                    continue
                self.ultima = fraccion
            # Sin hora de fin no hay fracción: solo se dice dónde va.
            self._avisar(fraccion, etiqueta)

    def _avisar(self, fraccion, etiqueta) -> None:
        try:
            self.progreso(fraccion, etiqueta)
        except Exception:  # noqa: BLE001 - el avance es un adorno: no tumba el cálculo
            self.roto = True


def _matar(proceso: subprocess.Popen) -> None:
    """Mata a RTKLIB **y a lo que haya lanzado** (un envoltorio `.cmd` o `sh` tiene un nieto)."""
    if os.name == "nt":
        subprocess.run(  # nosec B603 B607 - orden fija, solo el PID de nuestro propio proceso
            ["taskkill", "/T", "/F", "/PID", str(proceso.pid)],
            capture_output=True,
            check=False,
            timeout=30,
        )
    else:
        try:
            os.killpg(proceso.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    if proceso.poll() is None:
        proceso.kill()


def correr(
    programa: str | list[str],
    *,
    rover,
    base_obs,
    navegacion: list,
    destino,
    base: Base,
    opciones: Opciones | None = None,
    plazo_s: int = TIEMPO_MAXIMO_S,
    progreso: Callable[[float | None, str], None] | None = None,
) -> Resultado:
    """Lanza RTKLIB y devuelve la trayectoria **leída del `.pos`**, no del código de salida.

    `progreso(fraccion, etiqueta)` se llama con lo que RTKLIB dice en stderr: la fracción sale de
    la hora que va procesando entre la primera y la última observación del dron, y es `None` si el
    RINEX no trae la última. Nunca baja, y se llama desde el hilo de quien llama a `correr`.
    """
    revision = revisar(rover, base_obs, navegacion, base)
    destino = Path(destino)
    with tempfile.TemporaryDirectory(prefix="ppk_") as carpeta:
        pos = Path(carpeta) / "trayectoria.pos"
        orden = construir_orden(
            programa,
            rover=rover,
            base_obs=base_obs,
            navegacion=navegacion,
            salida=pos,
            base=base,
            opciones=opciones,
        )
        mensajes_vivos: deque[str] = deque(maxlen=6)
        avances: queue.Queue = queue.Queue()
        # Un grupo de procesos propio, para poder alcanzar al nieto si el programa es un envoltorio.
        grupo = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        try:
            proceso = subprocess.Popen(  # nosec B603 - lista de argumentos, sin shell, rutas absolutas
                orden,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env={**os.environ, "LC_ALL": "C"},
                **grupo,
            )
        except OSError as fallo:
            raise ComposicionInvalida(f"No se pudo lanzar RTKLIB: {fallo}") from fallo

        lector = threading.Thread(
            target=_leer_avance, args=(proceso.stderr, mensajes_vivos, avances), daemon=True
        )
        lector.start()
        avisador = _Avisador(progreso, revision.rover.desde, revision.rover.hasta)
        limite = time.monotonic() + plazo_s
        try:
            while proceso.poll() is None:
                if time.monotonic() >= limite:
                    _matar(proceso)
                    proceso.wait()
                    raise ComposicionInvalida(
                        f"RTKLIB tardó más de {plazo_s // 60} minutos y se detuvo. Con una base "
                        "lejana o un vuelo muy largo conviene un intervalo mayor."
                    )
                avisador.entregar(avances)
                try:
                    proceso.wait(timeout=SONDEO_S)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            # Una cancelación o un Ctrl+C no dejan a RTKLIB huérfano.
            if proceso.poll() is None:
                _matar(proceso)
                proceso.wait()
            lector.join(timeout=10)  # un nieto que retenga el pipe no puede colgar al trabajo
            if proceso.stderr is not None:
                proceso.stderr.close()
        avisador.entregar(avances)

        mensajes = list(mensajes_vivos)
        # **El código de salida no es la prueba.** Lo que cuenta es lo que quedó escrito.
        if not pos.exists() or pos.stat().st_size == 0:
            raise ComposicionInvalida(
                "RTKLIB no escribió ninguna posición."
                + (f" Dijo: {' | '.join(mensajes)}" if mensajes else "")
            )
        texto = pos.read_text(encoding="utf-8", errors="replace")
        trayectoria = vuelo_pos.leer(texto)  # levanta si no es un .pos legible
        destino.write_text(texto, encoding="utf-8")
    return Resultado(trayectoria, revision, mensajes)
