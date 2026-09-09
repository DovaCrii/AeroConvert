"""El catalogo de formatos.

**Es codigo, no una tabla.** Agregar un formato es cambiar codigo y sus pruebas, no una
fila que alguien edita en el admin. Una tabla obligaria a una migracion por formato y a
mantener sincronizados el registro de motores (codigo) con el catalogo (base de datos):
dos fuentes de verdad que se desincronizan sin que nadie se entere.

Dos decisiones que conviene entender antes de tocar esto:

1. **BigTIFF es una entrada propia, no una bandera de GeoTIFF.** Comparten extension y son
   formatos distintos: Civil 3D lee uno y no el otro. Tenerlos separados hace que la matriz
   de capacidades y la tira de veredictos puedan decirlo; tenerlos juntos lo esconderia.
2. **`con_perdida` decide como se escribe la asercion del oraculo.** Un destino sin perdida
   se afirma con igualdad de estadisticas; uno con perdida, con georreferencia exacta y un
   piso de PSNR. La eleccion sale del dato, no de la memoria de quien escribe la prueba.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.utils.translation import gettext_lazy as _

RASTER = "raster"
NUBE = "nube"
VECTOR = "vector"
MALLA = "malla"

FAMILIAS = {
    RASTER: "Raster geoespacial",
    NUBE: "Nube de puntos",
    VECTOR: "Vectorial, CAD y topografia",
    MALLA: "BIM y malla 3D",
}


@dataclass(frozen=True)
class Formato:
    codigo: str
    familia: str
    #: **Solo se traduce la parte descriptiva.**
    #:
    #: `GeoTIFF`, `Shapefile`, `LandXML` o `MrSID` son nombres propios y se dejan como
    #: estan: traducirlos haria que alguien buscara en Google algo que no existe. Lo que se
    #: traduce es lo que describe -- `GeoTIFF (classic)` a `GeoTIFF clasico`, `Survey point
    #: file` a `Libreta de puntos` -- y va en ingles porque es el msgid de gettext; el
    #: espanol vive en `locale/es/LC_MESSAGES/django.po`.
    #:
    #: El tipo es `str` y no `StrPromise` porque las dos formas conviven en el catalogo y
    #: una cadena perezosa se comporta como `str` en todo lo que hace falta aqui: se formatea,
    #: se compara y DRF la serializa.
    nombre: str
    extensiones: frozenset[str]
    #: Firmas de los primeros bytes. Vacio = el formato no tiene firma (texto plano).
    firmas: tuple[bytes, ...] = ()
    lleva_crs_incrustado: bool = True
    admite_lectura: bool = True
    admite_escritura: bool = True
    con_perdida: bool = False
    #: Extensiones que viajan al lado y sin las cuales se pierde informacion.
    acompanantes: frozenset[str] = field(default_factory=frozenset)
    nota: str = ""


def _f(**kwargs) -> Formato:
    return Formato(**kwargs)


#: El catalogo. La clave es el codigo, que es lo que guardan los trabajos y lo que usa el
#: registro de motores para declarar pares.
FORMATOS: dict[str, Formato] = {
    # --- Raster ------------------------------------------------------------
    "geotiff": _f(
        codigo="geotiff",
        familia=RASTER,
        nombre=_("GeoTIFF (classic)"),
        extensiones=frozenset({".tif", ".tiff"}),
        firmas=(b"II*\x00", b"MM\x00*"),
        acompanantes=frozenset({".tfw", ".prj", ".aux.xml", ".ovr", ".msk"}),
        nota="TIFF clasico. Es el que abre en cualquier parte, incluido Civil 3D.",
    ),
    "bigtiff": _f(
        codigo="bigtiff",
        familia=RASTER,
        nombre="BigTIFF",
        extensiones=frozenset({".tif", ".tiff"}),
        firmas=(b"II+\x00", b"MM\x00+"),
        acompanantes=frozenset({".tfw", ".prj", ".aux.xml", ".ovr", ".msk"}),
        nota=(
            "Variante del TIFF para pasar el techo de 4 GB. Misma extension, formato "
            "distinto: AutoCAD y Civil 3D NO lo leen."
        ),
    ),
    "cog": _f(
        codigo="cog",
        familia=RASTER,
        nombre="Cloud Optimized GeoTIFF",
        extensiones=frozenset({".tif", ".tiff"}),
        firmas=(b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"),
        acompanantes=frozenset({".prj"}),
        nota="Un GeoTIFF teselado y con piramides, ordenado para leerse por rangos HTTP.",
    ),
    "jp2": _f(
        codigo="jp2",
        familia=RASTER,
        nombre="JPEG 2000",
        extensiones=frozenset({".jp2", ".j2k"}),
        firmas=(b"\x00\x00\x00\x0cjP  ", b"\xff\x4f\xff\x51"),
        con_perdida=True,
        acompanantes=frozenset({".j2w", ".prj", ".aux.xml"}),
        nota=(
            "El sustituto libre de ECW: abierto, GDAL lo escribe sin licencia y Civil 3D "
            "con Raster Design lo lee."
        ),
    ),
    "ecw": _f(
        codigo="ecw",
        familia=RASTER,
        nombre="ECW",
        extensiones=frozenset({".ecw"}),
        firmas=(b"e\x01\x00\x00",),
        con_perdida=True,
        acompanantes=frozenset({".prj", ".aux.xml"}),
        nota=(
            "Propietario de Hexagon. Se lee con el controlador; escribirlo exige una clave "
            "OEM de pago."
        ),
    ),
    "mrsid": _f(
        codigo="mrsid",
        familia=RASTER,
        nombre="MrSID",
        extensiones=frozenset({".sid"}),
        firmas=(b"msid",),
        admite_escritura=False,
        con_perdida=True,
        nota="Solo lectura. Escribirlo exige el SDK de Extensis y no se contempla.",
    ),
    "img": _f(
        codigo="img",
        familia=RASTER,
        nombre="ERDAS IMAGINE",
        extensiones=frozenset({".img"}),
        firmas=(b"EHFA_HEADER_TAG",),
        acompanantes=frozenset({".rrd", ".aux.xml"}),
    ),
    "asc": _f(
        codigo="asc",
        familia=RASTER,
        nombre="Arc/Info ASCII Grid",
        extensiones=frozenset({".asc", ".grd"}),
        # Texto plano: no tiene firma. Se reconoce por extension y por cabecera.
        lleva_crs_incrustado=False,
        acompanantes=frozenset({".prj"}),
    ),
    "dem": _f(
        codigo="dem",
        familia=RASTER,
        nombre="USGS DEM",
        extensiones=frozenset({".dem"}),
        admite_escritura=False,
        lleva_crs_incrustado=False,
    ),
    "png": _f(
        codigo="png",
        familia=RASTER,
        nombre=_("PNG with world file"),
        extensiones=frozenset({".png"}),
        firmas=(b"\x89PNG\r\n\x1a\n",),
        lleva_crs_incrustado=False,
        acompanantes=frozenset({".pgw", ".wld", ".prj", ".aux.xml"}),
    ),
    "jpeg": _f(
        codigo="jpeg",
        familia=RASTER,
        nombre=_("JPEG with world file"),
        extensiones=frozenset({".jpg", ".jpeg"}),
        firmas=(b"\xff\xd8\xff",),
        lleva_crs_incrustado=False,
        con_perdida=True,
        acompanantes=frozenset({".jgw", ".wld", ".prj", ".aux.xml"}),
    ),
    "webp": _f(
        codigo="webp",
        familia=RASTER,
        nombre="WebP",
        extensiones=frozenset({".webp"}),
        firmas=(b"RIFF",),
        lleva_crs_incrustado=False,
        con_perdida=True,
        acompanantes=frozenset({".wld", ".prj"}),
    ),
    "gpkg_raster": _f(
        codigo="gpkg_raster",
        familia=RASTER,
        nombre=_("GeoPackage raster"),
        extensiones=frozenset({".gpkg"}),
        firmas=(b"SQLite format 3\x00",),
    ),
    "mbtiles": _f(
        codigo="mbtiles",
        familia=RASTER,
        nombre="MBTiles",
        extensiones=frozenset({".mbtiles"}),
        firmas=(b"SQLite format 3\x00",),
        con_perdida=True,
    ),
    "vrt": _f(
        codigo="vrt",
        familia=RASTER,
        nombre=_("GDAL Virtual Raster"),
        extensiones=frozenset({".vrt"}),
        nota="Mosaico virtual: apunta a otros archivos sin copiar un solo pixel.",
    ),
    # --- Nubes de puntos ---------------------------------------------------
    "las": _f(
        codigo="las",
        familia=NUBE,
        nombre=_("LAS point cloud"),
        extensiones=frozenset({".las"}),
        firmas=(b"LASF",),
    ),
    "laz": _f(
        codigo="laz",
        familia=NUBE,
        nombre=_("LAZ compressed point cloud"),
        extensiones=frozenset({".laz"}),
        firmas=(b"LASF",),
    ),
    "copc": _f(
        codigo="copc",
        familia=NUBE,
        nombre="Cloud Optimized Point Cloud",
        extensiones=frozenset({".laz"}),
        firmas=(b"LASF",),
        nota="Un LAZ 1.4 valido con un octree dentro. Es lo que lee AeroBim.",
    ),
    "e57": _f(
        codigo="e57",
        familia=NUBE,
        nombre=_("E57 point cloud"),
        extensiones=frozenset({".e57"}),
        firmas=(b"ASTM-E57",),
        nota=(
            "El puente estandar cuando el dato viene de un escaner o de ReCap. **Este PDAL "
            "no lo trae**: la sonda lo dice y la celda queda apagada."
        ),
    ),
    "ply": _f(
        codigo="ply",
        familia=NUBE,
        nombre=_("PLY point cloud"),
        extensiones=frozenset({".ply"}),
        firmas=(b"ply\n", b"ply\r\n"),
        lleva_crs_incrustado=False,
    ),
    # ReCap de Autodesk. **Ni se lee ni se escribe, y no es una carencia pendiente.**
    #
    # `.rcs` es un escaneo indexado y `.rcp` el proyecto que apunta a varios. Los dos son
    # binarios cerrados de Autodesk: no hay lector abierto, PDAL no los conoce, GDAL tampoco,
    # y CloudCompare tampoco. El unico programa que los exporta es ReCap Pro.
    #
    # Estan en el catalogo **a proposito**: quien suelte un `.rcs` merece leer «esto sale de
    # ReCap, exportalo a E57 o LAS» en vez de «formato no reconocido», que suena a fallo de
    # la aplicacion cuando es una decision de Autodesk.
    "rcs": _f(
        codigo="rcs",
        familia=NUBE,
        nombre=_("Autodesk ReCap scan"),
        extensiones=frozenset({".rcs"}),
        admite_lectura=False,
        admite_escritura=False,
        lleva_crs_incrustado=False,
        nota=(
            "Formato cerrado de Autodesk. Solo ReCap Pro lo exporta: usa Exportar → E57 "
            "(o LAS) y convierte ese archivo."
        ),
    ),
    "rcp": _f(
        codigo="rcp",
        familia=NUBE,
        nombre=_("Autodesk ReCap project"),
        extensiones=frozenset({".rcp"}),
        admite_lectura=False,
        admite_escritura=False,
        lleva_crs_incrustado=False,
        nota=(
            "Es el proyecto, no los puntos: apunta a varios .rcs. Solo ReCap Pro lo abre. "
            "Exporta a E57 o LAS desde ahi."
        ),
    ),
    "xyz_nube": _f(
        codigo="xyz_nube",
        familia=NUBE,
        nombre=_("XYZ text point cloud"),
        extensiones=frozenset({".xyz", ".pts", ".txt"}),
        lleva_crs_incrustado=False,
    ),
    # --- Vectorial, CAD y topografia ---------------------------------------
    "shp": _f(
        codigo="shp",
        familia=VECTOR,
        nombre="Shapefile",
        extensiones=frozenset({".shp"}),
        firmas=(b"\x00\x00'\n",),
        lleva_crs_incrustado=False,
        acompanantes=frozenset({".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx"}),
        nota="El .prj y el .dbf no son opcionales: sin ellos no hay CRS ni atributos.",
    ),
    "gpkg": _f(
        codigo="gpkg",
        familia=VECTOR,
        nombre="GeoPackage",
        extensiones=frozenset({".gpkg"}),
        firmas=(b"SQLite format 3\x00",),
        nota="Un solo archivo, con CRS y atributos dentro. El destino recomendado.",
    ),
    "geojson": _f(
        codigo="geojson",
        familia=VECTOR,
        nombre="GeoJSON",
        extensiones=frozenset({".geojson", ".json"}),
        nota="Por norma va en EPSG:4326. Cualquier otra cosa hay que declararla aparte.",
    ),
    "kml": _f(
        codigo="kml",
        familia=VECTOR,
        nombre="KML",
        extensiones=frozenset({".kml"}),
        nota="Siempre EPSG:4326, longitud antes que latitud.",
    ),
    "kmz": _f(
        codigo="kmz",
        familia=VECTOR,
        nombre="KMZ",
        extensiones=frozenset({".kmz"}),
        firmas=(b"PK\x03\x04",),
    ),
    "gml": _f(
        codigo="gml",
        familia=VECTOR,
        nombre="GML",
        extensiones=frozenset({".gml"}),
    ),
    "gpx": _f(
        codigo="gpx",
        familia=VECTOR,
        nombre="GPX",
        extensiones=frozenset({".gpx"}),
    ),
    "dxf": _f(
        codigo="dxf",
        familia=VECTOR,
        nombre="DXF",
        extensiones=frozenset({".dxf"}),
        lleva_crs_incrustado=False,
    ),
    "dwg": _f(
        codigo="dwg",
        familia=VECTOR,
        nombre="DWG",
        extensiones=frozenset({".dwg"}),
        firmas=(b"AC10",),
        admite_escritura=False,
        lleva_crs_incrustado=False,
        nota=(
            "Cerrado. Se lee convirtiendo a DXF con ODA File Converter; LibreDWG es GPL-3 "
            "y contagiaria la licencia del proyecto entero."
        ),
    ),
    "dgn": _f(
        codigo="dgn",
        familia=VECTOR,
        nombre="DGN",
        extensiones=frozenset({".dgn"}),
        admite_escritura=False,
        lleva_crs_incrustado=False,
        nota="v7 lo lee GDAL; v8 necesita ODA, igual que DWG.",
    ),
    "puntos": _f(
        codigo="puntos",
        familia=VECTOR,
        nombre=_("Survey point file (PNEZD/PENZD)"),
        extensiones=frozenset({".csv", ".txt", ".pnt"}),
        lleva_crs_incrustado=False,
        acompanantes=frozenset({".prj"}),
        nota=(
            "El formato de puntos de Civil 3D. El orden de columnas NO se adivina: PNEZD "
            "leido como PENZD deja el punto a millones de metros, y en silencio."
        ),
    ),
    "landxml": _f(
        codigo="landxml",
        familia=VECTOR,
        nombre="LandXML",
        extensiones=frozenset({".xml"}),
        nota="Superficies y alineamientos. La entrada natural a Civil 3D.",
    ),
    # --- BIM y malla -------------------------------------------------------
    "ifc": _f(
        codigo="ifc",
        familia=MALLA,
        nombre="IFC",
        extensiones=frozenset({".ifc"}),
        firmas=(b"ISO-10303-21",),
        admite_escritura=False,
    ),
    "obj": _f(
        codigo="obj",
        familia=MALLA,
        nombre="Wavefront OBJ",
        extensiones=frozenset({".obj"}),
        lleva_crs_incrustado=False,
        acompanantes=frozenset({".mtl"}),
    ),
    "gltf": _f(
        codigo="gltf",
        familia=MALLA,
        nombre="glTF / GLB",
        extensiones=frozenset({".gltf", ".glb"}),
        firmas=(b"glTF",),
        lleva_crs_incrustado=False,
    ),
    "tiles3d": _f(
        codigo="tiles3d",
        familia=MALLA,
        nombre="3D Tiles",
        extensiones=frozenset({".json"}),
        admite_lectura=False,
    ),
}


def formato(codigo: str) -> Formato:
    return FORMATOS[codigo]


def de_familia(familia: str) -> tuple[Formato, ...]:
    return tuple(f for f in FORMATOS.values() if f.familia == familia)


def escribibles(familia: str | None = None) -> tuple[Formato, ...]:
    return tuple(
        f
        for f in FORMATOS.values()
        if f.admite_escritura and (familia is None or f.familia == familia)
    )


def por_extension(extension: str) -> tuple[Formato, ...]:
    """Todos los formatos que usan esa extension. Puede devolver varios: `.tif` es
    GeoTIFF, BigTIFF y COG a la vez, y por eso la extension no basta para decidir."""
    ext = extension.lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    return tuple(f for f in FORMATOS.values() if ext in f.extensiones)
