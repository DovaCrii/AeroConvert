"""Un video de dron: sacar fotogramas para fotogrametría, comprimirlo, recortarlo o quitarle el
audio (F14.17). Con **FFmpeg**, programa externo sondeado y ejecutado aparte (D1).

## Fotogramas cada N segundos **o cada N metros**

Para reconstruir un modelo desde un video importa la **separación entre tomas**, no el reloj: un
dron que se detiene a girar daría veinte fotos casi iguales cada segundo. Con el `.SRT` de DJI (la
posición de cada fotograma, ver `telemetria.py`) se eligen los instantes en que el dron **avanzó N
metros** sobre el elipsoide (`pyproj.Geod`), y cada fotograma lleva en su EXIF la posición
interpolada en ese instante. **La altura no se escribe en el EXIF**: la del SRT es de la cámara y su
referencia no está declarada (regla 3); va en el CSV con esa advertencia.

## Lo que se comprueba, con otro lector

`ffprobe` mira lo que escribió FFmpeg: duración, códec, resolución y si quedó audio. Los fotogramas
los abre Pillow, y tienen que ser tantos como instantes se pidieron.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess  # nosec B404 - FFmpeg y ffprobe se lanzan con lista de argumentos
from dataclasses import dataclass
from pathlib import Path

from .composicion import ComposicionInvalida

SEGUNDOS_DE_CACHE = 600
CLAVE_DE_CACHE = "documentos:ffmpeg"

OPERACIONES = {
    "fotogramas": "Sacar fotogramas para fotogrametría",
    "comprimir": "Comprimir (H.264, menos peso)",
    "recortar": "Recortar un tramo",
    "sin_audio": "Quitar el audio",
    "a_mp4": "Pasar a MP4 (H.264)",
}

CADA_SEGUNDOS = (1, 2, 5, 10)
CADA_METROS = (5, 10, 20, 50)

#: Un video de veinte minutos a un fotograma por segundo son 1.200: más que esto no es una
#: secuencia para fotogrametría, es el video entero en JPG.
MAXIMO_FOTOGRAMAS = 2000

EXTENSIONES = frozenset({".mp4", ".mov", ".m4v", ".mkv", ".avi"})


@dataclass(frozen=True)
class Disponible:
    ffmpeg: str = ""
    ffprobe: str = ""
    motivo: str = ""
    sugerencia: str = ""

    def __bool__(self) -> bool:
        return bool(self.ffmpeg and self.ffprobe)


def sondar(*, recordar: bool = True) -> Disponible:
    """Dónde están FFmpeg y ffprobe (los dos: uno escribe y el otro comprueba)."""
    from django.conf import settings
    from django.core.cache import cache

    if recordar:
        guardado = cache.get(CLAVE_DE_CACHE)
        if guardado is not None:
            return guardado
    configurado = (getattr(settings, "FFMPEG", "") or "").strip().strip('"')
    ffmpeg = configurado if configurado and Path(configurado).is_file() else ""
    ffmpeg = ffmpeg or shutil.which("ffmpeg") or ""
    ffprobe = ""
    if ffmpeg:
        hermano = Path(ffmpeg).with_name(Path(ffmpeg).name.replace("ffmpeg", "ffprobe"))
        ffprobe = str(hermano) if hermano.is_file() else (shutil.which("ffprobe") or "")
    if ffmpeg and ffprobe:
        estado = Disponible(ffmpeg=ffmpeg, ffprobe=ffprobe)
    else:
        estado = Disponible(
            motivo=(
                "Esta máquina no tiene FFmpeg (o le falta ffprobe), que es lo que trabaja el video."
            ),
            sugerencia="En el servidor: sudo despliegue/instalar_faltantes.sh.",
        )
    if recordar:
        cache.set(CLAVE_DE_CACHE, estado, SEGUNDOS_DE_CACHE)
    return estado


# --- Leer lo que hay (ffprobe) -------------------------------------------------------------------


@dataclass(frozen=True)
class Ficha:
    duracion_s: float
    codec: str
    ancho: int
    alto: int
    con_audio: bool


def probar(ffprobe: str, ruta: Path) -> Ficha:
    """Lo que dice `ffprobe` del archivo. Levanta si no es un video que se pueda leer."""
    try:
        resultado = subprocess.run(  # nosec B603
            [ffprobe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
             str(ruta)],
            capture_output=True, text=True, errors="replace", timeout=60, check=False,
        )  # fmt: skip
        datos = json.loads(resultado.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as fallo:
        raise ComposicionInvalida(f"ffprobe no pudo leer {ruta.name}: {fallo}") from fallo
    flujos = datos.get("streams") or []
    video = next((f for f in flujos if f.get("codec_type") == "video"), None)
    if video is None:
        raise ComposicionInvalida(f"{ruta.name} no trae ninguna pista de video.")
    try:
        duracion = float((datos.get("format") or {}).get("duration") or video.get("duration") or 0)
    except ValueError:
        duracion = 0.0
    return Ficha(
        duracion_s=duracion,
        codec=str(video.get("codec_name") or ""),
        ancho=int(video.get("width") or 0),
        alto=int(video.get("height") or 0),
        con_audio=any(f.get("codec_type") == "audio" for f in flujos),
    )


# --- Qué instantes -------------------------------------------------------------------------


def instantes_por_tiempo(duracion_s: float, cada_s: float) -> list[float]:
    if cada_s <= 0:
        raise ComposicionInvalida("El intervalo tiene que ser mayor que cero.")
    instantes, t = [], 0.0
    while t < duracion_s - 1e-6:
        instantes.append(round(t, 3))
        t += cada_s
    return instantes


def instantes_por_distancia(puntos, cada_m: float) -> list[float]:
    """Los instantes en que el dron lleva recorridos 0, N, 2N… metros (sobre el elipsoide).

    Entre dos puntos del SRT se interpola en el tiempo: el instante en que se cruza cada múltiplo
    de N cae donde corresponde, no en el punto siguiente.
    """
    from pyproj import Geod

    if cada_m <= 0:
        raise ComposicionInvalida("La distancia entre fotogramas tiene que ser mayor que cero.")
    if len(puntos) < 2:
        raise ComposicionInvalida("El SRT trae menos de dos posiciones: no hay recorrido.")
    geod = Geod(ellps="WGS84")
    instantes = [puntos[0].t_s]
    recorrido = 0.0
    siguiente = cada_m
    for a, b in zip(puntos, puntos[1:], strict=False):
        _, _, tramo = geod.inv(a.lon, a.lat, b.lon, b.lat)
        while tramo > 0 and recorrido + tramo >= siguiente:
            fraccion = (siguiente - recorrido) / tramo
            instantes.append(round(a.t_s + fraccion * (b.t_s - a.t_s), 3))
            siguiente += cada_m
        recorrido += tramo
    return instantes


def posicion_en(puntos, t_s: float) -> tuple[float, float, float | None] | None:
    """La posición interpolada en `t_s`, o `None` fuera del tramo con posiciones."""
    if not puntos or t_s < puntos[0].t_s - 0.5 or t_s > puntos[-1].t_s + 0.5:
        return None
    for a, b in zip(puntos, puntos[1:], strict=False):
        if a.t_s <= t_s <= b.t_s:
            f = 0.0 if b.t_s == a.t_s else (t_s - a.t_s) / (b.t_s - a.t_s)
            alt = None
            if a.alt is not None and b.alt is not None:
                alt = a.alt + f * (b.alt - a.alt)
            return a.lat + f * (b.lat - a.lat), a.lon + f * (b.lon - a.lon), alt
    cercano = min(puntos, key=lambda p: abs(p.t_s - t_s))
    return cercano.lat, cercano.lon, cercano.alt


# --- Las órdenes ----------------------------------------------------------------------------------


def plan_fotograma(ffmpeg: str, video: Path, t_s: float, salida: Path) -> list[str]:
    return [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{t_s:.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(salida),
    ]  # fmt: skip


def plan_operacion(
    ffmpeg: str,
    operacion: str,
    video: Path,
    destino: Path,
    *,
    inicio_s: float | None = None,
    fin_s: float | None = None,
) -> list[str]:
    base = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    if operacion == "recortar":
        if inicio_s is None or fin_s is None or not 0 <= inicio_s < fin_s:
            raise ComposicionInvalida("Para recortar hace falta un inicio menor que el fin.")
        # Recodificado, no `-c copy`: copiar corta en el fotograma clave más cercano y el tramo
        # sale segundos más largo o más corto que el pedido.
        return [*base, "-ss", f"{inicio_s:.3f}", "-to", f"{fin_s:.3f}", "-i", str(video),
                "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-c:a", "aac",
                "-movflags", "+faststart", str(destino)]  # fmt: skip
    if operacion == "sin_audio":
        return [*base, "-i", str(video), "-map", "0:v", "-c:v", "copy", "-an", str(destino)]
    if operacion == "comprimir":
        return [*base, "-i", str(video), "-c:v", "libx264", "-crf", "28", "-preset", "medium",
                "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(destino)]  # fmt: skip
    if operacion == "a_mp4":
        return [*base, "-i", str(video), "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                "-c:a", "aac", "-movflags", "+faststart", str(destino)]  # fmt: skip
    raise ComposicionInvalida(f"«{operacion}» no es una operación de las que se ofrecen.")


def _lanzar(orden: list[str], que: str, timeout_s: int) -> None:
    try:
        resultado = subprocess.run(  # nosec B603
            orden, capture_output=True, text=True, errors="replace", timeout=timeout_s, check=False
        )
    except subprocess.TimeoutExpired as fallo:
        raise ComposicionInvalida(f"FFmpeg lleva {timeout_s} s sin terminar {que}.") from fallo
    if resultado.returncode != 0:
        queja = (resultado.stderr or "").strip().splitlines()
        raise ComposicionInvalida(
            f"FFmpeg falló al {que}. {queja[-1][:300] if queja else ''}".strip()
        )


def operar(
    ffmpeg: str, operacion: str, video: Path, destino: Path, *, timeout_s: int = 3000, **rango
) -> None:
    """Hace la operación y deja el resultado en `destino`. Lo comprueba quien llama, con ffprobe."""
    _lanzar(
        plan_operacion(ffmpeg, operacion, video, destino, **rango), "trabajar el video", timeout_s
    )
    if not destino.is_file() or destino.stat().st_size == 0:
        destino.unlink(missing_ok=True)
        raise ComposicionInvalida("FFmpeg terminó sin escribir el video.")


def extraer_fotogramas(
    ffmpeg: str,
    video: Path,
    carpeta: Path,
    instantes: list[float],
    *,
    puntos=None,
    progreso=None,
) -> tuple[list[Path], str]:
    """Un JPG por instante, con la posición en el EXIF si hay SRT. Devuelve (archivos, csv)."""
    from .vuelo_exif import poner_posicion

    if not instantes:
        raise ComposicionInvalida("No hay ningún instante del que sacar un fotograma.")
    if len(instantes) > MAXIMO_FOTOGRAMAS:
        raise ComposicionInvalida(
            f"Saldrían {len(instantes)} fotogramas y el tope es {MAXIMO_FOTOGRAMAS}: elija un "
            "intervalo mayor."
        )
    carpeta.mkdir(parents=True, exist_ok=True)
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\n")
    escritor.writerow(["fotograma", "t_s", "lat", "lon", "altura_srt_m"])
    archivos: list[Path] = []
    for i, t in enumerate(instantes, start=1):
        archivo = carpeta / f"fotograma_{i:05d}.jpg"
        _lanzar(plan_fotograma(ffmpeg, video, t, archivo), f"sacar el fotograma {i}", 120)
        if not archivo.is_file() or archivo.stat().st_size == 0:
            raise ComposicionInvalida(f"FFmpeg no escribió el fotograma {i} (t = {t:.3f} s).")
        posicion = posicion_en(puntos, t) if puntos else None
        if posicion is not None:
            lat, lon, alt = posicion
            # Sin altura en el EXIF: la del SRT no declara su referencia (regla 3).
            archivo.write_bytes(poner_posicion(archivo.read_bytes(), lat, lon, None, "WGS-84"))
            escritor.writerow([archivo.name, f"{t:.3f}", f"{lat:.8f}", f"{lon:.8f}",
                               "" if alt is None else f"{alt:.2f}"])  # fmt: skip
        else:
            escritor.writerow([archivo.name, f"{t:.3f}", "", "", ""])
        archivos.append(archivo)
        if progreso is not None and (i % 10 == 0 or i == len(instantes)):
            progreso(i / len(instantes), f"Fotograma {i} de {len(instantes)}")
    return archivos, salida.getvalue()
