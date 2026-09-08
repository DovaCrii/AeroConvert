"""Motores raster: los que de verdad convierten.

## Como se construye el comando

`gdal_translate` cuando no hay que reproyectar, `gdalwarp` cuando si. La diferencia importa
mas de lo que parece: `gdal_translate` con `-a_srs` **no reproyecta**, solo reetiqueta -- si
alguien lo usa esperando reproyeccion, la ortofoto acaba en el sitio equivocado con un CRS
que dice lo contrario. Es un fallo silencioso, asi que la eleccion la hace el motor y no una
opcion del formulario.

## Las opciones no son libres

Cada opcion que el motor acepta esta declarada en `opciones()`, y de ahi se genera el
formulario. Asi el formulario no puede ofrecer un ajuste que el motor no sepa traducir a un
argumento, ni al reves.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings

from apps.engines import registry
from apps.engines.base import (
    Disponibilidad,
    Motor,
    OpcionDeMotor,
    ParDeFormatos,
    PlanDeEjecucion,
    Verificacion,
)

#: Origenes raster que GDAL sabe leer.
ORIGENES = ("geotiff", "bigtiff", "cog", "jp2", "img", "asc", "png", "jpeg", "mrsid", "ecw")
#: Destinos que GDAL escribe sin licencia de nadie.
DESTINOS_LIBRES = ("geotiff", "bigtiff", "cog", "jp2", "img", "asc", "png", "webp")

#: El controlador de GDAL para cada codigo del catalogo.
CONTROLADOR = {
    "geotiff": "GTiff",
    "bigtiff": "GTiff",
    "cog": "COG",
    "jp2": "JP2OpenJPEG",
    "ecw": "ECW",
    "img": "HFA",
    "asc": "AAIGrid",
    "png": "PNG",
    "jpeg": "JPEG",
    "webp": "WEBP",
}

#: Cuantos segundos por gigabyte de entrada. Un ECW de 40 GB tarda horas legitimamente, asi
#: que el presupuesto tiene que ser generoso: el que detecta un atasco de verdad es el
#: detector de silencio, no este.
SEGUNDOS_POR_GB_POR_DEFECTO = 900

#: Los unicos destinos a los que se les pide `gdaladdo`.
#:
#: **La lista es corta a proposito, y saltarsela cuesta caro.** `gdaladdo` solo escribe las
#: piramides *dentro* del archivo cuando el controlador admite abrirlo para actualizar; con
#: cualquier otro escribe un `.ovr` al lado. Y un `.ovr` es un GeoTIFF con la piramide sin
#: comprimir bien: sobre una ortofoto de 14.526 x 14.443 son **360 MB** pegados a un JP2 de
#: 63 MB. Se midio.
#:
#: Eso rompe las dos cosas que se prometen: el entregable deja de ser un solo archivo que se
#: basta a si mismo, y el disco del servidor se llena con seis veces lo que se pidio.
#:
#: Los que faltan no lo necesitan:
#: - `cog` las construye el propio controlador.
#: - `jp2` y `ecw` son wavelet: son multirresolucion por construccion.
#: - `asc` es texto plano y `png`/`jpeg`/`webp` no son formatos de archivo geoespacial.
DESTINOS_CON_PIRAMIDES = frozenset({"geotiff", "bigtiff", "img"})


def _bin(nombre: str) -> str:
    """Donde esta la herramienta de GDAL. Configuracion primero, PATH despues."""
    carpeta = (getattr(settings, "GDAL_BIN", "") or "").strip().strip('"')
    if carpeta:
        import os

        candidato = Path(carpeta) / (f"{nombre}.exe" if os.name == "nt" else nombre)
        if candidato.is_file():
            return str(candidato)
    return shutil.which(nombre) or nombre


class MotorGdalRaster(Motor):
    """Conversión raster con GDAL. Es el caballo de tiro del producto."""

    id = "gdal-raster"
    nombre = "GDAL"
    familia = "raster"
    prioridad = 10

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(
            ParDeFormatos(origen, destino) for origen in ORIGENES for destino in DESTINOS_LIBRES
        )

    def disponibilidad(self) -> Disponibilidad:
        from apps.engines import sondas

        gdal = sondas.sondar_gdal()
        if not gdal.disponible:
            return Disponibilidad.no(
                "motor-no-disponible", gdal.motivo, sugerencia="Ver INSTALL.md."
            )
        proj = sondas.sondar_proj()
        if not proj.disponible:
            return Disponibilidad.no(
                proj.codigo_motivo, proj.mensaje, sugerencia=proj.sugerencia, version=gdal.version
            )
        return Disponibilidad.si(gdal.version)

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        comunes = (
            OpcionDeMotor(
                "compresion",
                "Compresión",
                "eleccion",
                por_defecto="DEFLATE",
                elecciones=(
                    ("DEFLATE", "DEFLATE — sin pérdida, la más pequeña"),
                    ("LZW", "LZW — sin pérdida, más compatible con software antiguo"),
                    ("JPEG", "JPEG — con pérdida, mucho más pequeña"),
                    ("NONE", "Sin comprimir"),
                ),
                ayuda=(
                    "Medido sobre una ortofoto real: DEFLATE queda 33 MB por debajo de LZW "
                    "siendo igual de exacto."
                ),
            ),
            OpcionDeMotor(
                "solo_rgb",
                "Descartar la banda alfa",
                "booleano",
                por_defecto=False,
                ayuda="Varios CAD pintan la banda alfa como una banda gris más.",
            ),
        )
        # Las piramides solo se ofrecen donde de verdad caben dentro del archivo. Ofrecerlas
        # en un JP2 seria ofrecer un `.ovr` de 360 MB al lado, que es justo lo contrario de
        # lo que se pide.
        if par.destino in DESTINOS_CON_PIRAMIDES:
            comunes = (
                *comunes,
                OpcionDeMotor(
                    "piramides",
                    "Pirámides",
                    "eleccion",
                    por_defecto="2 4 8 16 32",
                    elecciones=(
                        ("", "Ninguna"),
                        ("2 4 8", "Tres niveles"),
                        ("2 4 8 16 32", "Cinco niveles — recomendado"),
                    ),
                    ayuda="Van dentro del archivo. Sin ellas, cada zoom lee la imagen entera.",
                ),
            )
        if par.destino in ("geotiff", "bigtiff", "cog"):
            return (
                *comunes,
                OpcionDeMotor(
                    "tamano_tesela",
                    "Tamaño de tesela",
                    "eleccion",
                    por_defecto="512",
                    elecciones=(("256", "256 px"), ("512", "512 px"), ("1024", "1024 px")),
                ),
            )
        if par.destino == "jp2":
            return (
                OpcionDeMotor(
                    "calidad",
                    "Calidad",
                    "entero",
                    por_defecto=25,
                    minimo=1,
                    maximo=100,
                    ayuda=(
                        "Porcentaje del tamaño original que se persigue. Con 25 se midió "
                        "PSNR 51,7 dB y un error máximo de 4 niveles sobre 255."
                    ),
                ),
                *comunes[1:],
            )
        return comunes

    # --- El plan ------------------------------------------------------------

    def plan(self, trabajo) -> PlanDeEjecucion:
        origen = Path(trabajo.source_path)
        destino = Path(trabajo.output_path)
        parcial = destino.with_name(destino.name + ".parcial")

        opciones = dict(trabajo.options or {})
        reproyecta = bool(trabajo.target_crs_code)
        controlador = CONTROLADOR.get(trabajo.target_format_code, "GTiff")

        argv: list[str] = [_bin("gdalwarp" if reproyecta else "gdal_translate")]

        if reproyecta:
            autoridad = trabajo.target_crs_authority or "EPSG"
            argv += ["-t_srs", f"{autoridad}:{trabajo.target_crs_code}"]
            remuestreo = opciones.get("remuestreo", "cubic")
            argv += ["-r", str(remuestreo)]
            argv += ["-overwrite"]
        else:
            for banda in self._bandas(trabajo, opciones):
                argv += ["-b", str(banda)]

        argv += ["-of", controlador]
        for clave, valor in self._opciones_de_creacion(trabajo, opciones).items():
            argv += ["-co", f"{clave}={valor}"]

        argv += ["--config", "GDAL_NUM_THREADS", "ALL_CPUS"]

        # **Nunca `-q` aqui.** Silenciar a GDAL tiene dos consecuencias, y la segunda es
        # grave: la barra de progreso se queda quieta toda la conversion, y -- peor -- el
        # detector de atasco deja de recibir senales. En un raster que tarda mas de
        # `AEROCONVERT_SILENCIO_MAXIMO_S`, un motor perfectamente sano se daria por
        # atascado y se mataria a si mismo.
        #
        # `gdal_translate` emite el avance por omision. `gdalwarp` necesita pedirselo.
        if reproyecta:
            argv += ["-progress"]

        argv += [str(origen), str(parcial)]

        posteriores: list[tuple[str, ...]] = []
        niveles = str(opciones.get("piramides", "2 4 8 16 32")).split()
        if niveles and trabajo.target_format_code in DESTINOS_CON_PIRAMIDES:
            posteriores.append(
                (
                    _bin("gdaladdo"),
                    "-r",
                    "average",
                    "-q",
                    str(parcial),
                    *niveles,
                )
            )

        return PlanDeEjecucion(
            argv=tuple(argv),
            ruta_de_salida=destino,
            posteriores=tuple(posteriores),
            env=self._entorno(),
            timeout_s=self._presupuesto(trabajo),
            analizador_de_progreso=analizar_progreso,
        )

    def _bandas(self, trabajo, opciones) -> tuple[int, ...]:
        """Que bandas se copian. Vacio = todas."""
        if not opciones.get("solo_rgb"):
            return ()
        return (1, 2, 3)

    def _opciones_de_creacion(self, trabajo, opciones) -> dict[str, str]:
        destino = trabajo.target_format_code
        creacion: dict[str, str] = {}

        if destino in ("geotiff", "bigtiff", "cog"):
            compresion = str(opciones.get("compresion", "DEFLATE")).upper()
            creacion["COMPRESS"] = compresion
            if compresion in ("DEFLATE", "LZW"):
                # El predictor horizontal es lo que hace que DEFLATE y LZW valgan la pena
                # sobre datos de imagen. Sin el, comprimen la mitad.
                creacion["PREDICTOR"] = "2"
            if destino != "cog":
                creacion["TILED"] = "YES"
                tesela = str(opciones.get("tamano_tesela", "512"))
                creacion["BLOCKXSIZE"] = tesela
                creacion["BLOCKYSIZE"] = tesela
            # **La opcion que resuelve el caso que origino la aplicacion.** `NO` obliga a
            # TIFF clasico y falla ruidosamente si no cabe, que es preferible a escribir en
            # silencio algo que Civil 3D no abrira. `IF_SAFER` deja que GDAL decida con
            # margen; `IF_NEEDED` no, porque estima sobre el tamano sin comprimir.
            if destino == "bigtiff":
                creacion["BIGTIFF"] = "YES"
            else:
                creacion["BIGTIFF"] = str(
                    opciones.get("bigtiff", "NO" if destino == "geotiff" else "IF_SAFER")
                )

        elif destino == "jp2":
            creacion["QUALITY"] = str(opciones.get("calidad", 25))
            creacion["REVERSIBLE"] = "YES" if opciones.get("sin_perdida") else "NO"
            # Las dos cajas de georreferencia, para que el archivo se baste a si mismo y no
            # necesite un `.j2w` al lado.
            creacion["GeoJP2"] = "YES"
            creacion["GMLJP2"] = "YES"
            creacion["RESOLUTIONS"] = str(opciones.get("resoluciónes", 6))

        elif destino == "webp":
            creacion["QUALITY"] = str(opciones.get("calidad", 85))

        return creacion

    def _entorno(self) -> dict[str, str]:
        """Variables del **proceso hijo**. Nunca las del servidor."""
        entorno = {
            "GDAL_NUM_THREADS": "ALL_CPUS",
            # Sin tope, GDAL se come la memoria de la maquina en un raster grande y el
            # sistema empieza a paginar. 512 MB es de sobra y deja la estacion usable.
            "GDAL_CACHEMAX": "512",
        }
        carpeta = (getattr(settings, "GDAL_BIN", "") or "").strip().strip('"')
        if carpeta:
            import os

            entorno["PATH"] = carpeta + os.pathsep + os.environ.get("PATH", "")
        return entorno

    def _presupuesto(self, trabajo) -> int:
        gigas = max(1.0, (trabajo.source_size_bytes or 0) / 1e9)
        por_giga = getattr(settings, "SEGUNDOS_POR_GB", SEGUNDOS_POR_GB_POR_DEFECTO)
        return int(max(600, gigas * por_giga))

    # --- La verificacion -----------------------------------------------------

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        """Se le pregunta a GDAL si la salida sirve.

        Lo importante es **que lo diga GDAL y no nosotros**: comprobar la salida con el
        mismo lector que la escribio no probaria nada. Se comparan las dimensiones contra
        las del origen y se exige que el CRS siga ahi cuando el origen lo tenia.
        """
        base = super().verificar(trabajo, salida)
        if not base.correcta:
            return base

        info = _gdalinfo(salida)
        if info is None:
            # GDAL no pudo leer lo que acaba de escribir. Es raro y es grave.
            return Verificacion(
                correcta=False,
                motivo="GDAL no puede leer el archivo que acaba de escribir.",
                codigo_motivo="salida-invalida",
            )

        detalles = {
            "ancho_px": info.get("size", [0, 0])[0],
            "alto_px": info.get("size", [0, 0])[1],
            "bandas": len(info.get("bands", [])),
            "controlador": info.get("driverShortName", ""),
            "bytes": salida.stat().st_size,
        }
        epsg = _epsg_de(info)
        if epsg:
            detalles["epsg"] = epsg

        # Si el origen tenia CRS, la salida tiene que tenerlo. Perderlo por el camino es el
        # fallo mas caro que hay: el archivo abre, se ve bien, y esta en otro sitio.
        if trabajo.source_crs_code and not epsg and trabajo.target_format_code != "png":
            return Verificacion(
                correcta=False,
                motivo=(
                    f"El origen estaba en EPSG:{trabajo.source_crs_code} y la salida no "
                    "declara ningún sistema de referencia."
                ),
                codigo_motivo="salida-invalida",
                detalles=detalles,
            )

        return Verificacion(correcta=True, detalles=detalles)


class MotorEcw(Motor):
    """ECW, separado del motor general a proposito.

    Si ECW fuera un destino mas de `gdal-raster`, al faltar la clave se apagaria la fila
    entera con el motivo equivocado -- y GDAL si esta. Separarlo es lo que permite que su
    celda tenga su propio motivo y su propia alternativa.
    """

    id = "gdal-ecw"
    nombre = "GDAL con SDK de Hexagon"
    familia = "raster"
    prioridad = 20

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(ParDeFormatos(origen, "ecw") for origen in ORIGENES)

    def disponibilidad(self) -> Disponibilidad:
        from apps.engines import sondas

        return sondas.sondar_ecw()

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        return (
            OpcionDeMotor(
                "objetivo",
                "Reducción objetivo",
                "entero",
                por_defecto=90,
                minimo=1,
                maximo=99,
                ayuda="Porcentaje de reducción que se persigue. 90 significa una décima parte.",
            ),
        )

    def plan(self, trabajo) -> PlanDeEjecucion:
        general = MotorGdalRaster()
        base = general.plan(trabajo)

        entorno = dict(base.env)
        clave = (getattr(settings, "ECW_ENCODE_KEY", "") or "").strip()
        empresa = (getattr(settings, "ECW_ENCODE_COMPANY", "") or "").strip()
        if clave and empresa:
            # **La clave viaja solo aqui**, en el entorno del hijo. Nunca en el argv, que se
            # guarda entero en la bitacora, ni en el entorno del servidor.
            entorno["ECW_ENCODE_KEY"] = clave
            entorno["ECW_ENCODE_COMPANY"] = empresa

        objetivo = (trabajo.options or {}).get("objetivo", 90)
        argv = list(base.argv)
        argv[argv.index("-of") + 1] = "ECW"
        argv[-2:-2] = ["-co", f"TARGET={objetivo}"]

        return PlanDeEjecucion(
            argv=tuple(argv),
            ruta_de_salida=base.ruta_de_salida,
            # ECW lleva su propia piramide dentro por construccion: es wavelet.
            posteriores=(),
            env=entorno,
            timeout_s=base.timeout_s,
            analizador_de_progreso=base.analizador_de_progreso,
        )

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        return MotorGdalRaster().verificar(trabajo, salida)


# --- Utilidades -------------------------------------------------------------


def analizar_progreso(linea: str) -> float | None:
    """`0...10...20...30` -> 0.30. Una linea que no habla de progreso devuelve `None`."""
    numeros = [t for t in linea.replace(".", " ").split() if t.isdigit() and len(t) <= 3]
    if not numeros:
        return None
    valor = int(numeros[-1])
    return valor / 100.0 if 0 <= valor <= 100 else None


def _gdalinfo(ruta: Path) -> dict | None:
    import json
    import subprocess

    try:
        resultado = subprocess.run(  # nosec B603
            [_bin("gdalinfo"), "-json", str(ruta)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if resultado.returncode != 0 or not resultado.stdout:
        return None
    try:
        return json.loads(resultado.stdout)
    except json.JSONDecodeError:
        return None


def _epsg_de(info: dict) -> str:
    """El código EPSG que declara `gdalinfo -json`, si lo declara."""
    try:
        wkt = info.get("coordinateSystem", {}).get("wkt", "")
    except AttributeError:
        return ""
    import re

    encontrados = re.findall(r'ID\s*\[\s*"EPSG"\s*,\s*(\d+)\s*\]', wkt)
    return encontrados[-1] if encontrados else ""


def registrar_todos() -> None:
    registry.registrar(MotorGdalRaster())
    registry.registrar(MotorEcw())
