"""Motores vectoriales, CAD y de topografía.

## Dos motores y no uno

`MotorOgrVector` hace la conversión vectorial normal -- SHP, GPKG, GeoJSON, KML, DXF entre
sí -- y `MotorPuntosTopograficos` hace **una sola cosa**: convertir una libreta de puntos.

Están separados porque el comando no se parece. Una libreta de puntos no es un formato
vectorial: es texto delimitado sin geometría, y para que OGR construya los puntos hay que
decirle qué columna es la X y cuál la Y. Ese dato lo resuelve `apps.formats.puntos` con el
rango UTM antes de llegar aquí, y viaja en las opciones del trabajo.

## Los tres sitios donde esto se puede escribir mal

**1. El orden de columnas.** Es el motivo de que exista `apps.formats.puntos`. Aquí solo se
traduce a `-oo X_POSSIBLE_NAMES` y compañía; el criterio está allí.

**2. KML exige EPSG:4326, y no avisa.** El controlador escribe las coordenadas tal cual se
le den. Un KML con estes y nortes UTM dentro es sintácticamente válido, abre en Google Earth,
y pone la obra a cientos de kilómetros del planeta -- las coordenadas se interpretan como
grados. Por eso el motor **añade la reproyección él mismo** cuando el destino es KML, y no lo
deja como opción del formulario: nadie tiene que acordarse de esto.

**3. Sin CRS no hay conversión posible.** Una libreta de puntos no lleva sistema de
referencia dentro, así que hay que declararlo. Convertirla sin CRS produciría una capa de
puntos que no está en ninguna parte, y para KML además no se podría ni reproyectar. Lo exige
el runner, y aquí se declara para que la matriz lo diga.
"""

from __future__ import annotations

import re
import shutil
import sys
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
from apps.formats import catalogo
from apps.formats import puntos as puntos_mod
from apps.vector import desde_landxml

#: El controlador de OGR para cada codigo del catalogo.
#:
#: `ESRI Shapefile` y `MapInfo File` llevan espacio en el nombre corto. Va tal cual: es lo
#: que espera `-f`, y es tambien lo que hay que buscar en la lista de la sonda.
CONTROLADOR = {
    "shp": "ESRI Shapefile",
    "gpkg": "GPKG",
    "geojson": "GeoJSON",
    "kml": "LIBKML",
    "kmz": "LIBKML",
    "gml": "GML",
    "gpx": "GPX",
    "dxf": "DXF",
}

#: Origenes que OGR lee sin ayuda de nadie.
ORIGENES_VECTORIALES = ("shp", "gpkg", "geojson", "kml", "kmz", "gml", "gpx", "dxf", "dgn")

#: Destinos que se ofrecen. `dgn` y `dwg` no estan: el catalogo ya dice que no se escriben.
DESTINOS = ("gpkg", "shp", "geojson", "kml", "kmz", "dxf")

#: Destinos de una libreta de puntos. Los mismos, y por el mismo motivo: lo que se quiere de
#: unos puntos de control es verlos en el programa de turno.
DESTINOS_DE_PUNTOS = ("gpkg", "shp", "geojson", "kml", "kmz", "dxf")

#: Los que **obligan** a EPSG:4326. Ver el punto 2 del docstring del modulo.
DESTINOS_EN_GRADOS = frozenset({"kml", "kmz", "geojson"})

#: Nombres de los campos de salida cuando los ponemos nosotros.
#:
#: Diez caracteres o menos: el formato Shapefile los trunca ahi y sin avisar de forma
#: legible. `descripcion` saldria como `descripcio` en SHP y `descripcion` en GPKG, o sea el
#: mismo dato con dos nombres segun el destino. Elegirlos cortos evita esa diferencia.
CAMPO_PUNTO = "punto"
CAMPO_DESCRIPCION = "descrip"


def _bin(nombre: str) -> str:
    """Donde esta la herramienta de OGR. Configuracion primero, PATH despues."""
    carpeta = (getattr(settings, "GDAL_BIN", "") or "").strip().strip('"')
    if carpeta:
        import os

        candidato = Path(carpeta) / (f"{nombre}.exe" if os.name == "nt" else nombre)
        if candidato.is_file():
            return str(candidato)
    return shutil.which(nombre) or nombre


