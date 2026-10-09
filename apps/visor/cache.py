"""La caché de teselas en disco: acotada, barrida y escrita sin dejar nada a medias.

## Por qué en disco y no en la memoria de Django

Una tesela PNG pesa entre 5 y 150 KB y un recorrido por una ortofoto pide cientos. Tenerlas en
memoria compite con GDAL; tenerlas en disco sobrevive a un reinicio del servidor y las comparten
todos los obreros de gunicorn.

## Cómo se acota

El tope es `VISOR_CACHE_MAX_MB`. Se barre de dos maneras: **solo**, cuando lo escrito desde el
último barrido pasa de un veinteavo del tope (así nunca se llega a pasar el tope por mucho), y por
**el barrido de la aplicación** (`apps/jobs/retencion.py`) o a mano con
`manage.py barrer_teselas`. Cuando se barre, se borran **las que hace más tiempo que nadie mira**
(LRU por fecha de modificación, que se refresca en cada acierto) hasta quedar en el 80 % del tope.

## Cómo se escribe (regla 5)

Siempre a `<destino>.parcial-<id>` y solo se renombra con `os.replace()` después de verificar la
salida. Dos peticiones de la misma tesela a la vez escriben cada una su parcial y gana la última,
que es idéntica. Un parcial que sobrevive a un proceso muerto lo borra el barrido.

## La clave

`sha256(ruta | tamaño | mtime_ns | versión)`: si el archivo cambia, la clave cambia y las teselas
viejas dejan de pedirse (y envejecen hasta que el barrido las borra). Es además la base del `ETag`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

registro = logging.getLogger(__name__)

#: Se cambia cuando cambia **lo que sale** (argumentos de `gdalwarp`, formato de la ficha): invalida
#: toda la caché sin tener que borrarla a mano.
VERSION = "2"  # 2: la ficha trae lo del terreno (F19.4); la «1» no sabía que un DEM lo es

#: Hasta qué fracción del tope se baja al barrer. Bajar solo hasta el tope haría barrer en cada
#: escritura.
FRACCION_AL_BARRER = 0.8

#: Un parcial más viejo que esto no lo está escribiendo nadie.
EDAD_DE_UN_PARCIAL_S = 3600

MARCA_PARCIAL = ".parcial-"

_cerrojo_de_barrido = threading.Lock()
_escrito_desde_el_barrido = 0


def carpeta() -> Path:
    """Donde vive la caché. Se crea al pedirla."""
    configurada = (getattr(settings, "VISOR_CACHE", "") or "").strip().strip('"')
    ruta = Path(configurada) if configurada else Path(settings.BASE_DIR) / "cache-visor"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def tope_bytes() -> int:
    return max(1, int(getattr(settings, "VISOR_CACHE_MAX_MB", 512))) * 1024 * 1024


def clave_de(ruta: Path) -> str:
    """La clave de un archivo en su estado de ahora. Levanta `OSError` si no se puede mirar."""
    datos = ruta.stat()
    huella = f"{ruta}|{datos.st_size}|{datos.st_mtime_ns}|{VERSION}"
    return hashlib.sha256(huella.encode("utf-8")).hexdigest()[:32]


def carpeta_de(clave: str) -> Path:
    return carpeta() / clave[:2] / clave


def leer(ruta: Path) -> bytes | None:
    """El contenido si existe, y **se anota que se ha mirado** (es lo que ordena el barrido)."""
    try:
        contenido = ruta.read_bytes()
        os.utime(ruta, None)
    except OSError:
        return None
    return contenido


def tocar(ruta: Path) -> None:
    """Anota que se ha mirado un archivo de la caché (lo que ordena el barrido) sin leerlo."""
    try:
        os.utime(ruta, None)
    except OSError:
        pass


def nombre_de_parcial(destino: Path) -> Path:
    """Un nombre de trabajo único, junto al destino (mismo volumen: `os.replace` es atómico)."""
    return destino.with_name(f"{destino.name}{MARCA_PARCIAL}{uuid.uuid4().hex[:8]}")


def escribir(destino: Path, contenido: bytes) -> None:
    """Escribe de golpe: parcial y renombrado. Nadie lee jamás una tesela a medias."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = nombre_de_parcial(destino)
    try:
        parcial.write_bytes(contenido)
        reemplazar(parcial, destino)
    finally:
        parcial.unlink(missing_ok=True)
    anotar_escritura(len(contenido))


def reemplazar(parcial: Path, destino: Path) -> None:
    """`os.replace()` que tolera que otro hilo esté leyendo el destino (Windows no lo deja).

    Si el destino ya existe y no se pudo reemplazar es porque alguien más acaba de dejar **el mismo
    contenido** (la clave lo determina todo), así que sirve.
    """
    try:
        os.replace(parcial, destino)
    except OSError:
        if not destino.is_file():
            raise


