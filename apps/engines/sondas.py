"""Que herramientas hay en esta maquina.

## Dos reglas que se heredan de AeroBim

**Una sonda no ejecuta una conversion.** Nunca. Se pregunta la version, se listan los
controladores, se mira si un archivo existe -- nada mas. Esto se consulta al pintar una
pagina.

**Y ni siquiera lanzar el programa es gratis.** `estado_del_conversor()` de AeroBim lo dice
literal: «no se lanza el programa para preguntarle su versión: arrancarlo cuesta segundos y
esto se consulta al pintar una página». Aqui hay una excepcion medida -- GDAL, del que hay
que enumerar controladores -- y por eso se cachea diez minutos.

## La sutileza que decide media matriz

**Que el controlador este no significa que sepa escribir.** El controlador ECW de GDAL lee
siempre; escribir necesita ademas la SDK con clave OEM de Hexagon. Comprobar solo que el
controlador aparece y dar la conversion por buena es lo que produce un trabajo que corre
veinte minutos y muere al final. Por eso `sondar_ecw()` mira tres cosas por separado, y da
tres motivos distintos: son tres arreglos distintos.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

from .base import Disponibilidad

#: Cuanto se recuerda el resultado de una sonda. Diez minutos: suficiente para que pintar
#: veinte paginas no lance veinte procesos, y poco para que instalar GDAL se note pronto.
SEGUNDOS_DE_CACHE = 600

#: Nadie tarda tanto en decir su version. Si tarda, algo va mal y no vale la pena esperar.
TIEMPO_MAXIMO_SONDA_S = 15


def _carpeta_de(valor: str) -> Path | None:
    ruta = (valor or "").strip().strip('"')
    return Path(ruta) if ruta else None


def _ejecutable(nombre: str, carpeta_configurada: str) -> str | None:
    """Donde esta el programa: primero donde lo pone la configuracion, luego el PATH.

    Buscar en el PATH como respaldo es lo que hace que quien instale bien las herramientas
    no tenga que configurar nada -- el mismo detalle que `ruta_por_defecto()` de AeroBim.
    """
    carpeta = _carpeta_de(carpeta_configurada)
    if carpeta is not None:
        candidato = carpeta / f"{nombre}.exe" if os.name == "nt" else carpeta / nombre
        if candidato.is_file():
            return str(candidato)
    return shutil.which(nombre)


def _preguntar_version(ejecutable: str, *argumentos: str, contiene: str = "") -> str | None:
    """La linea de version que imprime la herramienta.

    `contiene` existe porque **no todas contestan en la primera linea**: `pdal --version`
    abre con una fila de guiones a modo de banner, y quedarse con ella daria una version
    que es `-----------`. Cuando se indica, se busca la primera linea que lo mencione.
    """
    try:
        # `ejecutable` sale de `_ejecutable()`, que solo devuelve una ruta configurada por
        # el administrador en `.env` o algo hallado en el PATH: nunca un dato de la
        # peticion. Va como lista y con `shell=False`, asi que no hay interpretacion de
        # metacaracteres, y los argumentos son literales del codigo.
        resultado = subprocess.run(  # nosec B603
            [ejecutable, *argumentos],
            capture_output=True,
            text=True,
            timeout=TIEMPO_MAXIMO_SONDA_S,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if resultado.returncode != 0:
        return None

    lineas = [
        linea.strip()
        for linea in (resultado.stdout or resultado.stderr).splitlines()
        if linea.strip() and set(linea.strip()) != {"-"}
    ]
    if not lineas:
        return None
    if contiene:
        for linea in lineas:
            if contiene.lower() in linea.lower():
                return linea
    return lineas[0]


@dataclass(frozen=True)
class EstadoGdal:
    disponible: bool
    version: str = ""
    ejecutable: str = ""
    #: Nombres cortos de los controladores, en mayusculas.
    controladores: frozenset[str] = frozenset()
    #: Los que ademas saben crear archivos. **No es lo mismo**, y es lo que decide si una
    #: celda de la matriz esta viva.
    escribibles: frozenset[str] = frozenset()
    motivo: str = ""


@lru_cache(maxsize=1)
def _formatos_gdal_crudo(ejecutable: str) -> str:
    # Misma justificacion que en `_preguntar_version`: ruta de administrador, lista de
    # argumentos literales, `shell=False`.
    resultado = subprocess.run(  # nosec B603
        [ejecutable, "--formats"],
        capture_output=True,
        text=True,
        timeout=TIEMPO_MAXIMO_SONDA_S,
        check=False,
        shell=False,
    )
    return resultado.stdout or ""


#: `gdalinfo --formats` imprime una linea por controlador, asi:
#:     GTiff -raster- (rw+uvs): GeoTIFF (*.tif, *.tiff)
#: Las banderas entre parentesis son lo que importa: `r` lee, `w` escribe, `+` crea.
#:
#: **El nombre puede llevar espacios**, y darlo por hecho costo cuatro controladores. Con
#: `(\S+)` la linea `ESRI Shapefile -vector- (rw+uv): ...` no coincide con nada, asi que
#: `ESRI Shapefile`, `MapInfo File` e `Interlis 1` y `2` desaparecian de la lista -- y una
#: celda de la matriz que dice «no se puede escribir SHP» porque una expresion regular no
#: supo leer un espacio es exactamente la clase de fallo que esta aplicacion existe para no
#: cometer. En raster no se notaba: ahi los nombres son de una sola palabra.
PATRON_FORMATO = re.compile(r"^\s{2}(.+?)\s+-[\w,\s]+-\s+\(([^)]*)\):")


def sondar_gdal() -> EstadoGdal:
    """GDAL: si esta, que versión, y **que sabe escribir**."""
    guardado = cache.get("motores:gdal")
    if guardado is not None:
        return guardado

    ejecutable = _ejecutable("gdalinfo", getattr(settings, "GDAL_BIN", ""))
    if ejecutable is None:
        estado = EstadoGdal(
            disponible=False,
            motivo=(
                "No se encontro gdalinfo. Instala GDAL (OSGeo4W, QGIS o conda-forge) y "
                "apunta AEROCONVERT_GDAL_BIN a su carpeta bin."
            ),
        )
        cache.set("motores:gdal", estado, SEGUNDOS_DE_CACHE)
        return estado

    version = _preguntar_version(ejecutable, "--version") or ""
    controladores: set[str] = set()
    escribibles: set[str] = set()
    try:
        for linea in _formatos_gdal_crudo(ejecutable).splitlines():
            coincidencia = PATRON_FORMATO.match(linea)
            if not coincidencia:
                continue
            nombre, banderas = coincidencia.group(1).upper(), coincidencia.group(2)
            controladores.add(nombre)
            if "w" in banderas:
                escribibles.add(nombre)
    except (OSError, subprocess.SubprocessError):
        pass

    estado = EstadoGdal(
        disponible=True,
        version=version,
        ejecutable=ejecutable,
        controladores=frozenset(controladores),
        escribibles=frozenset(escribibles),
    )
    cache.set("motores:gdal", estado, SEGUNDOS_DE_CACHE)
    return estado


@lru_cache(maxsize=1)
def _formatos_ogr_crudo(ejecutable: str) -> str:
    # Misma justificacion que en `_preguntar_version`.
    resultado = subprocess.run(  # nosec B603
        [ejecutable, "--formats"],
        capture_output=True,
        text=True,
        timeout=TIEMPO_MAXIMO_SONDA_S,
        check=False,
        shell=False,
    )
    return resultado.stdout or ""


def sondar_ogr() -> EstadoGdal:
    """OGR: la mitad vectorial de GDAL, y **hay que sondarla aparte**.

    `gdalinfo --formats` lista los controladores **raster** y `ogrinfo --formats` los
    vectoriales. Son listas distintas: preguntarle a `gdalinfo` por GPKG o por DXF no los
    encuentra, y dar por hecho que «si GDAL esta, OGR escribe DXF» apagaria media matriz
    vectorial por el motivo equivocado.

    Reutiliza `EstadoGdal` porque la respuesta tiene la misma forma: version, controladores
    y -- lo que de verdad importa -- cuales saben **crear** archivos.
    """
    guardado = cache.get("motores:ogr")
    if guardado is not None:
        return guardado

    ejecutable = _ejecutable("ogrinfo", getattr(settings, "GDAL_BIN", ""))
    if ejecutable is None:
        estado = EstadoGdal(
            disponible=False,
            motivo=(
                "No se encontro ogrinfo. Viene con GDAL: instalalo (OSGeo4W, QGIS o "
                "conda-forge) y apunta AEROCONVERT_GDAL_BIN a su carpeta bin."
            ),
        )
        cache.set("motores:ogr", estado, SEGUNDOS_DE_CACHE)
        return estado

    version = _preguntar_version(ejecutable, "--version") or ""
    controladores: set[str] = set()
    escribibles: set[str] = set()
    try:
        for linea in _formatos_ogr_crudo(ejecutable).splitlines():
            coincidencia = PATRON_FORMATO.match(linea)
            if not coincidencia:
                continue
            nombre, banderas = coincidencia.group(1).upper(), coincidencia.group(2)
            controladores.add(nombre)
            if "w" in banderas:
                escribibles.add(nombre)
    except (OSError, subprocess.SubprocessError):
        pass

    estado = EstadoGdal(
        disponible=True,
        version=version,
        ejecutable=ejecutable,
        controladores=frozenset(controladores),
        escribibles=frozenset(escribibles),
    )
    cache.set("motores:ogr", estado, SEGUNDOS_DE_CACHE)
    return estado


def sondar_proj() -> Disponibilidad:
    """Que PROJ tenga su base de datos donde dice.

    Mezclar el GDAL de un sitio con el `proj` de otro es un clasico, y no falla de forma
    limpia: o dice «Cannot find proj.db», o reproyecta con datos equivocados. Lo segundo
    es peor, porque sale un archivo que parece bien.
    """
    for variable in ("PROJ_DATA", "PROJ_LIB"):
        carpeta = _carpeta_de(os.environ.get(variable, ""))
        if carpeta is not None and (carpeta / "proj.db").is_file():
            return Disponibilidad.si(str(carpeta / "proj.db"))

    gdal = sondar_gdal()
    if gdal.disponible and gdal.ejecutable:
        vecina = Path(gdal.ejecutable).parent.parent / "share" / "proj" / "proj.db"
        if vecina.is_file():
            return Disponibilidad.si(str(vecina))

    return Disponibilidad.no(
        "proj-descolocado",
        "No se encontro proj.db.",
        sugerencia="Define PROJ_DATA apuntando a la carpeta que contiene proj.db.",
    )


def sondar_ecw() -> Disponibilidad:
    """ECW, en tres preguntas separadas porque son tres arreglos distintos.

    Escribir ECW exige la SDK de Hexagon con clave OEM, de pago. Sin ella la fila queda
    apagada -- **no oculta** -- con su motivo y con las alternativas que si sirven.
    """
    alternativas = ("cog", "jp2")

    binario = (getattr(settings, "ECW_BIN", "") or "").strip()
    if binario:
        if Path(binario).is_file():
            return Disponibilidad.si(f"conversor externo: {binario}")
        return Disponibilidad.no(
            "sin-binario-ecw",
            f"AEROCONVERT_ECW_BIN apunta a {binario}, y ahi no hay ningún archivo.",
            sugerencia="Corrige la ruta o deja la variable vacia.",
            alternativas=alternativas,
        )

    gdal = sondar_gdal()
    if not gdal.disponible:
        return Disponibilidad.no(
            "motor-no-disponible",
            gdal.motivo,
            sugerencia="Revisa INSTALL.md.",
            alternativas=alternativas,
        )

    if "ECW" not in gdal.controladores:
        return Disponibilidad.no(
            "sin-driver-ecw",
            "Esta instalacion de GDAL no trae el controlador ECW, ni para leer.",
            sugerencia=(
                "Hace falta una compilacion de GDAL con la SDK de Hexagon. La de QGIS y la "
                "de conda-forge no la traen."
            ),
            alternativas=alternativas,
            version=gdal.version,
        )

    clave = (getattr(settings, "ECW_ENCODE_KEY", "") or "").strip()
    empresa = (getattr(settings, "ECW_ENCODE_COMPANY", "") or "").strip()
    if not (clave and empresa):
        return Disponibilidad.no(
            "sin-clave-ecw",
            "El controlador ECW lee, pero escribir exige una clave OEM de Hexagon.",
            sugerencia=(
                "Configura AEROCONVERT_ECW_ENCODE_KEY y AEROCONVERT_ECW_ENCODE_COMPANY, o "
                "usa COG o JP2, que no necesitan licencia."
            ),
            alternativas=alternativas,
            version=gdal.version,
        )

    if "ECW" not in gdal.escribibles:
        return Disponibilidad.no(
            "sin-driver-ecw",
            "El controlador ECW esta pero no declara capacidad de escritura.",
            sugerencia="Es una compilacion de solo lectura de la SDK.",
            alternativas=alternativas,
            version=gdal.version,
        )

    return Disponibilidad.si(gdal.version)


def sondar_pdal() -> Disponibilidad:
    ejecutable = _ejecutable("pdal", getattr(settings, "PDAL_BIN", ""))
    if ejecutable is None:
        return Disponibilidad.no(
            "motor-no-disponible",
            "No se encontro pdal.",
            sugerencia="Viene con QGIS y con conda-forge. Ver INSTALL.md.",
        )
    version = _preguntar_version(ejecutable, "--version", contiene="pdal")
    if version is None:
        return Disponibilidad.no(
            "motor-no-disponible", f"{ejecutable} esta pero no responde a --version."
        )
    return Disponibilidad.si(version)


@lru_cache(maxsize=1)
def _controladores_pdal(ejecutable: str) -> frozenset[str]:
    try:
        resultado = subprocess.run(  # nosec B603
            [ejecutable, "--drivers"],
            capture_output=True,
            text=True,
            timeout=TIEMPO_MAXIMO_SONDA_S,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    nombres = set()
    for linea in (resultado.stdout or "").splitlines():
        primera = linea.strip().split(" ", 1)[0]
        if primera.startswith(("readers.", "writers.", "filters.")):
            nombres.add(primera)
    return frozenset(nombres)


def sondar_pdal_controlador(nombre: str) -> Disponibilidad:
    """Si **este** PDAL trae ese controlador.

    Los controladores de PDAL se fijan al compilarlo: el que trae QGIS no incluye E57, y no
    hay forma de anadirlo sin reinstalar. Distinguirlo de «PDAL no esta» importa, porque el
    arreglo es distinto -- uno se instala, el otro se cambia de compilacion.
    """
    ejecutable = _ejecutable("pdal", getattr(settings, "PDAL_BIN", ""))
    if ejecutable is None:
        return Disponibilidad.no(
            "motor-no-disponible",
            "No se encontro pdal.",
            sugerencia="Viene con QGIS y con conda-forge. Ver INSTALL.md.",
        )
    if nombre not in _controladores_pdal(ejecutable):
        return Disponibilidad.no(
            "sin-driver-pdal",
            f"Este PDAL no trae {nombre}.",
            sugerencia=(
                "Los controladores se fijan al compilar PDAL. El de QGIS no lo incluye; una "
                "compilacion de conda-forge con esa opcion si."
            ),
            alternativas=("las", "laz", "copc"),
        )
    return Disponibilidad.si(_preguntar_version(ejecutable, "--version", contiene="pdal") or "pdal")


def sondar_oda() -> Disponibilidad:
    """ODA File Converter, para DWG y DGN.

    Copia literal de `estado_del_conversor()` de AeroBim, incluido lo de no ejecutarlo:
    se mira que la ruta configurada apunte a un archivo, y ya.
    """
    ruta = (getattr(settings, "ODA_CONVERTER", "") or "").strip()
    if not ruta:
        encontrado = shutil.which("ODAFileConverter")
        if encontrado:
            return Disponibilidad.si(encontrado)
        return Disponibilidad.no(
            "sin-conversor",
            "No hay conversor configurado.",
            sugerencia=(
                "Instala ODA File Converter (gratuito, de la Open Design Alliance) y apunta "
                "AEROCONVERT_ODA_CONVERTER a su ejecutable."
            ),
            alternativas=("dxf",),
        )
    if not Path(ruta).is_file():
        return Disponibilidad.no(
            "sin-conversor",
            f"AEROCONVERT_ODA_CONVERTER apunta a {ruta}, y ahi no hay ningún archivo.",
            alternativas=("dxf",),
        )
    return Disponibilidad.si(ruta)


def olvidar() -> None:
    """Vacia la cache de sondas. La usan las pruebas y el boton de volver a sondear."""
    cache.delete("motores:gdal")
    cache.delete("motores:ogr")
    _formatos_gdal_crudo.cache_clear()
    _formatos_ogr_crudo.cache_clear()
    _controladores_pdal.cache_clear()