#: Los nombres de campo que pone OGR con `HEADERS=NO`: `field_1`, `field_2`...
PATRON_CAMPO_GENERADO = re.compile(r"^field_\d{1,4}$")


def _es_campo_generado(nombre: str) -> bool:
    """`True` si ese nombre de campo lo pusimos nosotros y no sale del archivo.

    Es la puerta de la consulta de renombrado: solo entra en el SQL lo que encaja aquí. Con
    encabezado los nombres son los rótulos del archivo -- texto de otra persona -- y ese
    camino no construye consulta ninguna.
    """
    return bool(PATRON_CAMPO_GENERADO.match(nombre or ""))


def _nombre_de_capa(destino: Path) -> str:
    """El nombre de la capa dentro del archivo de salida.

    Se toma del nombre del archivo y se limpia: un GPKG con una capa llamada
    `puntos control cruce minero` obliga a citarla entre comillas en cada consulta.
    """
    limpio = "".join(c if c.isalnum() else "_" for c in destino.stem.lower())
    return limpio.strip("_") or "puntos"


def _sonda_ogr() -> Disponibilidad:
    """Disponibilidad comun a los dos motores."""
    from apps.engines import sondas

    ogr = sondas.sondar_ogr()
    if not ogr.disponible:
        return Disponibilidad.no("motor-no-disponible", ogr.motivo, sugerencia="Ver INSTALL.md.")
    proj = sondas.sondar_proj()
    if not proj.disponible:
        # Sin PROJ en su sitio la reproyeccion usa el dato equivocado, y KML **siempre**
        # reproyecta. Callarlo aqui seria entregar un KML en el sitio equivocado.
        return Disponibilidad.no(
            proj.codigo_motivo, proj.mensaje, sugerencia=proj.sugerencia, version=ogr.version
        )
    return Disponibilidad.si(ogr.version)


def _epsg_del_trabajo(trabajo) -> str:
    """`EPSG:32719` a partir del CRS de origen o del declarado. Cadena vacía si no hay."""
    autoridad = getattr(trabajo, "source_crs_authority", "") or "EPSG"
    codigo = getattr(trabajo, "source_crs_code", "") or ""
    return f"{autoridad}:{codigo}" if codigo else ""


