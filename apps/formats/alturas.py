"""Alturas: elipsoidal ↔ ortométrica con un modelo de geoide **declarado** (F15.2).

La regla 3 de `AGENTS.md` dice que el CRS no se adivina. La referencia vertical es lo mismo, y
pesa más de lo que parece: entre EGM96 y EGM2008 hay decenas de centímetros en algunos lugares,
y quien exporta «altura» desde un programa de topografía no siempre dice cuál usó. Por eso:

- **El modelo no tiene valor por omisión.** Se declara (`geoide-no-declarado` si falta) y se
  responde por él: el recibo lo repite.
- **Las grillas se sondean, no se descargan.** Se buscan en `AEROCONVERT_PROJ_GRILLAS`, en el
  directorio de datos de pyproj, en el de QGIS y en `PROJ_DATA`. Si no está, la capacidad queda
  apagada con motivo (`sin-grilla-geoide`) y la alternativa dicha (regla 4). **Nunca se activa la
  red de PROJ**: se le pasa a PROJ la ruta exacta del archivo, de modo que ni siquiera podría
  bajar otro.
- **Ninguna función acepta un `(x, y)` pelado:** entra un `PuntoConCrs`, cuya `z_m` es la altura
  del tipo que se declara; el recibo dice la grilla usada (nombre, ruta y SHA-256) y el método.

El cálculo es `h = H + N`: `h` altura elipsoidal, `H` ortométrica y `N` la ondulación del
geoide que da la grilla en esa posición. Se hace con `+proj=vgridshift` de PROJ.
**El oráculo es `cs2cs` de PROJ** por la ruta de códigos EPSG (`EPSG:4979` ↔ `EPSG:4326+3855`), que
elige la grilla por su cuenta: dos caminos distintos hasta el mismo número.
"""

from __future__ import annotations

import glob
import hashlib
import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from .crs import PuntoConCrs

ELIPSOIDAL_A_ORTOMETRICA = "elipsoidal-a-ortometrica"
ORTOMETRICA_A_ELIPSOIDAL = "ortometrica-a-elipsoidal"
SENTIDOS = (ELIPSOIDAL_A_ORTOMETRICA, ORTOMETRICA_A_ELIPSOIDAL)

METODO = "PROJ vgridshift (h = H + N)"


