"""Que hay dentro de este archivo, y cuanto nos fiamos de la respuesta.

Tres pasos, del mas barato al mas caro, y cada uno solo **confirma o contradice** al
anterior:

1. **Por firma.** 64 KiB y unos microsegundos. Es lo unico que distingue un BigTIFF de un
   TIFF clasico, que comparten extension y son formatos distintos para quien los abre.
2. **Por extension.** Solo cuando la firma calla: ASC, XYZ y DEM son texto plano y no
   tienen firma. La confianza baja a `extension`, y eso se muestra.
3. **Por GDAL.** Autoritativo, y **opcional**: si no esta instalado, la confianza baja;
   nunca hace fallar la inspeccion.

**Una discrepancia entre firma y extension no es un error.** Un `.tif` que por dentro es un
JP2 renombrado existe, pasa, y lo unico razonable es creerle a la firma y decirlo en la
ficha.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import catalogo, tiff
from . import crs as crs_mod
from . import las as las_mod
from . import puntos as puntos_mod

#: Cuanto se lee para reconocer la firma.
BYTES_DE_FIRMA = 65_536

CONFIANZA_FIRMA = "firma"
CONFIANZA_GDAL = "gdal"
CONFIANZA_EXTENSION = "extensión"
CONFIANZA_DESCONOCIDA = "desconocido"

ETIQUETAS_CONFIANZA = {
    CONFIANZA_FIRMA: "reconocido por su contenido",
    CONFIANZA_GDAL: "reconocido por GDAL",
    CONFIANZA_EXTENSION: "supuesto por la extensión",
    CONFIANZA_DESCONOCIDA: "no reconocido",
}


class OrigenIlegible(Exception):
    def __init__(self, mensaje: str, codigo: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


@dataclass(frozen=True)
class Acompanante:
    ruta: Path
    extension: str
    presente: bool
    #: `True` si su ausencia pierde informacion, no solo comodidad.
    imprescindible: bool


@dataclass(frozen=True)
class Inspeccion:
    """Todo lo que se sabe del archivo sin abrir la imagen."""

    ruta: Path
    nombre: str
    bytes_totales: int
    codigo_formato: str
    confianza: str
    crs: crs_mod.Crs
    acompanantes: tuple[Acompanante, ...] = ()
    #: Presente solo cuando el archivo es un TIFF o BigTIFF.
    tiff: tiff.CabeceraTiff | None = None
    #: Presente solo cuando el archivo es un LAS, LAZ o COPC.
    las: las_mod.CabeceraLas | None = None
    #: Presente solo cuando el archivo es una libreta de puntos (PNEZD y compañía).
    puntos: puntos_mod.CabeceraPuntos | None = None
    avisos: tuple[str, ...] = ()
    detalles: dict = field(default_factory=dict)

    @property
    def formato(self) -> catalogo.Formato | None:
        return catalogo.FORMATOS.get(self.codigo_formato)

    @property
    def familia(self) -> str:
        formato = self.formato
        return formato.familia if formato else ""

    @property
    def reconocido(self) -> bool:
        return self.confianza != CONFIANZA_DESCONOCIDA

    @property
    def etiqueta_confianza(self) -> str:
        return ETIQUETAS_CONFIANZA[self.confianza]

    @property
    def faltan_imprescindibles(self) -> tuple[Acompanante, ...]:
        return tuple(a for a in self.acompanantes if a.imprescindible and not a.presente)


def por_firma(cabecera: bytes) -> str | None:
    """El codigo de formato que dice la firma, o `None`.

    El orden importa: BigTIFF y TIFF clasico se diferencian en un solo byte, asi que se
    comparan las firmas completas y no un prefijo.
    """
    for codigo in ("bigtiff", "geotiff"):
        for firma in catalogo.FORMATOS[codigo].firmas:
            if cabecera.startswith(firma):
                return codigo

    for formato in catalogo.FORMATOS.values():
        if formato.codigo in ("bigtiff", "geotiff", "cog"):
            continue
        for firma in formato.firmas:
            if cabecera.startswith(firma):
                return formato.codigo
    return None


def por_extension(nombre: str) -> str | None:
    """El formato mas probable segun la extension, cuando la firma no dice nada.

    Cuando varios formatos comparten extension se prefiere el de lectura mas comun. Es una
    suposicion, y por eso la confianza que la acompana es `extension`.
    """
    sufijo = Path(nombre).suffix.lower()
    candidatos = catalogo.por_extension(sufijo)
    if not candidatos:
        return None
    legibles = [f for f in candidatos if f.admite_lectura]
    return (legibles or list(candidatos))[0].codigo


def archivos_acompanantes(ruta: Path, codigo_formato: str) -> tuple[Acompanante, ...]:
    """Los archivos que viajan al lado, y si estan.

    Importa mas de lo que parece: en modo nube hay que subirlos juntos, y **un `.tif` sin
    su `.prj` es un `.tif` sin georreferencia**. El sintoma es que la salida sale bien pero
    esta en el sitio equivocado, que es el peor sintoma que existe.
    """
    formato = catalogo.FORMATOS.get(codigo_formato)
    if formato is None or not formato.acompanantes:
        return ()

    # Un `.prj` solo es imprescindible si el formato no lleva el CRS dentro.
    imprescindibles = set()
    if not formato.lleva_crs_incrustado:
        imprescindibles.update({".prj", ".tfw", ".jgw", ".pgw", ".j2w", ".wld"})
    if codigo_formato == "shp":
        imprescindibles.update({".shx", ".dbf", ".prj"})

    base = ruta.with_suffix("")
    encontrados = []
    for extension in sorted(formato.acompanantes):
        # `.aux.xml` cuelga del nombre completo, no del tronco: `x.tif.aux.xml`.
        candidata = (
            ruta.with_name(ruta.name + extension)
            if extension.startswith(".aux")
            else base.with_suffix(extension)
        )
        encontrados.append(
            Acompanante(
                ruta=candidata,
                extension=extension,
                presente=candidata.exists(),
                imprescindible=extension in imprescindibles,
            )
        )
    return tuple(encontrados)


def _crs_de_prj(ruta: Path) -> crs_mod.Crs:
    prj = ruta.with_suffix(".prj")
    if not prj.exists():
        return crs_mod.SIN_CRS
    try:
        return crs_mod.desde_wkt(prj.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return crs_mod.SIN_CRS


def inspeccionar(ruta: str | Path) -> Inspeccion:
    """Lee la cabecera y devuelve lo que se sabe. **No abre la imagen.**

    Levanta `OrigenIlegible` con motivo de codigo estable cuando ni siquiera se puede
    mirar: no existe, no hay permiso, es una carpeta, o es un marcador de OneDrive.
    """
    ruta = Path(ruta)

    if not ruta.exists():
        raise OrigenIlegible(f"No hay ningún archivo en {ruta}.", "origen-no-legible")
    if ruta.is_dir():
        raise OrigenIlegible(f"{ruta} es una carpeta, no un archivo.", "origen-no-legible")

    try:
        tamano = ruta.stat().st_size
    except OSError as fallo:
        raise OrigenIlegible(f"No se pudo leer {ruta}: {fallo}", "origen-no-legible") from fallo

    if _es_marcador_en_la_nube(ruta):
        raise OrigenIlegible(
            f"{ruta.name} figura en la carpeta pero su contenido no esta descargado "
            "(OneDrive con Archivos a Peticion). Abrelo una vez en el Explorador, o marca "
            "«Conservar siempre en este dispositivo», y vuelve a intentarlo.",
            "solo-marcador-en-la-nube",
        )

    if tamano == 0:
        raise OrigenIlegible(f"{ruta.name} tiene 0 bytes.", "origen-no-legible")

    try:
        with open(ruta, "rb") as archivo:
            cabecera = archivo.read(BYTES_DE_FIRMA)
    except PermissionError as fallo:
        raise OrigenIlegible(
            f"{ruta.name} esta abierto en otro programa o no hay permiso de lectura.",
            "origen-bloqueado",
        ) from fallo
    except OSError as fallo:
        raise OrigenIlegible(
            f"No se pudo leer {ruta.name}: {fallo}", "origen-no-legible"
        ) from fallo

    avisos: list[str] = []
    codigo = por_firma(cabecera)
    confianza = CONFIANZA_FIRMA

    if codigo is None:
        codigo = por_extension(ruta.name)
        confianza = CONFIANZA_EXTENSION if codigo else CONFIANZA_DESCONOCIDA
    else:
        supuesto = por_extension(ruta.name)
        formato_firma = catalogo.FORMATOS[codigo]
        if supuesto and supuesto != codigo:
            supuesta = catalogo.FORMATOS[supuesto]
            # Compartir extension no es discrepancia: `.tif` es geotiff y bigtiff a la vez.
            if not (formato_firma.extensiones & supuesta.extensiones):
                avisos.append(
                    f"La extensión dice {supuesta.nombre} pero el contenido es "
                    f"{formato_firma.nombre}. Gana el contenido."
                )

    cabecera_tiff = None
    crs = crs_mod.SIN_CRS
    detalles: dict = {}

    if codigo in ("geotiff", "bigtiff", "cog"):
        try:
            cabecera_tiff = tiff.leer_cabecera(ruta)
        except (tiff.NoEsTiff, OSError, ValueError) as fallo:
            avisos.append(f"Empieza como un TIFF pero la cabecera no se pudo leer: {fallo}")
        else:
            codigo = "bigtiff" if cabecera_tiff.es_bigtiff else "geotiff"
            if cabecera_tiff.epsg:
                crs = crs_mod.epsg(cabecera_tiff.epsg, origen=crs_mod.INCRUSTADO)
            if cabecera_tiff.es_bigtiff and not cabecera_tiff.necesitaba_bigtiff:
                # La coma decimal, no el punto: el resto de la ficha dice «466,2 MB» y
                # «2,56 cm/px», y mezclar las dos convenciones en la misma tarjeta se nota.
                gigas = f"{cabecera_tiff.bytes_sin_comprimir / 1e9:.2f}".replace(".", ",")
                avisos.append(
                    f"Es BigTIFF sin necesitarlo: sin comprimir ocupa {gigas} GB, muy por "
                    "debajo del techo de 4 GB del TIFF clásico. Reescribirlo como clásico "
                    "no pierde nada y lo abre mucho más software."
                )
            if cabecera_tiff.tiene_alfa:
                avisos.append(
                    "Trae una banda alfa. Varios CAD la pintan como una banda gris más o "
                    "dejan negro donde debería ser transparente."
                )

    cabecera_las = None
    if codigo in ("las", "laz", "copc"):
        try:
            cabecera_las = las_mod.leer_cabecera(ruta)
        # `struct.error` se cuela con un archivo truncado en el sitio justo.
        except (las_mod.NoEsLas, OSError, ValueError, struct.error) as fallo:
            avisos.append(f"Empieza como un LAS pero la cabecera no se pudo leer: {fallo}")
        else:
            # **La firma no distingue las tres cosas: las tres empiezan por `LASF`.** Un LAZ
            # es un LAS con los datos comprimidos, y un COPC es un LAZ con un octree dentro.
            # Solo la cabecera lo dice, y para AeroBim la diferencia es entre poder abrir la
            # nube y no poder.
            if cabecera_las.es_copc:
                codigo = "copc"
            elif cabecera_las.comprimido:
                codigo = "laz"
            else:
                codigo = "las"

            if cabecera_las.epsg:
                crs = crs_mod.epsg(cabecera_las.epsg, origen=crs_mod.INCRUSTADO)
            elif cabecera_las.wkt:
                crs = crs_mod.desde_wkt(cabecera_las.wkt, origen=crs_mod.INCRUSTADO)

            if not cabecera_las.precision_suficiente_para_float32:
                avisos.append(
                    "Las coordenadas son demasiado grandes para float32: pasarlas a "
                    "precisión simple sin restar el desplazamiento de cabecera mueve los "
                    "puntos unos 20 cm. Cualquier visor que lo haga mal se notará."
                )

    cabecera_puntos = None
    if codigo == "puntos":
        try:
            cabecera_puntos = puntos_mod.leer(ruta)
        except (puntos_mod.NoEsArchivoDePuntos, OSError, ValueError) as fallo:
            # Un `.csv` que no es una libreta de puntos es un `.csv` cualquiera, y decirlo
            # es mejor que dejar la ficha en blanco: la extensión no promete nada.
            codigo = ""
            confianza = CONFIANZA_DESCONOCIDA
            avisos.append(f"Tiene extensión de libreta de puntos pero no lo es: {fallo}")
        else:
            avisos.extend(_avisos_de_puntos(cabecera_puntos))

    if not crs.conocido:
        crs = _crs_de_prj(ruta)

    if not crs.conocido:
        # Lo que impone el formato. Un KML **solo** existe en EPSG:4326, así que decirlo no
        # es adivinar: es leer la norma. Va el último para que no pise nada de lo que traiga
        # el archivo, aunque en estos formatos no puede haber otra cosa.
        formato = catalogo.FORMATOS.get(codigo or "")
        if formato is not None and formato.crs_fijo:
            crs = crs_mod.epsg(int(formato.crs_fijo), origen=crs_mod.POR_NORMA)

    return Inspeccion(
        ruta=ruta,
        nombre=ruta.name,
        bytes_totales=tamano,
        codigo_formato=codigo or "",
        confianza=confianza,
        crs=crs,
        acompanantes=archivos_acompanantes(ruta, codigo or ""),
        tiff=cabecera_tiff,
        las=cabecera_las,
        puntos=cabecera_puntos,
        avisos=tuple(avisos),
        detalles=detalles,
    )


def _avisos_de_puntos(cabecera: puntos_mod.CabeceraPuntos) -> list[str]:
    """Lo que hay que decir de una libreta de puntos, y en qué tono.

    El aviso importante es el del orden ambiguo, y se escribe con la consecuencia y no con
    el diagnóstico: «hay que elegir el orden» no mueve a nadie, «si se elige mal los puntos
    caen a 9.650 km» sí. La cifra sale del propio archivo.
    """
    avisos: list[str] = []

    if cabecera.hay_que_preguntar:
        kilometros = f"{cabecera.distancia_si_se_invierte_m / 1000:.0f}".replace(",", ".")
        avisos.append(
            f"No se puede deducir si el archivo es {cabecera.orden.upper()} o "
            f"{cabecera.orden_alternativo.upper()}: las dos columnas de coordenadas caben "
            "como este UTM. Hay que elegirlo a mano, y elegir mal no da ningún error: "
            f"deja los puntos a unos {kilometros} km de donde van."
        )
    else:
        avisos.append(
            f"Orden de columnas {cabecera.orden.upper()}, "
            f"{cabecera.etiqueta_certeza}. Compruébalo en la vista previa antes de "
            "convertir."
        )

    if cabecera.lineas_ignoradas:
        avisos.append(
            f"{cabecera.lineas_ignoradas} línea(s) no se pudieron interpretar y se van a "
            "quedar fuera."
        )

    return avisos


#: Atributo de Windows para un archivo cuyo contenido vive en la nube y no en el disco.
#: OneDrive con Archivos a Peticion lo pone, y el archivo *parece* estar ahi. Es la causa
#: mas confundible de "en mi PC abre y en el suyo no", asi que tiene motivo propio en vez
#: de acabar como `formato-no-reconocido`.
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
FILE_ATTRIBUTE_OFFLINE = 0x00001000


def _es_marcador_en_la_nube(ruta: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        atributos = ruta.stat().st_file_attributes  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False
    return bool(atributos & (FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | FILE_ATTRIBUTE_OFFLINE))


def huella(ruta: Path, *, trozo: int = 1_048_576, progreso=None) -> str:
    """`sha256` del archivo, por trozos.

    Por trozos y no de golpe porque estos archivos son de gigabytes y `read()` entero
    tumbaria el proceso. `progreso` recibe la fraccion completada: en un archivo grande la
    huella tarda minutos y **tiene que verse**, o parece que la aplicacion se colgo.
    """
    total = ruta.stat().st_size or 1
    leidos = 0
    digestor = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        while True:
            datos = archivo.read(trozo)
            if not datos:
                break
            digestor.update(datos)
            leidos += len(datos)
            if progreso is not None:
                progreso(leidos / total)
    return digestor.hexdigest()
