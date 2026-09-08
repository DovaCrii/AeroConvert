"""Perfiles de destino: **donde tiene que abrir el archivo**, no a que extension va.

## Por que el selector primario es un programa y no un formato

Porque esa es la pregunta que la gente se hace de verdad. Nadie quiere «un GeoTIFF con
BIGTIFF=NO y tres bandas»: quiere que la ortofoto abra en el PC del proyectista. Todas las
herramientas del mercado -- FME, Global Mapper, MyGeodata -- parten de que ya sabes el
formato de destino. Aqui se invierte: se elige el programa y el perfil elige el formato y
las opciones.

El caso que origino la aplicacion lo ilustra entero: una ortofoto de Metashape que abria en
la maquina de quien la genero y no en la de al lado. El archivo no estaba roto ni le
faltaba georreferencia -- era BigTIFF, y Civil 3D no lee BigTIFF. Ninguna herramienta lo
decia. Este modulo existe para decirlo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.formats import catalogo

#: Severidad de un veredicto. Nunca va solo el color: cada uno lleva icono propio y texto,
#: porque uno de cada doce hombres no distingue el rojo del verde (WCAG 1.4.1).
ABRE = "abre"
CON_REPAROS = "con-reparos"
NO_ABRE = "no-abre"

ICONOS = {
    ABRE: "icon-veredicto-abre",
    CON_REPAROS: "icon-veredicto-reparos",
    NO_ABRE: "icon-veredicto-no",
}
ETIQUETAS = {ABRE: "Abre", CON_REPAROS: "Abre con reparos", NO_ABRE: "No abre"}


@dataclass(frozen=True)
class Veredicto:
    perfil_id: str
    perfil_nombre: str
    severidad: str
    #: Una linea. Si hace falta un parrafo, el veredicto esta mal escrito.
    motivo: str
    #: Que hacer. Vacio cuando ya abre.
    remedio: str = ""

    @property
    def icono(self) -> str:
        return ICONOS[self.severidad]

    @property
    def etiqueta(self) -> str:
        return ETIQUETAS[self.severidad]


@dataclass(frozen=True)
class PerfilDeDestino:
    id: str
    nombre: str
    descripcion: str
    #: Formatos que este programa lee sin problema, en orden de preferencia.
    formatos_preferidos: tuple[str, ...]
    #: Formatos que lee, pero no son la mejor opcion.
    formatos_aceptados: tuple[str, ...] = ()
    #: El formato al que se convierte cuando se elige este perfil.
    formato_destino: str = ""
    #: Las opciones que fija el perfil. Se pueden ver y cambiar en «ajustar a mano».
    opciones: dict = field(default_factory=dict)
    #: Acompanantes que hay que escribir al lado.
    escribir_acompanantes: tuple[str, ...] = ()

    def lee(self, codigo_formato: str) -> bool:
        return (
            codigo_formato in self.formatos_preferidos or codigo_formato in self.formatos_aceptados
        )


# --- Los perfiles ----------------------------------------------------------

CIVIL3D = PerfilDeDestino(
    id="civil3d",
    nombre="Civil 3D / AutoCAD",
    descripcion="Lo que abre en cualquier puesto con Civil 3D, tenga o no Raster Design.",
    # TIFF clasico primero: es lo que abre AutoCAD base, sin complementos.
    formatos_preferidos=("geotiff",),
    formatos_aceptados=("jp2", "ecw", "mrsid", "img", "png", "jpeg"),
    formato_destino="geotiff",
    # **Las claves son las que declara el motor, no las de GDAL.**
    #
    # Escribirlas como `COMPRESS` o `BLOCKXSIZE` parecia natural -- es lo que acaba en el
    # comando -- y estaba mal: el motor lee `compresion` y `tamano_tesela`, asi que el
    # perfil no fijaba nada y el trabajo salia con los valores por omision. El perfil de
    # Civil 3D prometia descartar la banda alfa y **no lo hacia**.
    #
    # Es justo el fallo que la regla de «las opciones las declara el motor» existe para
    # impedir, y hay una prueba que compara ambos vocabularios para que no vuelva.
    opciones={
        # La opcion que resuelve el caso que origino la aplicacion.
        "bigtiff": "NO",
        "compresion": "DEFLATE",
        "tamano_tesela": "512",
        "solo_rgb": True,
        "piramides": "2 4 8 16 32",
    },
)

QGIS = PerfilDeDestino(
    id="qgis",
    nombre="QGIS",
    descripcion="Lee practicamente todo. El destino recomendado es COG.",
    formatos_preferidos=("cog", "geotiff", "bigtiff", "gpkg"),
    formatos_aceptados=(
        "jp2",
        "ecw",
        "mrsid",
        "img",
        "asc",
        "shp",
        "kml",
        "kmz",
        "geojson",
        "las",
        "laz",
        "copc",
    ),
    formato_destino="cog",
    opciones={"compresion": "DEFLATE"},
)

ARCGIS = PerfilDeDestino(
    id="arcgis",
    nombre="ArcGIS Pro",
    descripcion="Lee BigTIFF y la mayoria de los raster; prefiere GeoTIFF o CRF.",
    formatos_preferidos=("geotiff", "bigtiff", "cog", "img", "gpkg"),
    formatos_aceptados=("jp2", "ecw", "mrsid", "asc", "shp", "geojson", "las", "laz"),
    formato_destino="geotiff",
    # ArcGIS si lee BigTIFF, asi que no hay razon para forzar el clasico y arriesgarse a
    # que un raster grande no quepa.
    opciones={"compresion": "LZW", "bigtiff": "IF_SAFER", "piramides": "2 4 8 16 32"},
)

GOOGLE_EARTH = PerfilDeDestino(
    id="google-earth",
    nombre="Google Earth",
    descripcion="Solo KMZ con superposicion teselada, y en EPSG:4326.",
    formatos_preferidos=("kmz",),
    formatos_aceptados=("kml",),
    formato_destino="kmz",
    opciones={"reproyectar_a": "EPSG:4326", "teselar": True},
)

WEB = PerfilDeDestino(
    id="web",
    nombre="Visor web",
    descripcion="COG servido por rangos HTTP: se ve el trozo que se mira, no el archivo.",
    formatos_preferidos=("cog",),
    formatos_aceptados=("mbtiles", "geojson", "copc"),
    formato_destino="cog",
    opciones={"compresion": "DEFLATE"},
)

AEROBIM = PerfilDeDestino(
    id="aerobim",
    nombre="AeroBim",
    descripcion="La aplicacion hermana: COG para raster, COPC para nubes, DXF para planos.",
    formatos_preferidos=("cog", "copc", "dxf", "ifc"),
    formato_destino="cog",
    opciones={"compresion": "DEFLATE"},
)

PERFILES: dict[str, PerfilDeDestino] = {
    p.id: p for p in (CIVIL3D, QGIS, ARCGIS, GOOGLE_EARTH, WEB, AEROBIM)
}


def perfil(identificador: str) -> PerfilDeDestino:
    return PERFILES[identificador]


# --- Los veredictos --------------------------------------------------------
#
# Cada regla vive aqui, con su motivo escrito para una persona. Que sea una lista de
# funciones y no un `if` gigante es a proposito: agregar «Bentley MicroStation» tiene que
# ser agregar una regla, no editar un arbol.


def _veredicto_civil3d(inspeccion) -> Veredicto:
    tiff = inspeccion.tiff
    codigo = inspeccion.codigo_formato

    if codigo == "bigtiff":
        return Veredicto(
            perfil_id=CIVIL3D.id,
            perfil_nombre=CIVIL3D.nombre,
            severidad=NO_ABRE,
            motivo="Es BigTIFF, y Civil 3D no lee BigTIFF aunque la extensión sea .tif.",
            remedio="Reescribir como TIFF clásico. No pierde un solo píxel.",
        )

    if not CIVIL3D.lee(codigo):
        formato = catalogo.FORMATOS.get(codigo)
        nombre = formato.nombre if formato else codigo or "desconocido"
        return Veredicto(
            perfil_id=CIVIL3D.id,
            perfil_nombre=CIVIL3D.nombre,
            severidad=NO_ABRE,
            motivo=f"Civil 3D no abre {nombre}.",
            remedio="Convertir a GeoTIFF clásico.",
        )

    if tiff is not None and tiff.tiene_alfa:
        return Veredicto(
            perfil_id=CIVIL3D.id,
            perfil_nombre=CIVIL3D.nombre,
            severidad=CON_REPAROS,
            motivo="Trae banda alfa: AutoCAD suele pintarla como una banda gris o dejar negro.",
            remedio="Escribir tres bandas y pasar el alfa a mascara.",
        )

    if codigo in ("jp2", "ecw", "mrsid"):
        return Veredicto(
            perfil_id=CIVIL3D.id,
            perfil_nombre=CIVIL3D.nombre,
            severidad=CON_REPAROS,
            motivo="Necesita Raster Design o Map 3D; AutoCAD base no lo lee.",
            remedio="Si el puesto no lo tiene, convertir a GeoTIFF clásico.",
        )

    if not inspeccion.crs.conocido:
        return Veredicto(
            perfil_id=CIVIL3D.id,
            perfil_nombre=CIVIL3D.nombre,
            severidad=CON_REPAROS,
            motivo="Abre, pero sin sistema de referencia: entrara en el origen del dibujo.",
            remedio="Declarar el EPSG y escribir el .prj al lado.",
        )

    return Veredicto(CIVIL3D.id, CIVIL3D.nombre, ABRE, "Abre tal cual.")


def _veredicto_generico(perfil_destino: PerfilDeDestino, inspeccion) -> Veredicto:
    codigo = inspeccion.codigo_formato

    if not perfil_destino.lee(codigo):
        formato = catalogo.FORMATOS.get(codigo)
        nombre = formato.nombre if formato else codigo or "desconocido"
        destino = catalogo.FORMATOS.get(perfil_destino.formato_destino)
        return Veredicto(
            perfil_id=perfil_destino.id,
            perfil_nombre=perfil_destino.nombre,
            severidad=NO_ABRE,
            motivo=f"{perfil_destino.nombre} no abre {nombre}.",
            remedio=f"Convertir a {destino.nombre}." if destino else "",
        )

    if not inspeccion.crs.conocido and codigo not in ("kml", "kmz"):
        return Veredicto(
            perfil_id=perfil_destino.id,
            perfil_nombre=perfil_destino.nombre,
            severidad=CON_REPAROS,
            motivo="Abre, pero no declara sistema de referencia.",
            remedio="Declarar el EPSG antes de convertir.",
        )

    if codigo not in perfil_destino.formatos_preferidos:
        destino = catalogo.FORMATOS.get(perfil_destino.formato_destino)
        return Veredicto(
            perfil_id=perfil_destino.id,
            perfil_nombre=perfil_destino.nombre,
            severidad=CON_REPAROS,
            motivo="Abre, pero no es el formato que mejor le sienta.",
            remedio=f"Convertir a {destino.nombre}." if destino else "",
        )

    return Veredicto(perfil_destino.id, perfil_destino.nombre, ABRE, "Abre tal cual.")


def _veredicto_web(inspeccion) -> Veredicto:
    codigo = inspeccion.codigo_formato
    tiff = inspeccion.tiff

    if codigo == "cog":
        return Veredicto(WEB.id, WEB.nombre, ABRE, "Es COG: se sirve por rangos HTTP.")

    if tiff is not None:
        faltas = []
        if not tiff.teselado:
            faltas.append("no esta teselado")
        if not tiff.tiene_piramides_internas:
            faltas.append("no trae piramides que GDAL reconozca")
        detalle = " y ".join(faltas) if faltas else "el orden interno no es el de un COG"
        return Veredicto(
            perfil_id=WEB.id,
            perfil_nombre=WEB.nombre,
            severidad=CON_REPAROS,
            motivo=f"Se puede servir, pero {detalle}: el navegador se lo descarga entero.",
            remedio="Convertir a COG.",
        )

    return _veredicto_generico(WEB, inspeccion)


#: Las reglas propias. Lo que no esta aqui usa `_veredicto_generico`.
REGLAS = {CIVIL3D.id: _veredicto_civil3d, WEB.id: _veredicto_web}


def veredictos(inspeccion) -> tuple[Veredicto, ...]:
    """La tira de veredictos: un juicio por destino, cada uno con su motivo en una linea.

    Es lo primero que ve la persona despues de la ficha del archivo, y es lo que ninguna
    otra herramienta da.
    """
    salida = []
    for identificador, perfil_destino in PERFILES.items():
        regla = REGLAS.get(identificador)
        salida.append(
            regla(inspeccion) if regla else _veredicto_generico(perfil_destino, inspeccion)
        )
    return tuple(salida)