class MotorPuntosTopograficos(Motor):
    """Libretas de puntos PNEZD/PENZD a algo que se pueda abrir.

    Es el motor que resuelve un dolor semanal y no necesita ninguna licencia.
    """

    id = "ogr-puntos"
    nombre = "OGR sobre libreta de puntos"
    familia = "vector"
    prioridad = 10

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(ParDeFormatos("puntos", destino) for destino in DESTINOS_DE_PUNTOS)

    def disponibilidad(self) -> Disponibilidad:
        return _sonda_ogr()

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        """El orden de columnas, y nada más.

        Se ofrece **aunque la detección haya salido con certeza**, porque el detector puede
        acertar en el rango y aun así equivocarse en un archivo raro, y el formulario es el
        único sitio donde alguien puede contradecirlo. El valor por omisión lo pone la
        inspección; aquí solo se declara que la opción existe y cuáles son los valores
        posibles.
        """
        return (
            OpcionDeMotor(
                "orden",
                "Orden de columnas",
                "eleccion",
                por_defecto="pnezd",
                elecciones=tuple(
                    (codigo, puntos_mod.NOMBRES_DE_ORDEN[codigo]) for codigo in puntos_mod.ORDENES
                ),
                ayuda=(
                    "Se deduce del rango UTM de las coordenadas. Elegirlo mal no da ningún "
                    "error: deja los puntos a miles de kilómetros de donde van."
                ),
            ),
        )

    def plan(self, trabajo) -> PlanDeEjecucion:
        origen = Path(trabajo.source_path)
        destino = Path(trabajo.output_path)
        parcial = ruta_parcial(destino)

        opciones = dict(trabajo.options or {})
        orden = str(opciones.get("orden", "") or "")
        campos = puntos_mod.campos_ogr(origen, orden=orden)

        controlador = CONTROLADOR.get(trabajo.target_format_code, "GPKG")
        epsg = _epsg_del_trabajo(trabajo)

        argv: list[str] = [_bin("ogr2ogr"), "-f", controlador, str(parcial), str(origen)]

        # Cómo se lee la libreta. `KEEP_GEOM_COLUMNS=NO` evita que el este y el norte
        # aparezcan **además** como columnas de texto: el mismo dato dos veces, y en un DXF
        # eso son etiquetas encima de cada punto.
        argv += [
            "-oo",
            f"HEADERS={'YES' if campos.tiene_encabezado else 'NO'}",
            "-oo",
            f"SEPARATOR={campos.separador_ogr}",
            "-oo",
            "AUTODETECT_TYPE=YES",
            "-oo",
            f"X_POSSIBLE_NAMES={campos.campo_este}",
            "-oo",
            f"Y_POSSIBLE_NAMES={campos.campo_norte}",
            "-oo",
            f"Z_POSSIBLE_NAMES={campos.campo_cota}",
            "-oo",
            "KEEP_GEOM_COLUMNS=NO",
        ]

        consulta = self._renombrado(origen, campos)
        if consulta:
            argv += ["-sql", consulta]

        # **`-a_srs` y `-t_srs` son mutuamente excluyentes**, y `ogr2ogr` lo dice a la cara:
        # «Argument '-t_srs' not allowed with '-a_srs'». Tiene sentido -- uno etiqueta sin
        # tocar los números y el otro los mueve -- y son dos casos distintos:
        #
        # - Sin reproyección: `-a_srs` etiqueta. Es lo correcto para un GPKG o un SHP; las
        #   coordenadas ya están en ese sistema, solo que el archivo de texto no lo dice.
        # - Con reproyección: hay que decir de dónde salen (`-s_srs`) y a dónde van
        #   (`-t_srs`). Y de dónde salen no lo sabe nadie más que la persona que lo declaró:
        #   el CSV no lo lleva dentro.
        if epsg and trabajo.target_format_code in DESTINOS_EN_GRADOS:
            argv += ["-s_srs", epsg, "-t_srs", "EPSG:4326"]
        elif epsg:
            argv += ["-a_srs", epsg]

        argv += ["-nln", self._nombre_de_capa(destino)]

        return PlanDeEjecucion(
            argv=tuple(argv),
            ruta_de_salida=destino,
            env=entorno_de_gdal(),
            timeout_s=600,
            # `ogr2ogr` sin `-progress` no dice nada, y una libreta de puntos se convierte
            # en menos de un segundo: pedir avance seria ruido. Se declara mudo para que el
            # detector de atasco no lo vigile.
            emite_progreso=False,
        )

    def _renombrado(self, origen: Path, campos: puntos_mod.CamposOgr) -> str:
        """La consulta que pone nombres legibles a las columnas que sobreviven.

        Sin esto los atributos salen como `field_1` y `field_5`, que es exactamente lo que
        no se le manda a un cliente. Solo se hace cuando los nombres son nuestros -- con
        encabezado, los rótulos los puso quien hizo el archivo y no se le cambian.
        """
        if not campos.puede_renombrar:
            return ""

        seleccion = []
        if _es_campo_generado(campos.campo_punto):
            seleccion.append(f"{campos.campo_punto} AS {CAMPO_PUNTO}")
        if _es_campo_generado(campos.campo_descripcion):
            seleccion.append(f"{campos.campo_descripcion} AS {CAMPO_DESCRIPCION}")
        if not seleccion:
            return ""

        # El nombre de capa de un CSV es el nombre del archivo sin extension, y **lleva
        # espacios muy a menudo** (`puntos control cruce minero`), asi que va entre comillas
        # dobles: es como se cita un identificador en SQL de OGR.
        #
        # Y el nombre del archivo **lo elige quien usa la aplicacion**, asi que se escapa.
        # En Windows no se puede llamar a un archivo con una comilla doble dentro, pero en
        # Linux si, y un `foo".csv` cerraria la cita y dejaria el resto del nombre como SQL.
        # No es una base de datos -- es el SQL de OGR, sin DDL ni acceso a otra cosa -- pero
        # el resultado seria una consulta distinta de la pedida, o sea una conversion que
        # devuelve otras columnas sin avisar.
        #
        # Los dos nombres de campo se comprueban arriba contra `field_N`, que es lo unico
        # que generamos nosotros; con encabezado no se llega aqui.
        capa = origen.stem.replace('"', '""')
        # El `nosec` va **después** de haberlo arreglado, no en su lugar: bandit no sabe
        # distinguir un identificador citado y escapado de una concatenación cruda, y esto
        # no es una base de datos. Lo que lo hace seguro está tres párrafos arriba.
        return f'SELECT {", ".join(seleccion)} FROM "{capa}"'  # nosec B608

    def _nombre_de_capa(self, destino: Path) -> str:
        return _nombre_de_capa(destino)

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        return _verificar_con_ogrinfo(trabajo, salida, super().verificar(trabajo, salida))


