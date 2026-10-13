"""Procesar ráster: recorte por polígono, mosaico y sombreado (F21.3).

Son **procesos**, no conversiones de formato: sacan de uno o varios rásteres otro ráster distinto
(la parte que cae dentro de un polígono, la unión de varios, el relieve iluminado de un modelo de
elevación). Van en motores aparte, con `operacion` puesta, por la misma razón que las curvas de
nivel: un GeoTIFF a un GeoTIFF ya lo sabe `gdal-raster`, y sin esa marca se tapaban entre sí. El
trabajo pide el suyo con `options["operacion"]`; la matriz de conversión no los ve.

## Las cinco reglas, aquí

1. **El código de salida no es la prueba.** `gdalwarp -cutline` sale con `0` y deja un ráster sin
   un solo dato cuando el polígono no toca la imagen. `verificar` pide estadísticas a `gdalinfo`.
2. **Oráculo externo:** `gdalinfo -json -stats` y, para el sombreado, la fórmula de la iluminación
   sobre un plano de pendiente conocida (ver `test_procesar.py`).
3. **El CRS no se adivina.** El polígono lleva su CRS declarado (`apps/formats/poligono.py`); un
   ráster sin CRS no se recorta ni se sombrea (la escala del sombreado depende de las unidades); un
   mosaico de CRS distintos se detiene (`crs-distintos`).
4. **Apagado con motivo:** sin `gdaldem` el sombreado sale apagado con `sin-gdaldem` (el mismo
   motivo y el mismo paso de instalación que el visor), y sin `gdalwarp` o `gdalbuildvrt`,
   `motor-no-disponible`.
5. **El original no se toca:** solo se lee; todo va a `<destino>.parcial` (los intermedios cuelgan
   de su nombre y el corredor los borra) y el mosaico huella cada entrada para comprobarla.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from apps.engines import registry
from apps.engines.base import (
    Disponibilidad,
    Motor,
    OpcionDeMotor,
    ParDeFormatos,
    PlanDeEjecucion,
    PlanNoValido,
    Verificacion,
    ruta_parcial,
)
from apps.engines.entorno import entorno_de_gdal
from apps.formats import crs as crs_mod
from apps.formats import poligono
from apps.formats.crs import Crs

from .motores import (
    ORIGENES,
    ORIGENES_DE_ELEVACION,
    MotorGdalRaster,
    _bin,
    _epsg_de,
    _gdalinfo,
    _numero_finito,
    analizar_progreso,
)

RECORTE = "recorte"
MOSAICO = "mosaico"
SOMBREADO = "sombreado"

#: Lo que se entrega. COG es el de siempre para ver y compartir; GeoTIFF para quien lo pide.
DESTINOS_DE_PROCESO = ("geotiff", "bigtiff", "cog")
DESTINOS_DE_SOMBREADO = ("geotiff", "cog")

#: Los formatos que se leen como imagen para recortar o unir.
ORIGENES_DE_IMAGEN = tuple(o for o in ORIGENES if o not in ("png", "jpeg", "asc"))

#: Un mosaico de una sola imagen no es un mosaico.
IMAGENES_MINIMAS = 2

RESOLUCIONES = (
    ("highest", "La más fina de las imágenes — no pierde detalle (la de siempre)"),
    ("lowest", "La más gruesa — archivo más pequeño"),
    ("average", "El promedio"),
)

#: El azimut y la altura del sol, y la exageración vertical: los mismos límites que el visor.
AZIMUT_MAXIMO_DEG = 360
ALTURA_MINIMA_DEG, ALTURA_MAXIMA_DEG = 1, 90
EXAGERACION_MINIMA, EXAGERACION_MAXIMA = 0.1, 20.0

#: Cuántas veces el tamaño de un píxel se tolera al comparar extensiones (redondeos de GDAL).
TOLERANCIA_PX = 1.5


def _disponibilidad(*herramientas: str) -> Disponibilidad:
    """GDAL, su PROJ y **cada herramienta** que el proceso lanza. Sin lanzar nada que convierta."""
    from apps.engines import sondas

    gdal = sondas.sondar_gdal()
    if not gdal.disponible:
        return Disponibilidad.no("motor-no-disponible", gdal.motivo, sugerencia="Ver INSTALL.md.")
    proj = sondas.sondar_proj()
    if not proj.disponible:
        return Disponibilidad.no(
            proj.codigo_motivo, proj.mensaje, sugerencia=proj.sugerencia, version=gdal.version
        )
    faltan = [n for n in herramientas if not Path(_bin(n)).is_file()]
    if faltan:
        # `gdaldem` tiene su propio motivo (y su paso en `equipo.py`), el mismo que el visor.
        if "gdaldem" in faltan:
            return Disponibilidad.no(
                "sin-gdaldem",
                "A este GDAL le falta gdaldem, que es lo que calcula el sombreado.",
                sugerencia="Complete la instalación de GDAL (QGIS trae gdaldem).",
                version=gdal.version,
            )
        return Disponibilidad.no(
            "motor-no-disponible",
            f"Esta instalación de GDAL no trae {' ni '.join(f'`{n}`' for n in faltan)}.",
            sugerencia="Ver INSTALL.md: es parte de las utilidades de GDAL.",
            version=gdal.version,
        )
    return Disponibilidad.si(gdal.version)


def _info_o_parar(ruta: Path) -> dict:
    """`gdalinfo -json` de un original. Si no se lee, se para: no se procesa lo que no se ve."""
    info = _gdalinfo(ruta)
    if info is None:
        raise PlanNoValido(f"GDAL no puede leer «{ruta.name}».", "origen-no-legible")
    return info


def _estadisticas(ruta: Path) -> dict | None:
    """`gdalinfo -json -stats`: otro lector que el que escribió el archivo. Sin PAM: no deja un
    `.aux.xml` ni junto a la salida."""
    try:
        hecho = subprocess.run(  # nosec B603
            [_bin("gdalinfo"), "-json", "-stats", str(ruta)],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
            shell=False,
            env=entorno_de_gdal(GDAL_PAM_ENABLED="NO"),
        )
        return json.loads(hecho.stdout) if hecho.returncode == 0 and hecho.stdout else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def _estadistica(banda: dict, nombre: str) -> float | None:
    crudo = (banda.get("metadata", {}).get("", {}) or {}).get(f"STATISTICS_{nombre}")
    try:
        return float(crudo)
    except (TypeError, ValueError):
        return None


def _caja(info: dict) -> tuple[float, float, float, float] | None:
    """`(oeste, sur, este, norte)` de `cornerCoordinates`, o `None` si no está ubicado."""
    esquinas = info.get("cornerCoordinates") or {}
    try:
        (x0, y0), (x1, y1) = esquinas["lowerLeft"], esquinas["upperRight"]
    except (KeyError, TypeError, ValueError):
        return None
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _tamano_de_pixel(info: dict) -> tuple[float, float]:
    transformada = info.get("geoTransform") or [0, 1, 0, 0, 0, -1]
    return abs(transformada[1]) or 1.0, abs(transformada[5]) or 1.0


def _ventana_alineada(
    caja: tuple[float, ...], info: dict
) -> tuple[tuple[float, float, float, float], tuple[float, float]]:
    """La caja del polígono, ajustada **hacia afuera** a la retícula del ráster y recortada a él.

    Devuelve `((oeste, sur, este, norte), (ancho_px, alto_px))`. Una caja que no toca la imagen se
    para aquí con `recorte-vacio`, sin lanzar nada. Una imagen girada no se recorta (su retícula no
    es de ejes).
    """
    import math

    g = info.get("geoTransform")
    tamano = info.get("size")
    if not g or not tamano:
        raise PlanNoValido("La imagen no está ubicada: no se puede recortar.", "crs-ausente")
    if abs(g[2]) > 1e-12 or abs(g[4]) > 1e-12:
        raise PlanNoValido(
            "La imagen está girada: el recorte exige una retícula de ejes.", "error-del-motor"
        )
    x0, ancho, y0, alto = g[0], g[1], g[3], abs(g[5])
    este_img, sur_img = x0 + tamano[0] * ancho, y0 - tamano[1] * alto
    margen = 1e-9
    oeste = x0 + math.floor((caja[0] - x0) / ancho + margen) * ancho
    este = x0 + math.ceil((caja[2] - x0) / ancho - margen) * ancho
    norte = y0 - math.floor((y0 - caja[3]) / alto + margen) * alto
    sur = y0 - math.ceil((y0 - caja[1]) / alto - margen) * alto
    oeste, sur = max(oeste, x0), max(sur, sur_img)
    este, norte = min(este, este_img), min(norte, y0)
    if este - oeste < ancho / 2 or norte - sur < alto / 2:
        raise PlanNoValido(
            "El polígono no toca la imagen: saldría un recorte sin datos.", "recorte-vacio"
        )
    return (oeste, sur, este, norte), (ancho, alto)


def _tiene_alfa(info: dict) -> bool:
    bandas = info.get("bands") or []
    return bool(bandas) and bandas[-1].get("colorInterpretation") == "Alpha"


def _sin_dato_declarado(info: dict) -> bool:
    return any("noDataValue" in banda for banda in info.get("bands") or [])


def _huella(ruta: Path) -> tuple[str, int, int]:
    """`(sha256, bytes, mtime_ns)` de un original, para comprobar que nada lo tocó (regla 5)."""
    resumen = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for trozo in iter(lambda: archivo.read(1 << 20), b""):
            resumen.update(trozo)
    estado = ruta.stat()
    return resumen.hexdigest(), estado.st_size, estado.st_mtime_ns


def _original_cambiado(ruta: Path, antes: tuple[str, int, int]) -> str:
    """El motivo si el original ya no es el de antes; vacío si sigue igual."""
    try:
        ahora = _huella(ruta)
    except OSError:
        return f"«{ruta.name}» ya no está donde estaba."
    if ahora != antes:
        return f"«{ruta.name}» cambió mientras se procesaba."
    return ""


def _filas(trabajo) -> list:
    try:
        return list(trabajo.entradas.all())
    except AttributeError:  # un trabajo sin base de datos (pruebas del plan)
        return []


def _huellar_entradas(trabajo) -> None:
    """Guarda en cada entrada la huella del original **antes** de procesar. El corredor solo huella
    la primera de un trabajo de ráster; las demás se comprobarían contra nada."""
    for fila in _filas(trabajo):
        fila.sha256, fila.bytes, fila.mtime_ns = _huella(Path(fila.ruta))
        fila.save(update_fields=["sha256", "bytes", "mtime_ns", "updated_at"])


def _entradas_cambiadas(trabajo) -> str:
    """El motivo si algún original ya no es el que se huelló; vacío si todos siguen igual."""
    for fila in _filas(trabajo):
        if not fila.sha256:
            continue
        cambio = _original_cambiado(Path(fila.ruta), (fila.sha256, fila.bytes, fila.mtime_ns))
        if cambio:
            return cambio
    return ""


class _MotorDeProceso(Motor):
    """Lo que comparten los procesos ráster: familia, prioridad y el entorno del hijo."""

    familia = "raster"
    prioridad = 10

    def _entorno(self) -> dict[str, str]:
        return entorno_de_gdal(GDAL_NUM_THREADS="ALL_CPUS", GDAL_CACHEMAX="512")

    def _presupuesto(self, trabajo) -> int:
        return MotorGdalRaster()._presupuesto(trabajo)

    def _opciones_de_salida(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        """Compresión y valor sin dato: las que ya declara el motor de conversión."""
        return tuple(
            o for o in MotorGdalRaster().opciones(par) if o.nombre in ("compresion", "nodata")
        )

    def _co(self, trabajo) -> list[str]:
        """`-co` de la salida: los de `gdal-raster`, para que COG y GeoTIFF salgan igual."""
        argv: list[str] = []
        creacion = MotorGdalRaster()._opciones_de_creacion(trabajo, dict(trabajo.options or {}))
        for clave, valor in creacion.items():
            argv += ["-co", f"{clave}={valor}"]
        return argv


# --- Recorte por polígono ---------------------------------------------------------------------


class MotorRecorteRaster(_MotorDeProceso):
    """`gdalwarp -cutline` con ventana propia: la parte de la imagen que cae dentro de un polígono.

    - **El polígono lleva CRS.** Vértices (`recorte_vertices` + `recorte_crs`) o archivo
      (`recorte_archivo`, cuyo CRS lo dice `ogrinfo`). Sin CRS conocido, se detiene.
    - **No remuestrea:** sin reproyección, el recorte conserva la retícula del original (los valores
      de los píxeles son los mismos). Fuera del polígono, el píxel **no tiene dato**: el valor sin
      dato declarado o, si el original no declara ninguno, una banda alfa. Cero no es «sin dato».
    """

    id = "gdal-recorte"
    nombre = "GDAL (recorte por polígono)"
    operacion = RECORTE

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(
            ParDeFormatos(origen, destino)
            for origen in ORIGENES_DE_IMAGEN
            for destino in DESTINOS_DE_PROCESO
        )

    def disponibilidad(self) -> Disponibilidad:
        return _disponibilidad("gdalwarp", "ogr2ogr")

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        return (
            OpcionDeMotor(
                "recorte_crs",
                "Sistema de referencia del polígono",
                "texto",
                por_defecto=None,
                ayuda=(
                    "El EPSG de las coordenadas de los vértices (por ejemplo EPSG:32719). Sin "
                    "valor "
                    "por omisión: recortar con coordenadas de otro sistema deja el resultado en "
                    "otro sitio. No hace falta si el polígono viene en un archivo que lo declara."
                ),
            ),
            OpcionDeMotor(
                "recorte_vertices",
                "Vértices del polígono",
                "texto",
                por_defecto=None,
                ayuda="Un vértice por línea o separados por «;», «este norte», con punto decimal.",
            ),
            OpcionDeMotor(
                "recorte_archivo",
                "O un archivo con el polígono",
                "texto",
                por_defecto=None,
                ayuda="GeoJSON, GeoPackage, Shapefile o KML. El archivo tiene que declarar su CRS.",
            ),
            *self._opciones_de_salida(par),
        )

    def _poligono(self, opciones: dict, raster: Crs) -> tuple[list[str], tuple[float, ...]]:
        """`(argumentos de gdalwarp, caja del polígono en el CRS del ráster)`, ya comprobados."""
        vertices, archivo = opciones.get("recorte_vertices"), opciones.get("recorte_archivo")
        if bool(vertices) == bool(archivo):
            raise PlanNoValido(
                "Falta el polígono de recorte: dé sus vértices o un archivo (no los dos).",
                "error-del-motor",
            )
        if vertices:
            anillo = poligono.anillo_de_opciones(opciones)
            en_el_raster = poligono.llevar_a(anillo, raster)
            argumentos = [
                "-cutline",
                poligono.a_wkt(anillo),
                "-cutline_srs",
                str(poligono.crs_unico(anillo)),
            ]
            return argumentos, poligono.caja_de(en_el_raster)
        ruta = Path(str(archivo))
        if ruta.suffix.lower() not in poligono.EXTENSIONES_DE_POLIGONO:
            raise PlanNoValido(
                "El polígono tiene que venir en GeoJSON, GeoPackage, Shapefile o KML.",
                "formato-no-reconocido",
            )
        from apps.vector.motores import _epsg_de as epsg_de_capas
        from apps.vector.motores import _ogrinfo

        info = _ogrinfo(ruta)
        capas = (info or {}).get("layers") or []
        if info is None or not capas:
            raise PlanNoValido(f"OGR no puede leer el polígono «{ruta.name}».", "origen-no-legible")
        epsg_del_archivo = epsg_de_capas(capas)
        if not epsg_del_archivo:
            raise PlanNoValido(
                f"El polígono «{ruta.name}» no declara un sistema de referencia con EPSG. "
                "No se adivina: declárelo en el archivo o dé los vértices con su EPSG.",
                "crs-ausente",
            )
        extension = ((capas[0].get("geometryFields") or [{}])[0]).get("extent")
        if not extension or len(extension) != 4:
            raise PlanNoValido(f"El polígono «{ruta.name}» no tiene extensión.", "recorte-vacio")
        caja = poligono.caja_de_extension(extension, crs_mod.epsg(epsg_del_archivo), raster)
        return ["-cutline", str(ruta), "-cl", str(capas[0].get("name", ""))], caja

    def plan(self, trabajo) -> PlanDeEjecucion:
        origen = Path(trabajo.source_path)
        destino = Path(trabajo.output_path)
        parcial = ruta_parcial(destino)
        opciones = dict(trabajo.options or {})

        if not trabajo.source_crs_code:
            raise PlanNoValido(
                "La imagen no declara su sistema de referencia: no se sabe dónde cae el polígono.",
                "crs-ausente",
            )
        corte, caja = self._poligono(opciones, crs_mod.epsg(trabajo.source_crs_code))
        info = _info_o_parar(origen)

        # **La ventana se calcula aquí y sobre la retícula del original**, no con
        # `-crop_to_cutline`: este redondea hacia abajo y pierde el último renglón de píxeles (en
        # un oráculo, 99 filas de 100 con el polígono corrido un cuarto de píxel), y `-tap` movería
        # la retícula. Con `-te` y `-tr` alineados a ella, cada píxel de la salida es uno
        # del original.
        ventana, paso = _ventana_alineada(caja, info)
        argv = [_bin("gdalwarp"), *corte, "-overwrite", "-r", "near"]
        argv += ["-te", *(repr(v) for v in ventana), "-tr", *(repr(v) for v in paso)]
        sin_dato = opciones.get("nodata")
        if sin_dato not in (None, ""):
            argv += ["-dstnodata", repr(_numero_finito(sin_dato, "el valor sin dato"))]
        elif not _sin_dato_declarado(info) and not _tiene_alfa(info):
            # Sin esto, lo de fuera del polígono sale con valor 0, que **parece un dato** (una cota
            # cero, un negro de la ortofoto). La banda alfa dice que ahí no hay nada.
            argv.append("-dstalpha")
        argv += [
            "-of",
            "COG" if trabajo.target_format_code == "cog" else "GTiff",
            *self._co(trabajo),
        ]
        argv += ["--config", "GDAL_NUM_THREADS", "ALL_CPUS"]
        argv += [str(origen), str(parcial)]
        return PlanDeEjecucion(
            argv=tuple(argv),
            ruta_de_salida=destino,
            env=self._entorno(),
            timeout_s=self._presupuesto(trabajo),
            analizador_de_progreso=analizar_progreso,
        )

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        base = super().verificar(trabajo, salida)
        if not base.correcta:
            return base
        info = _estadisticas(salida)
        if info is None:
            return Verificacion(
                correcta=False,
                motivo="GDAL no puede leer el archivo que acaba de escribir.",
                codigo_motivo="salida-invalida",
            )
        bandas = info.get("bands") or []
        detalles = {
            "ancho_px": (info.get("size") or [0, 0])[0],
            "alto_px": (info.get("size") or [0, 0])[1],
            "bandas": len(bandas),
            "bytes": salida.stat().st_size,
        }
        epsg = _epsg_de(info)
        if epsg:
            detalles["epsg"] = epsg
        if trabajo.source_crs_code and epsg != str(trabajo.source_crs_code):
            return Verificacion(
                correcta=False,
                motivo=(
                    f"La imagen estaba en EPSG:{trabajo.source_crs_code} y el recorte declara "
                    f"{'EPSG:' + epsg if epsg else 'ningún sistema'}."
                ),
                codigo_motivo="salida-invalida",
                detalles=detalles,
            )
        if self._sin_datos(bandas):
            return Verificacion(
                correcta=False,
                motivo=(
                    "El recorte quedó sin un solo dato: el polígono no toca la imagen. Compruebe "
                    "su posición y el sistema de referencia que declaró."
                ),
                codigo_motivo="recorte-vacio",
                detalles=detalles,
            )
        origen = _gdalinfo(Path(trabajo.source_path)) or {}
        original, recorte = _caja(origen), _caja(info)
        if original and recorte:
            px, py = _tamano_de_pixel(origen)
            fuera = (
                recorte[0] < original[0] - TOLERANCIA_PX * px
                or recorte[1] < original[1] - TOLERANCIA_PX * py
                or recorte[2] > original[2] + TOLERANCIA_PX * px
                or recorte[3] > original[3] + TOLERANCIA_PX * py
            )
            if fuera:
                return Verificacion(
                    correcta=False,
                    motivo="El recorte se sale de la extensión de la imagen original.",
                    codigo_motivo="salida-invalida",
                    detalles=detalles,
                )
        return Verificacion(correcta=True, detalles=detalles)

    @staticmethod
    def _sin_datos(bandas: list[dict]) -> bool:
        """¿No hay ni un píxel válido? Con alfa, mira el alfa; si no, el porcentaje válido."""
        if not bandas:
            return True
        ultima = bandas[-1]
        if ultima.get("colorInterpretation") == "Alpha":
            maximo = _estadistica(ultima, "MAXIMUM")
            return maximo is None or maximo <= 0
        validos = _estadistica(bandas[0], "VALID_PERCENT")
        return validos is not None and validos <= 0


# --- Mosaico ------------------------------------------------------------------------------------


class MotorMosaico(_MotorDeProceso):
    """`gdalbuildvrt` + `gdal_translate`: varias imágenes de un mismo sistema, en una sola.

    Las imágenes son las **entradas del trabajo** (`EntradaDeTrabajo`, en orden: donde se solapan,
    gana la última). Se paran, antes de lanzar nada, las que no son compatibles: otro CRS
    (`crs-distintos`), otro número de bandas o de tipo. Un mosaico de CRS mezclados deja cada
    imagen en un sitio equivocado y abre sin un solo aviso.
    """

    id = "gdal-mosaico"
    nombre = "GDAL (mosaico)"
    operacion = MOSAICO

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(
            ParDeFormatos(origen, destino)
            for origen in ORIGENES_DE_IMAGEN
            for destino in DESTINOS_DE_PROCESO
        )

    def disponibilidad(self) -> Disponibilidad:
        return _disponibilidad("gdalbuildvrt", "gdal_translate")

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        return (
            OpcionDeMotor(
                "resolucion",
                "Tamaño de píxel",
                "eleccion",
                por_defecto="highest",
                elecciones=RESOLUCIONES,
                ayuda="Si las imágenes no tienen el mismo tamaño de píxel, cuál se usa.",
            ),
            *self._opciones_de_salida(par),
        )

    def _entradas(self, trabajo) -> list[Path]:
        filas = _filas(trabajo)
        rutas = [Path(f.ruta) for f in filas] or [Path(trabajo.source_path)]
        if len(rutas) < IMAGENES_MINIMAS:
            raise PlanNoValido(
                f"Un mosaico necesita al menos {IMAGENES_MINIMAS} imágenes.", "error-del-motor"
            )
        return rutas

    def plan(self, trabajo) -> PlanDeEjecucion:
        rutas = self._entradas(trabajo)
        destino = Path(trabajo.output_path)
        parcial = ruta_parcial(destino)
        opciones = dict(trabajo.options or {})

        infos = [_info_o_parar(ruta) for ruta in rutas]
        self._comprobar_compatibles(rutas, infos)
        resolucion = str(opciones.get("resolucion") or "highest")
        if resolucion not in dict(RESOLUCIONES):
            raise PlanNoValido(f"«{resolucion}» no es un tamaño de píxel de los que se ofrecen.")

        intermedio = parcial.with_name(parcial.name + ".mosaico.vrt")
        argv = [_bin("gdalbuildvrt"), "-overwrite", "-resolution", resolucion]
        sin_dato = opciones.get("nodata")
        if sin_dato not in (None, ""):
            valor = repr(_numero_finito(sin_dato, "el valor sin dato"))
            argv += ["-srcnodata", valor, "-vrtnodata", valor]
        elif len(infos[0].get("bands") or []) == 3 and not any(
            _sin_dato_declarado(i) or _tiene_alfa(i) for i in infos
        ):
            # Los huecos entre imágenes (y de un lado a otro de una cuña) salen transparentes y no
            # negros: un negro puro es un color de la ortofoto, no «aquí no hay imagen».
            argv.append("-addalpha")
        argv += [str(intermedio), *(str(r) for r in rutas)]

        # Se huella cada original **antes**; `verificar` la compara después (regla 5). Las
        # entradas de un trabajo de ráster no las huella el corredor: solo la primera.
        _huellar_entradas(trabajo)

        paso2 = (
            _bin("gdal_translate"),
            "-of",
            "COG" if trabajo.target_format_code == "cog" else "GTiff",
            *self._co(trabajo),
            "--config",
            "GDAL_NUM_THREADS",
            "ALL_CPUS",
            str(intermedio),
            str(parcial),
        )
        return PlanDeEjecucion(
            argv=tuple(argv),
            ruta_de_salida=destino,
            posteriores=(paso2,),
            salida_en_posteriores=True,
            env=self._entorno(),
            timeout_s=self._presupuesto(trabajo),
            analizador_de_progreso=analizar_progreso,
        )

    @staticmethod
    def _comprobar_compatibles(rutas: list[Path], infos: list[dict]) -> None:
        primero = infos[0]
        if not _epsg_de(primero) and not (primero.get("coordinateSystem") or {}).get("wkt"):
            raise PlanNoValido(
                f"«{rutas[0].name}» no declara su sistema de referencia: no se sabe dónde va.",
                "crs-ausente",
            )
        forma = (
            len(primero.get("bands") or []),
            tuple(b.get("type") for b in primero.get("bands") or []),
        )
        for ruta, info in zip(rutas[1:], infos[1:], strict=True):
            wkt = (info.get("coordinateSystem") or {}).get("wkt", "")
            if not wkt:
                raise PlanNoValido(
                    f"«{ruta.name}» no declara su sistema de referencia: no se sabe dónde va.",
                    "crs-ausente",
                )
            if _epsg_de(info) != _epsg_de(primero) or (
                not _epsg_de(info) and wkt != (primero.get("coordinateSystem") or {}).get("wkt")
            ):
                raise PlanNoValido(
                    f"«{ruta.name}» no está en el mismo sistema de referencia que "
                    f"«{rutas[0].name}».",
                    "crs-distintos",
                )
            otra = (
                len(info.get("bands") or []),
                tuple(b.get("type") for b in info.get("bands") or []),
            )
            if otra != forma:
                raise PlanNoValido(
                    f"«{ruta.name}» no tiene las mismas bandas que «{rutas[0].name}»: no se unen.",
                    "error-del-motor",
                )

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        base = super().verificar(trabajo, salida)
        if not base.correcta:
            return base
        rutas = self._entradas(trabajo)
        # Los originales, intactos: lo que `plan` huelló, comparado ahora.
        cambio = _entradas_cambiadas(trabajo)
        if cambio:
            return Verificacion(correcta=False, motivo=cambio, codigo_motivo="original-modificado")
        info = _gdalinfo(salida)
        if info is None:
            return Verificacion(
                correcta=False,
                motivo="GDAL no puede leer el archivo que acaba de escribir.",
                codigo_motivo="salida-invalida",
            )
        entradas = [_gdalinfo(r) or {} for r in rutas]
        cajas = [c for c in (_caja(i) for i in entradas) if c]
        union = (
            min(c[0] for c in cajas),
            min(c[1] for c in cajas),
            max(c[2] for c in cajas),
            max(c[3] for c in cajas),
        )
        detalles = {
            "imagenes": len(rutas),
            "ancho_px": (info.get("size") or [0, 0])[0],
            "alto_px": (info.get("size") or [0, 0])[1],
            "bandas": len(info.get("bands") or []),
            "bytes": salida.stat().st_size,
            "epsg": _epsg_de(info),
        }
        esperado = _epsg_de(entradas[0])
        if esperado and detalles["epsg"] != esperado:
            return Verificacion(
                correcta=False,
                motivo=f"Las imágenes estaban en EPSG:{esperado} y el mosaico no lo declara.",
                codigo_motivo="salida-invalida",
                detalles=detalles,
            )
        caja = _caja(info)
        px, py = _tamano_de_pixel(info)
        if caja is None or any(
            abs(a - b) > TOLERANCIA_PX * p
            for a, b, p in zip(caja, union, (px, py, px, py), strict=True)
        ):
            return Verificacion(
                correcta=False,
                motivo="La extensión del mosaico no es la unión de la de las imágenes.",
                codigo_motivo="salida-invalida",
                detalles={**detalles, "esperada": union, "obtenida": caja},
            )
        return Verificacion(correcta=True, detalles=detalles)


# --- Sombreado ------------------------------------------------------------------------------------


class MotorSombreado(_MotorDeProceso):
    """`gdaldem hillshade` de un modelo de elevación, entregado como imagen de 8 bits.

    Es la misma llamada que el visor (`apps/visor/dem.argumentos_de_sombreado`: no se duplica) y la
    misma escala (`dem.escala_de_sombreado`): con grados, 111120; con pies, los pies. **La escala
    depende del CRS**, y por eso un modelo sin CRS no se sombrea: las pendientes
    saldrían de unidades
    que nadie sabe cuáles son.
    """

    id = "gdal-sombreado"
    nombre = "GDAL (sombreado)"
    operacion = SOMBREADO

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(
            ParDeFormatos(origen, destino)
            for origen in ORIGENES_DE_ELEVACION
            for destino in DESTINOS_DE_SOMBREADO
        )

    def disponibilidad(self) -> Disponibilidad:
        return _disponibilidad("gdaldem", "gdal_translate")

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        return (
            OpcionDeMotor(
                "azimut_deg",
                "Azimut del sol (°)",
                "decimal",
                por_defecto=315,
                minimo=0,
                maximo=AZIMUT_MAXIMO_DEG - 0.01,
                ayuda="De dónde viene la luz, desde el norte y en sentido horario. 315 es el NO.",
            ),
            OpcionDeMotor(
                "altura_deg",
                "Altura del sol (°)",
                "decimal",
                por_defecto=45,
                minimo=ALTURA_MINIMA_DEG,
                maximo=ALTURA_MAXIMA_DEG,
                ayuda="A cuántos grados sobre el horizonte. Más bajo, sombras más largas.",
            ),
            OpcionDeMotor(
                "exageracion_z",
                "Exageración vertical",
                "decimal",
                por_defecto=1.0,
                minimo=EXAGERACION_MINIMA,
                maximo=EXAGERACION_MAXIMA,
                ayuda="Multiplica las alturas: realza un relieve suave, pero deforma el real.",
            ),
        )

    @staticmethod
    def _numero(opciones: dict, nombre: str, por_defecto: float, minimo: float, maximo: float):
        valor = _numero_finito(opciones.get(nombre, por_defecto), f"«{nombre}»")
        if not minimo <= valor <= maximo:
            raise PlanNoValido(f"«{nombre}» va de {minimo:g} a {maximo:g}.")
        return valor

    def plan(self, trabajo) -> PlanDeEjecucion:
        from apps.visor import capa as capa_mod
        from apps.visor import dem

        origen = Path(trabajo.source_path)
        destino = Path(trabajo.output_path)
        parcial = ruta_parcial(destino)
        opciones = dict(trabajo.options or {})

        azimut = self._numero(opciones, "azimut_deg", 315, 0, AZIMUT_MAXIMO_DEG - 0.01)
        altura = self._numero(opciones, "altura_deg", 45, ALTURA_MINIMA_DEG, ALTURA_MAXIMA_DEG)
        exageracion = self._numero(
            opciones, "exageracion_z", 1.0, EXAGERACION_MINIMA, EXAGERACION_MAXIMA
        )

        info = _info_o_parar(origen)
        bandas = info.get("bands") or []
        paleta = bool(bandas) and bandas[0].get("colorInterpretation") == "Palette"
        if not (
            bandas and dem.es_dem(bandas=len(bandas), tipo=bandas[0].get("type", ""), paleta=paleta)
        ):
            raise PlanNoValido(
                "El archivo no es un modelo de elevación (una banda de alturas): el sombreado "
                "se calcula sobre alturas, no sobre una imagen.",
                "error-del-motor",
            )
        crs = capa_mod._crs_de(info)
        if crs is None:
            raise PlanNoValido(
                "El modelo no declara su sistema de referencia: sin él no se sabe si sus unidades "
                "son metros o grados, y el sombreado depende de ello. No se adivina.",
                "crs-ausente",
            )
        _, unidad_m = dem.unidad_vertical(bandas[0].get("unit"))
        escala = dem.escala_de_sombreado(crs, unidad_m)

        intermedio = parcial.with_name(parcial.name + ".sombra.tif")
        argv = [
            _bin("gdaldem"),
            *dem.argumentos_de_sombreado(
                origen,
                intermedio,
                azimut_deg=azimut,
                altura_deg=altura,
                exageracion_z=exageracion,
                escala=escala,
                silencioso=False,
            ),
        ]
        paso2 = (
            _bin("gdal_translate"),
            "-of",
            "COG" if trabajo.target_format_code == "cog" else "GTiff",
            *self._co(trabajo),
            str(intermedio),
            str(parcial),
        )
        return PlanDeEjecucion(
            argv=tuple(argv),
            ruta_de_salida=destino,
            posteriores=(paso2,),
            salida_en_posteriores=True,
            env=self._entorno(),
            timeout_s=self._presupuesto(trabajo),
            analizador_de_progreso=analizar_progreso,
        )

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        base = super().verificar(trabajo, salida)
        if not base.correcta:
            return base
        info = _estadisticas(salida)
        origen = _gdalinfo(Path(trabajo.source_path))
        if info is None or origen is None:
            return Verificacion(
                correcta=False,
                motivo="GDAL no puede leer el sombreado que acaba de escribir.",
                codigo_motivo="salida-invalida",
            )
        bandas = info.get("bands") or []
        detalles = {
            "ancho_px": (info.get("size") or [0, 0])[0],
            "alto_px": (info.get("size") or [0, 0])[1],
            "bytes": salida.stat().st_size,
            "epsg": _epsg_de(info),
        }
        # El mismo tamaño y la misma ubicación que el modelo, una banda de 8 bits: lo que dice el
        # visor de su propio sombreado, comprobado aquí con `gdalinfo` y no con lo que escribió.
        mismo = (
            info.get("size") == origen.get("size")
            and info.get("geoTransform") == origen.get("geoTransform")
            and len(bandas) == 1
            and bandas[0].get("type") == "Byte"
        )
        if not mismo:
            return Verificacion(
                correcta=False,
                motivo="El sombreado no tiene el tamaño, la ubicación o la forma del modelo.",
                codigo_motivo="salida-invalida",
                detalles=detalles,
            )
        if trabajo.source_crs_code and detalles["epsg"] != str(trabajo.source_crs_code):
            declarado = f"EPSG:{detalles['epsg']}" if detalles["epsg"] else "ningún sistema"
            return Verificacion(
                correcta=False,
                motivo=(
                    f"El modelo estaba en EPSG:{trabajo.source_crs_code} y el sombreado "
                    f"declara {declarado}."
                ),
                codigo_motivo="salida-invalida",
                detalles=detalles,
            )
        return Verificacion(correcta=True, detalles=detalles)


def registrar() -> None:
    registry.registrar(MotorRecorteRaster())
    registry.registrar(MotorMosaico())
    registry.registrar(MotorSombreado())
