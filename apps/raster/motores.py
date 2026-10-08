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
    ruta_parcial,
)
from apps.engines.entorno import entorno_de_gdal

#: Origenes raster que **cualquier** compilacion de GDAL sabe leer.
ORIGENES = ("geotiff", "bigtiff", "cog", "jp2", "img", "asc", "png", "jpeg")

#: Los que solo se leen si su controlador, que es de un tercero y con su licencia, esta
#: compilado dentro. Van aparte **a proposito**, cada uno con su motor y su sonda: mezclados
#: en `ORIGENES`, el motor general daba por buenas sus ocho columnas con solo comprobar que
#: GDAL existe, y la matriz pintaba en verde una conversion que moria al pedirla.
#:
#: La clave es el codigo del catalogo; el valor, como se llama el controlador en GDAL y de
#: donde sale.
ORIGENES_PROPIETARIOS = {
    "ecw": (
        "ECW",
        "El plugin ECW de GISInternals lo trae en Windows (winget install "
        "GISInternals.GDAL.ECW). La compilacion de QGIS y la de conda-forge no.",
    ),
    "mrsid": (
        "MRSID",
        "Hace falta una compilacion de GDAL con la SDK de LizardTech. La de QGIS y la de "
        "conda-forge no la traen.",
    ),
}

#: Todos los origenes, para quien necesite la lista entera — la sonda de ECW de escritura,
#: por ejemplo, que ofrece convertir a ECW desde cualquiera de ellos.
TODOS_LOS_ORIGENES = ORIGENES + tuple(ORIGENES_PROPIETARIOS)

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
#: Entradas de texto plano, las que cualquier contenido podría disfrazar con su extensión.
LECTOR_ESTRICTO = {"asc": "AAIGrid"}

DESTINOS_CON_PIRAMIDES = frozenset({"geotiff", "bigtiff", "img"})

#: Cómo se calculan los píxeles nuevos al reproyectar. **La lista es la única entrada posible**:
#: el formulario la valida y `plan()` la vuelve a comprobar, porque el valor acaba en un argumento
#: de `gdalwarp`. Antes `plan()` leía `opciones["remuestreo"]` y nadie lo declaraba: se podía leer
#: y no se podía poner.
REMUESTREOS = (
    ("cubic", "Cúbica — fotos y ortofotos (la de siempre)"),
    ("bilinear", "Bilineal — más suave y más rápida"),
    ("lanczos", "Lanczos — la más nítida"),
    ("average", "Promedio — al achicar mucho"),
    ("near", "Vecino más cercano — conserva los valores (clasificados, categorías)"),
)