class MotorLandXml(Motor):
    """Libreta de puntos → LandXML, escrito por nosotros.

    **OGR no trae controlador de LandXML**, ni de lectura ni de escritura: comprobado con
    `ogrinfo --formats`. Así que este motor no lanza una herramienta de fuera, lanza el
    nuestro — pero **lo lanza igual, como proceso hijo**, y no llama a la función desde la
    vista. Eso no es ceremonia: es lo que hace que se pueda cancelar, que tenga presupuesto
    de tiempo, y que un archivo enorme que agote la memoria no se lleve por delante el
    servidor. La misma decisión que hace que GDAL y PDAL corran fuera.

    Vale la pena frente al DXF que ya se puede hacer: un DXF entra en Civil 3D como dibujo
    —entidades sueltas— y un LandXML entra como **grupo de puntos COGO**, con su número y su
    descripción. Es la diferencia entre entregar un plano y entregar topografía.
    """

    id = "aeroconvert-landxml"
    nombre = "AeroConvert"
    familia = "vector"
    prioridad = 10

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset({ParDeFormatos("puntos", "landxml")})

    def disponibilidad(self) -> Disponibilidad:
        """Siempre. Es código propio y no depende de nada instalado.

        Es la única celda verde de la matriz que no necesita que haya nada en la máquina, y
        eso es parte de su valor: funciona en una VM pelada.
        """
        from django.conf import settings

        return Disponibilidad.si(f"AeroConvert {getattr(settings, 'VERSION', '')}".strip())

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        return (
            *MotorPuntosTopograficos().opciones(par),
            OpcionDeMotor(
                "grupo",
                "Nombre del grupo de puntos",
                "texto",
                por_defecto="",
                ayuda=(
                    "Como aparecerá el grupo en Civil 3D. Si se deja vacío, se usa el "
                    "nombre del archivo."
                ),
            ),
        )

    def plan(self, trabajo) -> PlanDeEjecucion:
        origen = Path(trabajo.source_path)
        destino = Path(trabajo.output_path)
        parcial = ruta_parcial(destino)
        opciones = dict(trabajo.options or {})

        argv = [
            sys.executable,
            "-m",
            "apps.vector.landxml",
            str(origen),
            str(parcial),
            "--orden",
            str(opciones.get("orden", "") or ""),
            "--epsg",
            (trabajo.source_crs_code or ""),
            "--nombre-crs",
            (getattr(trabajo, "source_crs_name", "") or ""),
            "--grupo",
            str(opciones.get("grupo", "") or ""),
        ]

        return PlanDeEjecucion(
            argv=tuple(argv),
            ruta_de_salida=destino,
            # `-m` resuelve el paquete desde el directorio de trabajo, así que el hijo tiene
            # que arrancar en la raíz del repositorio o no encontrará `apps`.
            cwd=Path(settings.BASE_DIR),
            timeout_s=1800,
            emite_progreso=False,
        )

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        """Aquí **no hay oráculo externo**, y no se finge que sí.

        OGR no lee LandXML, así que no hay una segunda herramienta a la que preguntarle si
        el archivo está bien. Comprobarlo con nuestro propio lector no probaría nada: sería
        el código dándose la razón.

        Lo que se comprueba es lo que sí es comprobable sin lector: que el XML esté bien
        formado —lo dice el analizador de la biblioteca estándar, que no es nuestro— y que
        traiga tantos `<CgPoint>` como puntos tenía la libreta. Eso atrapa el fallo que de
        verdad ocurre: un archivo válido, vacío o a medias.

        La aceptación de verdad es abrirlo en Civil 3D, y está escrita como procedimiento
        manual en `docs/PRUEBAS_CON_ORACULO.md`, igual que con ECW.
        """
        base = super().verificar(trabajo, salida)
        if not base.correcta:
            return base

        try:
            puestos = _contar_cgpoints(salida)
        except ValueError as fallo:
            return Verificacion(
                correcta=False,
                motivo=f"El LandXML escrito no está bien formado: {fallo}",
                codigo_motivo="salida-invalida",
            )

        detalles = {"entidades": puestos, "bytes": salida.stat().st_size}
        if trabajo.source_crs_code:
            detalles["epsg"] = trabajo.source_crs_code

        if not puestos:
            return Verificacion(
                correcta=False,
                motivo=(
                    "El archivo se escribió pero no tiene ningún punto dentro. Civil 3D lo "
                    "abriría sin protestar y sin enseñar nada."
                ),
                codigo_motivo="salida-invalida",
                detalles=detalles,
            )

        return Verificacion(correcta=True, detalles=detalles)