class AlturaError(Exception):
    """Un motivo con código estable de `apps/jobs/motivos.py`."""

    def __init__(self, mensaje: str, codigo: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


@dataclass(frozen=True)
class ModeloGeoide:
    codigo: str
    nombre: str
    #: EPSG del sistema vertical «<modelo> height», el que usa el oráculo.
    epsg_vertical: int
    #: Nombres de archivo de la grilla en PROJ, en orden de preferencia.
    grillas: tuple[str, ...]


#: El catálogo es cerrado a propósito. PROJ no trae un geoide propio de Chile: el que usen en
#: Chile (p. ej. el de SIRGAS-Chile) hay que declararlo aparte y no se inventa aquí.
MODELOS: dict[str, ModeloGeoide] = {
    "EGM2008": ModeloGeoide("EGM2008", "EGM2008 (NGA, 2,5')", 3855, ("us_nga_egm08_25.tif",)),
    "EGM96": ModeloGeoide("EGM96", "EGM96 (NGA, 15')", 5773, ("us_nga_egm96_15.tif",)),
}


@dataclass(frozen=True)
class Grilla:
    nombre: str
    ruta: str
    sha256: str
    bytes_totales: int


@dataclass(frozen=True)
class Sondeo:
    """Si un modelo se puede usar aquí. Apagado = `motivo` con código y alternativa."""

    modelo: str
    disponible: bool
    grilla: Grilla | None = None
    motivo: str = ""
    mensaje: str = ""
    buscado_en: tuple[str, ...] = ()


@dataclass(frozen=True)
class Recibo:
    """Lo que hay que poder demostrar de una conversión de altura."""

    modelo: str
    modelo_nombre: str
    grilla: Grilla
    metodo: str
    sentido: str
    ondulacion_m: float
    altura_entrada_m: float
    altura_salida_m: float
    crs: str

    def como_dict(self) -> dict:
        return {
            "modelo": self.modelo,
            "modelo_nombre": self.modelo_nombre,
            "grilla": self.grilla.nombre,
            "grilla_sha256": self.grilla.sha256,
            "grilla_ruta": self.grilla.ruta,
            "metodo": self.metodo,
            "sentido": self.sentido,
            "ondulacion_m": self.ondulacion_m,
            "altura_entrada_m": self.altura_entrada_m,
            "altura_salida_m": self.altura_salida_m,
            "crs": self.crs,
        }

    def __str__(self) -> str:
        return (
            f"{self.sentido}: {self.altura_entrada_m:.3f} → {self.altura_salida_m:.3f} m "
            f"(N = {self.ondulacion_m:.3f} m), modelo {self.modelo}, grilla "
            f"{self.grilla.nombre} (sha256 {self.grilla.sha256[:12]}…), {self.metodo}"
        )


@dataclass(frozen=True)
class ResultadoAltura:
    punto: PuntoConCrs
    recibo: Recibo = field(compare=False)


def _modelo(codigo: str | None) -> ModeloGeoide:
    limpio = (codigo or "").strip().upper()
    if not limpio:
        raise AlturaError(
            "No se declaró el modelo de geoide: no hay uno por omisión.", "geoide-no-declarado"
        )
    if limpio not in MODELOS:
        raise AlturaError(
            f"El modelo de geoide «{codigo}» no está en el catálogo "
            f"({', '.join(sorted(MODELOS))}).",
            "geoide-desconocido",
        )
    return MODELOS[limpio]


def carpetas_de_grillas() -> list[Path]:
    """Dónde se buscan las grillas, en orden. Solo las carpetas que existen."""
    candidatas: list[str] = []
    configuradas = getattr(settings, "PROJ_GRILLAS", "") or ""
    candidatas += [c for c in configuradas.split(os.pathsep) if c.strip()]
    from pyproj import datadir

    candidatas.append(datadir.get_data_dir())
    for variable in ("PROJ_DATA", "PROJ_LIB"):
        candidatas += [c for c in os.environ.get(variable, "").split(os.pathsep) if c.strip()]
    candidatas += sorted(glob.glob(r"C:\Program Files\QGIS*\share\proj"), reverse=True)
    candidatas += ["/usr/share/proj"]

    vistas: list[Path] = []
    for texto in candidatas:
        carpeta = Path(texto.strip())
        if carpeta.is_dir() and carpeta not in vistas:
            vistas.append(carpeta)
    return vistas


@lru_cache(maxsize=16)
def _huella(ruta: str, tamano: int, mtime_ns: int) -> str:
    resumen = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def _grilla(ruta: Path) -> Grilla:
    estado = ruta.stat()
    return Grilla(
        nombre=ruta.name,
        ruta=str(ruta),
        sha256=_huella(str(ruta), estado.st_size, estado.st_mtime_ns),
        bytes_totales=estado.st_size,
    )


def sondear(modelo: str | None) -> Sondeo:
    """Busca la grilla del modelo. **No ejecuta nada ni baja nada.**"""
    try:
        elegido = _modelo(modelo)
    except AlturaError as fallo:
        return Sondeo(
            modelo=(modelo or "").strip().upper(),
            disponible=False,
            motivo=fallo.codigo,
            mensaje=str(fallo),
        )
    carpetas = carpetas_de_grillas()
    for carpeta in carpetas:
        for nombre in elegido.grillas:
            ruta = carpeta / nombre
            if ruta.is_file() and ruta.stat().st_size > 0:
                return Sondeo(elegido.codigo, True, grilla=_grilla(ruta))
    return Sondeo(
        modelo=elegido.codigo,
        disponible=False,
        motivo="sin-grilla-geoide",
        mensaje=(
            f"No está la grilla {' / '.join(elegido.grillas)} de {elegido.codigo} en: "
            f"{', '.join(str(c) for c in carpetas) or '(ninguna carpeta)'}."
        ),
        buscado_en=tuple(str(c) for c in carpetas),
    )


def sondear_todos() -> list[Sondeo]:
    return [sondear(codigo) for codigo in MODELOS]


def _a_grados(punto: PuntoConCrs) -> tuple[float, float]:
    """Longitud y latitud (EPSG:4326) de la posición horizontal. El CRS no se adivina."""
    if not punto.crs.conocido:
        raise AlturaError(
            "La posición no declara sistema de referencia: sin él no se sabe dónde buscar la "
            "ondulación del geoide.",
            "crs-ausente",
        )
    from pyproj import Transformer
    from pyproj.exceptions import CRSError

    try:
        a_wgs84 = Transformer.from_crs(str(punto.crs), "EPSG:4326", always_xy=True)
    except CRSError as fallo:
        raise AlturaError(f"{punto.crs} no existe en la base de PROJ.", "crs-invalido") from fallo
    lon, lat = a_wgs84.transform(punto.x_m, punto.y_m)
    if not (math.isfinite(lon) and math.isfinite(lat)):
        raise AlturaError("La posición no se pudo llevar a longitud y latitud.", "crs-invalido")
    return float(lon), float(lat)


def ondulacion_m(punto: PuntoConCrs, *, modelo: str | None) -> tuple[float, Grilla]:
    """`N`, la ondulación del geoide en la posición, y la grilla que la dio."""
    elegido = _modelo(modelo)
    sonda = sondear(elegido.codigo)
    if not sonda.disponible or sonda.grilla is None:
        raise AlturaError(sonda.mensaje, sonda.motivo)
    lon, lat = _a_grados(punto)

    from pyproj import Transformer

    ruta = sonda.grilla.ruta.replace("\\", "/")
    # Entre comillas: la ruta de QGIS lleva espacios («Program Files»).
    tuberia = Transformer.from_pipeline(f'+proj=vgridshift +grids="{ruta}" +multiplier=1')
    _, _, valor = tuberia.transform(lon, lat, 0.0)
    if not math.isfinite(valor):
        raise AlturaError(
            f"({lon:.5f}, {lat:.5f}) cae fuera de la grilla {sonda.grilla.nombre}.",
            "fuera-de-la-grilla",
        )
    return float(valor), sonda.grilla


def convertir(punto: PuntoConCrs, *, modelo: str | None, sentido: str) -> ResultadoAltura:
    """Pasa `punto.z_m` entre altura elipsoidal y ortométrica con el geoide declarado.

    El punto devuelto es el mismo `(x, y, crs)` con la `z_m` nueva; el recibo dice qué modelo,
    qué grilla (con su huella) y qué método dieron el número.
    """
    if sentido not in SENTIDOS:
        raise ValueError(f"sentido desconocido: {sentido!r}; use uno de {SENTIDOS}")
    if punto.z_m is None or not math.isfinite(punto.z_m):
        raise AlturaError("La posición no trae altura que convertir.", "altura-ausente")
    n, grilla = ondulacion_m(punto, modelo=modelo)
    salida = punto.z_m - n if sentido == ELIPSOIDAL_A_ORTOMETRICA else punto.z_m + n
    elegido = _modelo(modelo)
    nuevo = PuntoConCrs(punto.x_m, punto.y_m, punto.crs, z_m=salida)
    return ResultadoAltura(
        punto=nuevo,
        recibo=Recibo(
            modelo=elegido.codigo,
            modelo_nombre=elegido.nombre,
            grilla=grilla,
            metodo=METODO,
            sentido=sentido,
            ondulacion_m=n,
            altura_entrada_m=punto.z_m,
            altura_salida_m=salida,
            crs=str(punto.crs),
        ),
    )