def anotar_escritura(nbytes: int) -> None:
    """Cuenta lo escrito y, si ya es mucho, barre. Barrer **no** debe romper una petición."""
    global _escrito_desde_el_barrido
    _escrito_desde_el_barrido += nbytes
    if _escrito_desde_el_barrido >= tope_bytes() // 20:
        _escrito_desde_el_barrido = 0
        try:
            barrer()
        except OSError:  # un disco que falla no puede tumbar la tesela que se está sirviendo
            registro.warning("No se pudo barrer la caché de teselas.", exc_info=True)


@dataclass
class Barrido:
    archivos_borrados: int = 0
    bytes_liberados: int = 0
    bytes_antes: int = 0
    bytes_despues: int = 0
    parciales_borrados: int = 0

    def __str__(self) -> str:
        return (
            f"{self.archivos_borrados} archivos de la caché de teselas "
            f"({self.bytes_liberados / 1e6:.1f} MB liberados; "
            f"{self.bytes_antes / 1e6:.1f} MB antes, {self.bytes_despues / 1e6:.1f} MB después)"
        )


#: Lo único que esta caché escribe: `<2 hex>/<32 hex>/<z-x-y.png | capa.json | fuente.vrt>`, lo del
#: terreno (F19.4: `sombra-<8 hex>-z-x-y.png`, `cota-<8 hex>-z-x-y.png`, el sombreado entero
#: `sombra-<8 hex>.tif` y los colores `cota-<8 hex>.txt`) y sus parciales. **El barrido borra solo
#: esto**: si `AEROCONVERT_VISOR_CACHE` apuntara por error a una carpeta con otras cosas, no se les
#: toca.
PATRON_PROPIO = re.compile(
    r"^[0-9a-f]{2}[\\/][0-9a-f]{32}[\\/]"
    r"((?:(?:sombra|cota)-[0-9a-f]{8}-)?\d+-\d+-\d+\.png"
    r"|(?:sombra|cota)-[0-9a-f]{8}\.(?:tif|txt)"
    r"|capa\.json|fuente\.vrt)"
    r"(\.parcial-[0-9a-f]{8})?$"
)


def _archivos() -> list[tuple[float, int, Path]]:
    """`(fecha de modificación, bytes, ruta)` de lo que **es de la caché**."""
    encontrados = []
    base = carpeta()
    for ruta in base.rglob("*"):
        try:
            if ruta.is_file() and PATRON_PROPIO.match(str(ruta.relative_to(base))):
                datos = ruta.stat()
                encontrados.append((datos.st_mtime, datos.st_size, ruta))
        except OSError:
            continue
    return encontrados


def usado_bytes() -> int:
    return sum(tamano for _, tamano, _ in _archivos())


def barrer(tope: int | None = None, *, simular: bool = False) -> Barrido:
    """Deja la caché por debajo del tope borrando lo menos mirado.

    Dos pasos: **primero los parciales viejos** (huérfanos de un proceso muerto), y después, si
    todavía pasa del tope, **los más antiguos** hasta el 80 %. `simular` cuenta lo que haría sin
    borrar nada.
    """
    limite = tope_bytes() if tope is None else max(0, tope)
    resultado = Barrido()
    if not _cerrojo_de_barrido.acquire(blocking=False):  # otro hilo ya está en ello
        return resultado
    try:
        todos = sorted(_archivos())
        resultado.bytes_antes = sum(tamano for _, tamano, _ in todos)
        ahora = time.time()
        restantes = []
        total = resultado.bytes_antes
        for fecha, tamano, ruta in todos:
            if MARCA_PARCIAL in ruta.name and ahora - fecha > EDAD_DE_UN_PARCIAL_S:
                if _borrar(ruta, simular):
                    resultado.parciales_borrados += 1
                    resultado.archivos_borrados += 1
                    resultado.bytes_liberados += tamano
                    total -= tamano
                continue
            restantes.append((fecha, tamano, ruta))

        if total > limite:
            objetivo = int(limite * FRACCION_AL_BARRER)
            for _fecha, tamano, ruta in restantes:  # ya vienen de la más vieja a la más nueva
                if total <= objetivo:
                    break
                if _borrar(ruta, simular):
                    resultado.archivos_borrados += 1
                    resultado.bytes_liberados += tamano
                    total -= tamano
        resultado.bytes_despues = total
        if not simular:
            _quitar_carpetas_vacias()
        return resultado
    finally:
        _cerrojo_de_barrido.release()


def _borrar(ruta: Path, simular: bool) -> bool:
    if simular:
        return True
    try:
        ruta.unlink()
    except OSError:  # en Windows, un archivo que GDAL tiene abierto no se deja borrar
        return False
    return True


def _quitar_carpetas_vacias() -> None:
    base = carpeta()
    for hija in sorted((p for p in base.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        try:
            hija.rmdir()  # solo borra si está vacía
        except OSError:
            continue