def _contar_cgpoints(ruta: Path) -> int:
    """Cuenta los `<CgPoint>` comprobando de paso que el XML esté bien formado.

    Con `iterparse` y no cargando el árbol: un LandXML de cien mil puntos son decenas de
    megabytes, y verificar la salida no puede costar más memoria que escribirla.

    El analizador es el de la biblioteca estándar y el archivo lo acabamos de escribir
    nosotros mismos en este equipo, así que no hay contenido ajeno que analizar aquí -- que
    es de lo que protege `defusedxml`.
    """
    from xml.etree import ElementTree  # nosec B405

    cuantos = 0
    try:
        for _evento, elemento in ElementTree.iterparse(ruta, events=("end",)):  # nosec B314
            if elemento.tag.rpartition("}")[2] == "CgPoint":
                cuantos += 1
            elemento.clear()
    except ElementTree.ParseError as fallo:
        raise ValueError(str(fallo)) from fallo
    return cuantos


class MotorDesdeLandXml(Motor):
    """LandXML → lo que sea, en dos pasos, y **solo los puntos**.

    OGR no lee LandXML, así que la primera mitad la hace un módulo nuestro que saca los
    `CgPoint` a un CSV intermedio, y la segunda es el `ogr2ogr` de siempre. El intermedio se
    llama colgando del parcial —`salida.parcial.shp.csv`— para que lo borre la limpieza que
    ya existe, que barre por ese prefijo.

    **Las superficies y los alineamientos no se convierten**, y eso se dice en vez de
    esconderse. No es una limitación de diseño: es que no hay ningún LandXML real con el que
    contrastar un lector de triangulados, y una malla mal leída produce una superficie
    plausible y equivocada. Un archivo que solo traiga superficies falla aquí con un motivo
    que lo explica, en vez de entregar una capa vacía.
    """

    id = "aeroconvert-desde-landxml"
    nombre = "AeroConvert + OGR"
    familia = "vector"
    prioridad = 10

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(ParDeFormatos("landxml", destino) for destino in DESTINOS_DE_PUNTOS)

    def disponibilidad(self) -> Disponibilidad:
        """El primer paso es nuestro, pero el segundo sigue siendo OGR."""
        return _sonda_ogr()

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        """Ninguna sobre el orden de columnas: **aquí esa pregunta no existe.**

        El CSV intermedio lo escribimos nosotros con nuestro propio encabezado, así que es
        el único camino del proyecto donde no hay nada que deducir ni que confirmar.
        """
        return MotorOgrVector().opciones(par)

    def plan(self, trabajo) -> PlanDeEjecucion:
        origen = Path(trabajo.source_path)
        destino = Path(trabajo.output_path)
        parcial = ruta_parcial(destino)
        # Colgando del parcial: `_limpiar_restos()` barre `<parcial>.*` al terminar.
        intermedio = parcial.with_name(parcial.name + ".csv")

        opciones = dict(trabajo.options or {})
        controlador = CONTROLADOR.get(trabajo.target_format_code, "GPKG")
        epsg = _epsg_del_trabajo(trabajo)

        argv = (
            sys.executable,
            "-m",
            "apps.vector.desde_landxml",
            str(origen),
            str(intermedio),
        )

        segundo: list[str] = [
            _bin("ogr2ogr"),
            "-f",
            controlador,
            str(parcial),
            str(intermedio),
            "-oo",
            "HEADERS=YES",
            "-oo",
            "SEPARATOR=COMMA",
            "-oo",
            "AUTODETECT_TYPE=YES",
            "-oo",
            f"X_POSSIBLE_NAMES={desde_landxml.CAMPO_ESTE}",
            "-oo",
            f"Y_POSSIBLE_NAMES={desde_landxml.CAMPO_NORTE}",
            "-oo",
            f"Z_POSSIBLE_NAMES={desde_landxml.CAMPO_COTA}",
            "-oo",
            "KEEP_GEOM_COLUMNS=NO",
        ]

        declarado = str(opciones.get("crs_destino", "") or "").strip()
        objetivo = ""
        if trabajo.target_crs_code:
            objetivo = f"{trabajo.target_crs_authority or 'EPSG'}:{trabajo.target_crs_code}"
        elif declarado:
            objetivo = declarado if ":" in declarado else f"EPSG:{declarado}"
        elif trabajo.target_format_code in DESTINOS_EN_GRADOS:
            objetivo = "EPSG:4326"

        # Las mismas dos ramas que en la libreta: etiquetar o mover, nunca las dos.
        if epsg and objetivo:
            segundo += ["-s_srs", epsg, "-t_srs", objetivo]
        elif epsg:
            segundo += ["-a_srs", epsg]

        segundo += ["-nln", _nombre_de_capa(destino)]

        return PlanDeEjecucion(
            argv=argv,
            ruta_de_salida=destino,
            posteriores=(tuple(segundo),),
            # El principal escribe el CSV intermedio; el parcial lo escribe `ogr2ogr`.
            salida_en_posteriores=True,
            env=entorno_de_gdal(),
            cwd=Path(settings.BASE_DIR),
            timeout_s=1800,
            emite_progreso=False,
        )

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        return _verificar_con_ogrinfo(trabajo, salida, super().verificar(trabajo, salida))