#: Los destinos que **guardan** un valor «sin dato». PNG y WebP no lo llevan: ofrecérselo ahí
#: sería prometer algo que el archivo de salida no puede contener.
DESTINOS_CON_NODATA = frozenset({"geotiff", "bigtiff", "cog", "img", "asc"})


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
        comunes = (
            *comunes,
            OpcionDeMotor(
                "remuestreo",
                "Remuestreo",
                "eleccion",
                por_defecto="cubic",
                elecciones=REMUESTREOS,
                ayuda=(
                    "Solo se usa si cambia el sistema de coordenadas. Con valores que son "
                    "categorías (un clasificado), use «vecino más cercano»: cualquier otro "
                    "inventa valores que no existían."
                ),
            ),
        )
        if par.destino in DESTINOS_CON_NODATA:
            comunes = (
                *comunes,
                OpcionDeMotor(
                    "nodata",
                    "Valor sin dato",
                    "decimal",
                    por_defecto=None,
                    minimo=-1e38,
                    maximo=1e38,
                    ayuda=(
                        "El valor de los píxeles que no son dato (por ejemplo -9999 o 0). Vacío: "
                        "se deja el que ya trae el archivo. Los píxeles no cambian de valor: "
                        "solo se declara cuál es el vacío."
                    ),
                ),
            )
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
        parcial = ruta_parcial(destino)

        opciones = dict(trabajo.options or {})
        reproyecta = bool(trabajo.target_crs_code)
        controlador = CONTROLADOR.get(trabajo.target_format_code, "GTiff")

        argv: list[str] = [_bin("gdalwarp" if reproyecta else "gdal_translate")]

        if reproyecta:
            autoridad = trabajo.target_crs_authority or "EPSG"
            argv += ["-t_srs", f"{autoridad}:{trabajo.target_crs_code}"]
            remuestreo = str(opciones.get("remuestreo") or "cubic")
            if remuestreo not in dict(REMUESTREOS):
                raise ValueError(f"«{remuestreo}» no es un remuestreo de los que se ofrecen.")
            argv += ["-r", remuestreo]
            argv += ["-overwrite"]
        else:
            for banda in self._bandas(trabajo, opciones):
                argv += ["-b", str(banda)]

        sin_dato = opciones.get("nodata")
        if sin_dato not in (None, "") and trabajo.target_format_code in DESTINOS_CON_NODATA:
            # En `gdalwarp` el destino lleva su propio valor; en `gdal_translate` solo se declara.
            argv += ["-dstnodata" if reproyecta else "-a_nodata", repr(float(sin_dato))]

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
        # Los dos emiten el avance **por omision**; solo `-q` lo apaga. Aqui hubo un `-progress`
        # para `gdalwarp` que GDAL rechaza («Unknown argument»): la reproyeccion no funciono nunca
        # contra GDAL de verdad, porque la unica prueba afirmaba que el argumento estuviera.

        # **B-04:** sin `-if`, GDAL abre el archivo con el controlador que le dicte el contenido,
        # y un VRT disfrazado de `.asc` leería otros archivos del disco. Con `-if` solo prueba
        # el controlador que corresponde a lo que se declaró.
        lector = LECTOR_ESTRICTO.get(getattr(trabajo, "source_format_code", ""))
        if lector:
            argv += ["-if", lector]

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
        """Variables del **proceso hijo**. Nunca las del servidor.

        `GDAL_DATA` y las de PROJ las localiza `entorno_de_gdal()`: no se pueden deducir de
        la carpeta de binarios con una regla, y sin ellas hay controladores que no arrancan.
        """
        return entorno_de_gdal(
            GDAL_NUM_THREADS="ALL_CPUS",
            # Sin tope, GDAL se come la memoria de la maquina en un raster grande y el
            # sistema empieza a paginar. 512 MB es de sobra y deja la estacion usable.
            GDAL_CACHEMAX="512",
        )

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
        return frozenset(ParDeFormatos(origen, "ecw") for origen in TODOS_LOS_ORIGENES)

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


class MotorLecturaPropietaria(Motor):
    """Leer un formato cuyo controlador no viene en GDAL de serie.

    **Uno por formato, no uno para todos.** Un solo motor tendria que contestar con una sola
    disponibilidad para ECW y MrSID a la vez, y son dos instalaciones distintas: con el plugin
    de ECW puesto y el de MrSID no, la respuesta unica mentiria sobre uno de los dos.

    Escribir el formato es otra cosa y tiene su propio motor -- `MotorEcw` -- porque el arreglo
    tambien es otro: leer ECW es gratis, escribirlo necesita una clave OEM de pago.
    """

    familia = "raster"
    #: Por debajo del general: cuando los dos sirven para un par, gana el que no necesita nada.
    prioridad = 15

    def __init__(self, formato: str, controlador: str, de_donde: str):
        self.formato = formato
        self.controlador = controlador
        self.de_donde = de_donde
        self.id = f"gdal-leer-{formato}"
        self.nombre = f"GDAL con el controlador {controlador}"

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(ParDeFormatos(self.formato, destino) for destino in DESTINOS_LIBRES)

    def disponibilidad(self) -> Disponibilidad:
        from apps.engines import sondas

        return sondas.sondar_lectura_gdal(
            self.controlador,
            formato=self.formato,
            de_donde=self.de_donde,
            # Lo unico honesto que se puede sugerir: el archivo se abre en el programa que
            # si lo lee y se guarda en algo abierto. No hay alternativa dentro de aqui.
            alternativas=(),
        )

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        return MotorGdalRaster().opciones(par)

    def plan(self, trabajo) -> PlanDeEjecucion:
        return MotorGdalRaster().plan(trabajo)

    def verificar(self, trabajo, plan):
        return MotorGdalRaster().verificar(trabajo, plan)