class MotorOgrVector(Motor):
    """Conversión vectorial normal: SHP, GPKG, GeoJSON, KML, DXF entre sí."""

    id = "ogr-vector"
    nombre = "OGR"
    familia = "vector"
    prioridad = 20

    def pares(self) -> frozenset[ParDeFormatos]:
        return frozenset(
            ParDeFormatos(origen, destino)
            for origen in ORIGENES_VECTORIALES
            for destino in DESTINOS
            if origen != destino
        )

    def disponibilidad(self) -> Disponibilidad:
        return _sonda_ogr()

    def opciones(self, par: ParDeFormatos) -> tuple[OpcionDeMotor, ...]:
        if par.destino in DESTINOS_EN_GRADOS:
            # No hay opciones que ofrecer: el destino manda el CRS y el motor lo pone. Dejar
            # aqui un selector de CRS invitaria a elegir uno que el formato no admite.
            return ()

        comunes = (
            OpcionDeMotor(
                "solo_geometria",
                "Descartar los atributos",
                "booleano",
                por_defecto=False,
                ayuda="Útil para un DXF que solo tiene que dibujar.",
            ),
        )

        formato = catalogo.FORMATOS.get(par.destino)
        if formato is not None and formato.exige_metros:
            # **Sin valor por omisión**, igual que el CRS declarado de la ficha: sugerir uno
            # sería adivinar con la firma de otra persona. Lo que sí se puede decir es por
            # qué hace falta, que es lo que la ayuda explica.
            return (
                OpcionDeMotor(
                    "crs_destino",
                    "Reproyectar a (EPSG)",
                    "texto",
                    por_defecto="",
                    ayuda=(
                        "Obligatorio si el origen está en grados: un DXF guarda números sin "
                        "sistema de referencia, y en grados el dibujo mide milésimas de "
                        "unidad. Por ejemplo 32719 para UTM 19 sur."
                    ),
                ),
                *comunes,
            )
        return comunes

    def plan(self, trabajo) -> PlanDeEjecucion:
        origen = Path(trabajo.source_path)
        destino = Path(trabajo.output_path)
        parcial = ruta_parcial(destino)

        opciones = dict(trabajo.options or {})
        controlador = CONTROLADOR.get(trabajo.target_format_code, "GPKG")

        argv: list[str] = [_bin("ogr2ogr"), "-f", controlador, str(parcial), str(origen)]

        declarado = str(opciones.get("crs_destino", "") or "").strip()
        if trabajo.target_crs_code:
            autoridad = trabajo.target_crs_authority or "EPSG"
            argv += ["-t_srs", f"{autoridad}:{trabajo.target_crs_code}"]
        elif declarado:
            # Puede venir como `32719` o como `EPSG:32719`; `-t_srs` acepta las dos, pero se
            # normaliza para que el argv de la bitácora se lea siempre igual.
            argv += ["-t_srs", declarado if ":" in declarado else f"EPSG:{declarado}"]
        elif trabajo.target_format_code in DESTINOS_EN_GRADOS:
            argv += ["-t_srs", "EPSG:4326"]

        if opciones.get("solo_geometria"):
            argv += ["-select", ""]

        argv += ["-overwrite"]

        return PlanDeEjecucion(
            argv=tuple(argv),
            ruta_de_salida=destino,
            env=entorno_de_gdal(),
            timeout_s=1800,
            emite_progreso=False,
        )

    def verificar(self, trabajo, salida: Path) -> Verificacion:
        return _verificar_con_ogrinfo(trabajo, salida, super().verificar(trabajo, salida))


# --- La verificacion ---------------------------------------------------------


def _verificar_con_ogrinfo(trabajo, salida: Path, base: Verificacion) -> Verificacion:
    """Se le pregunta a OGR si la salida sirve.

    Que lo diga OGR y no nosotros: comprobar la salida con el mismo lector que la escribio
    no probaria nada. Y lo que se exige es lo que de verdad se rompe -- **que haya
    entidades**. `ogr2ogr` devuelve 0 y escribe un archivo con cero puntos cuando el
    `X_POSSIBLE_NAMES` no coincidio con ninguna columna: un GPKG de 98 KB perfectamente
    valido y completamente vacio.
    """
    if not base.correcta:
        return base

    info = _ogrinfo(salida)
    if info is None:
        return Verificacion(
            correcta=False,
            motivo="OGR no puede leer el archivo que acaba de escribir.",
            codigo_motivo="salida-invalida",
        )

    capas = info.get("layers", []) or []
    entidades = sum(int(capa.get("featureCount", 0) or 0) for capa in capas)

    detalles = {
        "capas": len(capas),
        "entidades": entidades,
        "controlador": info.get("driverShortName", ""),
        "bytes": salida.stat().st_size,
    }
    epsg = _epsg_de(capas)
    if epsg:
        detalles["epsg"] = epsg
    if capas:
        detalles["geometria"] = capas[0].get("geometryFields", [{}])[0].get("type", "")

    if not entidades:
        return Verificacion(
            correcta=False,
            motivo=(
                "El archivo se escribió pero no tiene ninguna entidad dentro. Suele "
                "significar que el orden de columnas no era el del archivo."
            ),
            codigo_motivo="salida-invalida",
            detalles=detalles,
        )

    return Verificacion(correcta=True, detalles=detalles)


def _ogrinfo(ruta: Path) -> dict | None:
    import json
    import subprocess

    try:
        resultado = subprocess.run(  # nosec B603
            [_bin("ogrinfo"), "-json", "-so", "-al", str(ruta)],
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


def _epsg_de(capas: list[dict]) -> str:
    """El código EPSG que declara la primera capa, si lo declara."""
    import re

    for capa in capas:
        for campo in capa.get("geometryFields", []) or []:
            wkt = (campo.get("coordinateSystem", {}) or {}).get("wkt", "")
            encontrados = re.findall(r'ID\s*\[\s*"EPSG"\s*,\s*(\d+)\s*\]', wkt)
            if encontrados:
                return encontrados[-1]
    return ""


def registrar_todos() -> None:
    registry.registrar(MotorPuntosTopograficos())
    registry.registrar(MotorLandXml())
    registry.registrar(MotorDesdeLandXml())
    registry.registrar(MotorOgrVector())