#: Los origenes que pueden ser un modelo de elevacion. Un GeoTIFF de tres bandas no lo es, y lo
#: dice el recibo: la banda 1 se toma como altura, y quien lo use sobre una ortofoto saca lineas
#: que no son curvas de nada.
ORIGENES_DE_ELEVACION = ("geotiff", "bigtiff", "cog", "img", "asc")

#: Lo que se escribe. DWG no esta: lo escribe ODA (F15.8) a partir de un DXF.
DESTINOS_DE_CURVAS = {"dxf": "DXF", "shp": "ESRI Shapefile", "gpkg": "GPKG"}

#: El nombre del campo con la cota, y el de la capa. Cortos: el Shapefile corta a diez letras.
CAMPO_DE_COTA = "ELEV"
CAPA_DE_CURVAS = "curvas"

#: Un intervalo menor que esto no es una curva de nivel: son millones de lineas pegadas.
INTERVALO_MINIMO_M = 0.001


class MotorCurvasDeNivel(Motor):
    """Curvas de nivel desde un modelo de elevacion, con `gdal_contour` (F15.6).

    **Va en un motor aparte** y no como un destino mas de `gdal-raster`: no convierte pixeles a
    pixeles, saca **lineas** de un campo continuo, y por eso sus opciones (un intervalo, una cota de
    partida) no se parecen a las de una ortofoto. Separarlo es tambien lo que permite que su celda
    tenga su propio motivo si `gdal_contour` falta.

    - El DXF sale **con la cota de cada curva** (grupo 38 de su polilínea): un DXF con curvas
      planas es un dibujo de lineas que nadie sabe a que altura estan. El Shapefile y el GeoPackage
      llevan la cota en el campo `ELEV`, que es lo que espera QGIS para rotular. El DXF se hace
      pasando por un GeoPackage 3D, porque `gdal_contour` escribe el DXF directo sin la cota.
    - La banda es la 1 y el valor sin dato es el que declara el archivo.
    - El DXF **no guarda el sistema de coordenadas**: las curvas quedan en el del modelo, y el
      recibo lo dice con su EPSG.
    """

    id = "gdal-curvas"
    nombre = "GDAL (curvas de nivel)"
    familia = "raster"
    prioridad = 10

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(
            ParDeFormatos(origen, destino)
            for origen in ORIGENES_DE_ELEVACION
            for destino in DESTINOS_DE_CURVAS
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
        faltan = [n for n in ("gdal_contour", "ogr2ogr") if not Path(_bin(n)).is_file()]
        if faltan:
            return Disponibilidad.no(
                "motor-no-disponible",
                f"Esta instalación de GDAL no trae {' ni '.join(f'`{n}`' for n in faltan)}.",
                sugerencia="Ver INSTALL.md: es parte de las utilidades de GDAL.",
                version=gdal.version,
            )
        return Disponibilidad.si(gdal.version)

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        return (
            OpcionDeMotor(
                "intervalo_m",
                "Intervalo entre curvas (m)",
                "decimal",
                por_defecto=10,
                minimo=INTERVALO_MINIMO_M,
                maximo=100000,
                ayuda=(
                    "Cada cuántos metros de altura va una curva. Se elige según la escala: 0,5 m "
                    "para un plano de detalle, 10 m para una carta. Con un intervalo mayor que el "
                    "desnivel del modelo no sale ninguna curva, y el trabajo lo dice."
                ),
            ),
            OpcionDeMotor(
                "desde_m",
                "Cota de partida (m)",
                "decimal",
                por_defecto=0,
                minimo=-100000,
                maximo=100000,
                ayuda=(
                    "Las curvas caen en la cota de partida más un número entero de intervalos. "
                    "Con 0 y un intervalo de 10, en 100, 110, 120… Con 5, en 105, 115, 125…"
                ),
            ),
        )

    def plan(self, trabajo) -> PlanDeEjecucion:
        origen = Path(trabajo.source_path)
        destino = Path(trabajo.output_path)
        parcial = ruta_parcial(destino)
        opciones = dict(trabajo.options or {})

        intervalo = _numero_finito(opciones.get("intervalo_m", 10), "el intervalo")
        if intervalo < INTERVALO_MINIMO_M:
            raise ValueError(
                f"El intervalo ({intervalo} m) es demasiado pequeño para ser una curva de nivel."
            )
        partida = _numero_finito(opciones.get("desde_m", 0) or 0, "la cota de partida")

        controlador = DESTINOS_DE_CURVAS.get(trabajo.target_format_code)
        if controlador is None:
            raise ValueError(
                f"«{trabajo.target_format_code}» no es un destino de curvas de nivel "
                f"({', '.join(DESTINOS_DE_CURVAS)})."
            )

        # **B-04, a la manera de este programa:** `gdal_contour` no tiene `-if`, y con un `.asc` que
        # es en realidad un VRT leeria otros archivos del disco. Un ASCII Grid empieza por `ncols`
        # (o `NCOLS`): lo que no empieza asi no se pasa.
        if getattr(trabajo, "source_format_code", "") in LECTOR_ESTRICTO:
            with origen.open("rb") as archivo:
                cabecera = archivo.read(32).lstrip().lower()
            if not cabecera.startswith((b"ncols", b"nrows", b"xllcorner", b"xllcenter")):
                raise ValueError(
                    "El archivo dice ser un ASCII Grid y no empieza como uno: no se abre."
                )

        es_dxf = trabajo.target_format_code == "dxf"
        # **El DXF se hace en dos pasos, y no por capricho.** Con `gdal_contour -f DXF -3d` el
        # controlador crea la capa como 2D y tira la Z: sale un DXF con 29 polilíneas **sin cota**,
        # válido y inservible. Se midió. Con un GeoPackage 3D en medio, `ogr2ogr` sí escribe la
        # elevación de cada polilínea (grupo 38). El intermedio cuelga del nombre del parcial y el
        # corredor lo borra con él.
        intermedio = parcial.with_name(parcial.name + ".curvas3d.gpkg")
        primero = intermedio if es_dxf else parcial
        argv: list[str] = [
            _bin("gdal_contour"),
            "-i",
            repr(intervalo),
            "-off",
            repr(partida),
            "-f",
            "GPKG" if es_dxf else controlador,
            "-nln",
            CAPA_DE_CURVAS,
            "-a",
            CAMPO_DE_COTA,
        ]
        if es_dxf:
            argv.append("-3d")
        argv += [str(origen), str(primero)]

        posteriores: tuple[tuple[str, ...], ...] = ()
        if es_dxf:
            # `-select ""`: el DXF no tiene campos; sin él `ogr2ogr` da un error por cada uno.
            posteriores = (
                (_bin("ogr2ogr"), "-f", "DXF", "-select", "", str(parcial), str(intermedio)),
            )

        return PlanDeEjecucion(
            argv=tuple(argv),
            ruta_de_salida=destino,
            posteriores=posteriores,
            salida_en_posteriores=es_dxf,
            env=entorno_de_gdal(GDAL_CACHEMAX="512"),
            timeout_s=MotorGdalRaster()._presupuesto(trabajo),
            analizador_de_progreso=analizar_progreso,
        )

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        """Se le pregunta a OGR: ¿hay curvas, y a qué cotas?

        `gdal_contour` devuelve 0 y escribe un archivo válido **sin ninguna entidad** cuando el
        intervalo es mayor que el desnivel o la banda no es una elevación: es el fallo que importa.
        """
        base = super().verificar(trabajo, salida)
        if not base.correcta:
            return base

        from apps.vector.motores import _epsg_de as epsg_de_capas
        from apps.vector.motores import _ogrinfo

        info = _ogrinfo(salida)
        if info is None:
            return Verificacion(
                correcta=False,
                motivo="OGR no puede leer el archivo que acaba de escribir.",
                codigo_motivo="salida-invalida",
            )
        capas = info.get("layers", []) or []
        curvas = sum(int(capa.get("featureCount", 0) or 0) for capa in capas)
        detalles = {
            "curvas": curvas,
            "controlador": info.get("driverShortName", ""),
            "intervalo_m": (trabajo.options or {}).get("intervalo_m", 10),
            "bytes": salida.stat().st_size,
        }
        if not curvas:
            return Verificacion(
                correcta=False,
                motivo=(
                    "No salió ninguna curva. Suele ser un intervalo mayor que el desnivel del "
                    "modelo, o que la banda 1 no sea una elevación (una ortofoto no tiene curvas)."
                ),
                codigo_motivo="salida-invalida",
                detalles=detalles,
            )
        no_es_elevacion = _no_es_un_modelo_de_elevacion(trabajo)
        if no_es_elevacion:
            return Verificacion(
                correcta=False,
                motivo=no_es_elevacion,
                codigo_motivo="salida-invalida",
                detalles=detalles,
            )
        epsg = epsg_de_capas(capas)
        # Un ASCII Grid no lleva sistema dentro (su `.prj` queda al lado y no se copia): las curvas
        # tampoco lo llevan, y no hay reproyección, así que es un aviso y no una detención.
        sin_sistema_incrustado = trabajo.target_format_code == "dxf" or (
            getattr(trabajo, "source_format_code", "") == "asc"
        )
        if epsg:
            detalles["epsg"] = epsg
        elif trabajo.source_crs_code and not sin_sistema_incrustado:
            return Verificacion(
                correcta=False,
                motivo=(
                    f"El modelo estaba en EPSG:{trabajo.source_crs_code} y las curvas no "
                    "declaran ningún sistema de referencia."
                ),
                codigo_motivo="salida-invalida",
                detalles=detalles,
            )
        if not epsg:
            donde = f" (EPSG:{trabajo.source_crs_code})" if trabajo.source_crs_code else ""
            if trabajo.target_format_code == "dxf":
                quien = "El DXF no guarda el sistema de coordenadas"
            elif getattr(trabajo, "source_format_code", "") == "asc":
                quien = "El modelo (un ASCII Grid) no trae el sistema de coordenadas dentro"
            else:
                quien = "El modelo no declara su sistema de coordenadas"
            detalles["avisos"] = [
                f"{quien}: las curvas están en el sistema del modelo{donde} pero no lo declaran."
            ]
        return Verificacion(correcta=True, detalles=detalles)


def _no_es_un_modelo_de_elevacion(trabajo) -> str:
    """El motivo si el origen no puede ser un modelo de elevación; vacío si puede (o no se sabe).

    Una ortofoto RGB tiene la banda 1 de 0 a 255, y sacarle curvas «de nivel» da unas 25 líneas que
    parecen un resultado y no lo son. Se le pregunta a GDAL (`gdalinfo`), no se supone.
    """
    info = _gdalinfo(Path(trabajo.source_path))
    if info is None:
        return ""
    bandas = info.get("bands", []) or []
    if len(bandas) > 1:
        return (
            f"El archivo tiene {len(bandas)} bandas: es una imagen, no un modelo de elevación. "
            "Las curvas de nivel salen de una sola banda con la altura de cada píxel."
        )
    return ""


def _numero_finito(valor, que: str) -> float:
    import math

    try:
        numero = float(valor)
    except (TypeError, ValueError) as fallo:
        raise ValueError(f"{que.capitalize()} no es un número.") from fallo
    if not math.isfinite(numero):
        raise ValueError(f"{que.capitalize()} no es un número finito.")
    return numero


def registrar_todos() -> None:
    registry.registrar(MotorGdalRaster())
    registry.registrar(MotorCurvasDeNivel())
    registry.registrar(MotorEcw())
    for formato, (controlador, de_donde) in ORIGENES_PROPIETARIOS.items():
        registry.registrar(MotorLecturaPropietaria(formato, controlador, de_donde))
