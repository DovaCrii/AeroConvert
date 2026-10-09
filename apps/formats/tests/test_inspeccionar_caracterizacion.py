"""Caracterización de `deteccion.inspeccionar` (F11.8, etapa 3), antes de partirla en pasos.

`inspeccionar` tiene ~250 líneas y una rama por cada formato que sabe leer. Estas pruebas
fijan, para una colección de archivos sintéticos (los mismos constructores que usan las demás
pruebas de formatos), **lo que devuelve hoy**: formato, confianza, sistema de referencia,
avisos —con su texto— y qué cabeceras se leyeron. El refactor no puede cambiar ninguna.

No son un oráculo externo: describen el comportamiento actual, no su corrección. La corrección
de cada lector la prueban sus propios módulos (`test_tiff.py`, `test_las.py`, ...).
"""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from apps.formats import deteccion

from .constructor import (
    ASC_MINIMO,
    bigtiff_minimo,
    copc_minimo,
    geotiff_minimo,
    las_minimo,
    rinex_minimo,
    trimble_minimo,
)

LANDXML = """<?xml version="1.0" encoding="UTF-8"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2">
  <Units><Metric linearUnit="meter" /></Units>
  <CoordinateSystem epsgCode="{epsg}" name="x" />
  <CgPoints name="Control">
    <CgPoint name="P1">7318729.036 495279.406 3042.641</CgPoint>
  </CgPoints>
</LandXML>
"""

VRT = (
    '<VRTDataset rasterXSize="10" rasterYSize="1"><VRTRasterBand dataType="Byte" band="1">'
    '<SimpleSource><SourceFilename relativeToVRT="0">otro.tif</SourceFilename>'
    "<SourceBand>1</SourceBand></SimpleSource></VRTRasterBand></VRTDataset>"
)

LIBRETA = "punto;este;norte;cota\nP1;495279.4;7318729.0;3042.6\nP2;495137.1;7318700.3;3045.0\n"


def _pdf_minimo() -> bytes:
    import io

    from pypdf import PdfWriter

    escritor = PdfWriter()
    escritor.add_blank_page(width=595, height=842)
    memoria = io.BytesIO()
    escritor.write(memoria)
    return memoria.getvalue()


def _pdf_cifrado() -> bytes:
    import io

    from pypdf import PdfWriter

    escritor = PdfWriter()
    escritor.add_blank_page(width=595, height=842)
    escritor.encrypt("secreto")
    memoria = io.BytesIO()
    escritor.write(memoria)
    return memoria.getvalue()


#: nombre del caso -> (nombre de archivo, contenido). Los nombres de archivo importan: la
#: extensión es la mitad de la detección.
CASOS: dict[str, tuple[str, object]] = {
    "geotiff": ("orto.tif", geotiff_minimo()),
    "geotiff-con-alfa": ("alfa.tif", geotiff_minimo(alfa=True, bandas=4)),
    "geotiff-sin-crs": ("sin_crs.tif", geotiff_minimo(epsg=None, escala_m=None, origen=None)),
    "bigtiff-innecesario": ("grande.tif", bigtiff_minimo()),
    "tiff-con-cabecera-rota": ("roto.tif", b"II*\x00\x08\x00\x00\x00" + b"\xff" * 40),
    "tiff-solo-la-marca": ("corto.tif", b"II*\x00\x00\x00"),
    "asc": ("terreno.asc", ASC_MINIMO),
    "asc-con-prj": ("con_prj.asc", ASC_MINIMO),  # el .prj se escribe aparte, ver `_preparar`
    "extension-desconocida": ("cosa.zzz", b"\x01\x02\x03\x04"),
    "jp2-renombrado": ("mentira.tif", b"\x00\x00\x00\x0cjP  \r\n\x87\n" + bytes(64)),
    "vrt-disfrazado": ("falso.asc", VRT),
    "vrt-declarado": ("mosaico.vrt", VRT),
    "las": ("nube.las", las_minimo()),
    "laz": ("nube.laz", las_minimo(comprimido=True)),
    "copc": ("nube.copc.laz", copc_minimo()),
    "las-con-wkt": ("wkt.las", las_minimo(epsg=None, wkt='PROJCS["x",GEOGCS["y"]]')),
    "las-sin-crs": ("sin.las", las_minimo(epsg=None)),
    "las-coordenadas-grandes": (
        "lejos.las",
        las_minimo(
            minimo=(5_000_000.0, 5_000_000.0, 0.0),
            maximo=(5_000_100.0, 5_000_100.0, 10.0),
            desplazamiento=(5_000_000.0, 5_000_000.0, 0.0),
        ),
    ),
    "las-truncado": ("trunc.las", las_minimo()[:60]),
    "libreta": ("puntos.csv", LIBRETA),
    "csv-que-no-es-libreta": ("datos.csv", "uno;dos\nhola;mundo\n"),
    "pdf": ("plano.pdf", _pdf_minimo()),
    "pdf-cifrado": ("secreto.pdf", _pdf_cifrado()),
    "pdf-roto": ("roto.pdf", b"%PDF-1.4\nnada de nada\n"),
    "trimble": ("sesion.T02", trimble_minimo()),
    "trimble-que-no-lo-es": ("falso.T02", b"\x00\x00\x00\x0d" + bytes(range(17)) + b"nada"),
    "rinex-v3": ("obs.rnx", rinex_minimo(version="3.04")),
    "rinex-v2": ("obs.24o", rinex_minimo(version="2.11")),
    "rinex-que-no-lo-es": ("falso.obs", "esto no es un rinex\nni lo parece\n"),
    "landxml": ("proyecto.xml", LANDXML.format(epsg="32719")),
    "landxml-epsg-con-prefijo": ("prefijo.xml", LANDXML.format(epsg="EPSG:32719")),
    "landxml-epsg-roto": ("roto.xml", LANDXML.format(epsg="abc")),
    "xml-que-no-es-landxml": ("otro.xml", '<?xml version="1.0"?><cosa><x/></cosa>'),
    "kml": (
        "ruta.kml",
        '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>',
    ),
}

#: Casos que traen un `.prj` al lado (la georreferencia de «lateral»).
PRJ_LATERAL = {
    "asc-con-prj": (
        'PROJCS["WGS_1984_UTM_Zone_19S",GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
        'SPHEROID["WGS_1984",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],'
        'UNIT["Degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],'
        'PARAMETER["False_Easting",500000.0],PARAMETER["False_Northing",10000000.0],'
        'PARAMETER["Central_Meridian",-69.0],PARAMETER["Scale_Factor",0.9996],'
        'PARAMETER["Latitude_Of_Origin",0.0],UNIT["Meter",1.0]]'
    ),
}


def _escribir(tmp_path: Path, caso: str) -> Path:
    nombre, contenido = CASOS[caso]
    ruta = tmp_path / nombre
    if isinstance(contenido, str):
        ruta.write_text(contenido, encoding="utf-8", newline="\n")
    else:
        ruta.write_bytes(contenido)
    if caso in PRJ_LATERAL:
        ruta.with_suffix(".prj").write_text(PRJ_LATERAL[caso], encoding="utf-8", newline="\n")
    return ruta


def _foto(inspeccion, tmp_path: Path) -> dict:
    """Lo observable de una inspección, con las rutas temporales borradas."""

    def limpio(texto: str) -> str:
        return texto.replace(str(tmp_path), "<tmp>")

    return {
        "formato": inspeccion.codigo_formato,
        "confianza": inspeccion.confianza,
        "crs": (inspeccion.crs.autoridad, inspeccion.crs.codigo, inspeccion.crs.origen),
        "avisos": [limpio(a) for a in inspeccion.avisos],
        "cabeceras": sorted(
            nombre
            for nombre in ("tiff", "las", "puntos", "landxml", "pdf", "trimble")
            if getattr(inspeccion, nombre) is not None
        ),
        "acompanantes": [
            (a.ruta.name, a.extension, a.presente, a.imprescindible)
            for a in inspeccion.acompanantes
        ],
        "bytes": inspeccion.bytes_totales,
        "nombre": inspeccion.nombre,
    }


#: Lo que devuelve **hoy** cada caso. Se generó ejecutando el código sin tocar y revisando cada
#: valor a ojo; si un refactor lo cambia, la prueba se pone roja y hay que explicar por qué.
ESPERADO: dict[str, dict] = {
    "asc": {
        "acompanantes": [("terreno.prj", ".prj", False, True)],
        "avisos": [],
        "bytes": 208,
        "cabeceras": [],
        "confianza": "extensión",
        "crs": ("", "", "desconocido"),
        "formato": "asc",
        "nombre": "terreno.asc",
    },
    "asc-con-prj": {
        "acompanantes": [("con_prj.prj", ".prj", True, True)],
        "avisos": [],
        "bytes": 208,
        "cabeceras": [],
        "confianza": "extensión",
        "crs": ("EPSG", "32719", "sidecar-prj"),
        "formato": "asc",
        "nombre": "con_prj.asc",
    },
    "bigtiff-innecesario": {
        "acompanantes": [
            ("grande.tif.aux.xml", ".aux.xml", False, False),
            ("grande.msk", ".msk", False, False),
            ("grande.ovr", ".ovr", False, False),
            ("grande.prj", ".prj", False, False),
            ("grande.tfw", ".tfw", False, False),
        ],
        "avisos": [
            "Es BigTIFF sin necesitarlo: sin comprimir ocupa 0,00 GB, "
            "muy por debajo del techo de 4 GB del TIFF clásico. "
            "Reescribirlo como clásico no pierde nada y lo abre mucho "
            "más software."
        ],
        "bytes": 364,
        "cabeceras": ["tiff"],
        "confianza": "firma",
        "crs": ("EPSG", "32719", "incrustado"),
        "formato": "bigtiff",
        "nombre": "grande.tif",
    },
    "copc": {
        "acompanantes": [],
        "avisos": [
            "Las coordenadas son demasiado grandes para float32: pasarlas a precisión "
            "simple sin restar el desplazamiento de cabecera mueve los puntos unos 20 "
            "cm. Cualquier visor que lo haga mal se notará."
        ],
        "bytes": 667,
        "cabeceras": ["las"],
        "confianza": "firma",
        "crs": ("EPSG", "32719", "incrustado"),
        "formato": "copc",
        "nombre": "nube.copc.laz",
    },
    "csv-que-no-es-libreta": {
        "acompanantes": [],
        "avisos": [
            "Tiene extensión de libreta de puntos pero no lo es: "
            "Ninguna forma de partir las líneas da tres columnas o "
            "más. Esto no parece un archivo de puntos delimitado."
        ],
        "bytes": 19,
        "cabeceras": [],
        "confianza": "desconocido",
        "crs": ("", "", "desconocido"),
        "formato": "",
        "nombre": "datos.csv",
    },
    "extension-desconocida": {
        "acompanantes": [],
        "avisos": [],
        "bytes": 4,
        "cabeceras": [],
        "confianza": "desconocido",
        "crs": ("", "", "desconocido"),
        "formato": "",
        "nombre": "cosa.zzz",
    },
    "geotiff": {
        "acompanantes": [
            ("orto.tif.aux.xml", ".aux.xml", False, False),
            ("orto.msk", ".msk", False, False),
            ("orto.ovr", ".ovr", False, False),
            ("orto.prj", ".prj", False, False),
            ("orto.tfw", ".tfw", False, False),
        ],
        "avisos": [],
        "bytes": 258,
        "cabeceras": ["tiff"],
        "confianza": "firma",
        "crs": ("EPSG", "32719", "incrustado"),
        "formato": "geotiff",
        "nombre": "orto.tif",
    },
    "geotiff-con-alfa": {
        "acompanantes": [
            ("alfa.tif.aux.xml", ".aux.xml", False, False),
            ("alfa.msk", ".msk", False, False),
            ("alfa.ovr", ".ovr", False, False),
            ("alfa.prj", ".prj", False, False),
            ("alfa.tfw", ".tfw", False, False),
        ],
        "avisos": [
            "Trae una banda alfa. Varios CAD la pintan como una banda "
            "gris más o dejan negro donde debería ser transparente."
        ],
        "bytes": 326,
        "cabeceras": ["tiff"],
        "confianza": "firma",
        "crs": ("EPSG", "32719", "incrustado"),
        "formato": "geotiff",
        "nombre": "alfa.tif",
    },
    "geotiff-sin-crs": {
        "acompanantes": [
            ("sin_crs.tif.aux.xml", ".aux.xml", False, False),
            ("sin_crs.msk", ".msk", False, False),
            ("sin_crs.ovr", ".ovr", False, False),
            ("sin_crs.prj", ".prj", False, False),
            ("sin_crs.tfw", ".tfw", False, False),
        ],
        "avisos": [],
        "bytes": 126,
        "cabeceras": ["tiff"],
        "confianza": "firma",
        "crs": ("", "", "desconocido"),
        "formato": "geotiff",
        "nombre": "sin_crs.tif",
    },
    "jp2-renombrado": {
        "acompanantes": [
            ("mentira.tif.aux.xml", ".aux.xml", False, False),
            ("mentira.j2w", ".j2w", False, False),
            ("mentira.prj", ".prj", False, False),
        ],
        "avisos": [
            "La extensión dice GeoTIFF clásico pero el contenido es JPEG 2000. Gana el contenido."
        ],
        "bytes": 76,
        "cabeceras": [],
        "confianza": "firma",
        "crs": ("", "", "desconocido"),
        "formato": "jp2",
        "nombre": "mentira.tif",
    },
    "kml": {
        "acompanantes": [],
        "avisos": [],
        "bytes": 82,
        "cabeceras": [],
        "confianza": "extensión",
        "crs": ("EPSG", "4326", "por-norma"),
        "formato": "kml",
        "nombre": "ruta.kml",
    },
    "landxml": {
        "acompanantes": [],
        "avisos": ["Contiene 1 puntos."],
        "bytes": 327,
        "cabeceras": ["landxml"],
        "confianza": "extensión",
        "crs": ("EPSG", "32719", "incrustado"),
        "formato": "landxml",
        "nombre": "proyecto.xml",
    },
    "landxml-epsg-con-prefijo": {
        "acompanantes": [],
        "avisos": ["Contiene 1 puntos."],
        "bytes": 332,
        "cabeceras": ["landxml"],
        "confianza": "extensión",
        "crs": ("EPSG", "32719", "incrustado"),
        "formato": "landxml",
        "nombre": "prefijo.xml",
    },
    "landxml-epsg-roto": {
        "acompanantes": [],
        "avisos": [
            "El LandXML dice epsgCode «abc», que no es un número de "
            "EPSG: no se usa. Declare el sistema al convertir.",
            "Contiene 1 puntos.",
        ],
        "bytes": 325,
        "cabeceras": ["landxml"],
        "confianza": "extensión",
        "crs": ("", "", "desconocido"),
        "formato": "landxml",
        "nombre": "roto.xml",
    },
    "las": {
        "acompanantes": [],
        "avisos": [
            "Las coordenadas son demasiado grandes para float32: pasarlas a precisión "
            "simple sin restar el desplazamiento de cabecera mueve los puntos unos 20 "
            "cm. Cualquier visor que lo haga mal se notará."
        ],
        "bytes": 305,
        "cabeceras": ["las"],
        "confianza": "firma",
        "crs": ("EPSG", "32719", "incrustado"),
        "formato": "las",
        "nombre": "nube.las",
    },
    "las-con-wkt": {
        "acompanantes": [],
        "avisos": [
            "Las coordenadas son demasiado grandes para float32: pasarlas a "
            "precisión simple sin restar el desplazamiento de cabecera mueve "
            "los puntos unos 20 cm. Cualquier visor que lo haga mal se "
            "notará."
        ],
        "bytes": 305,
        "cabeceras": ["las"],
        "confianza": "firma",
        "crs": ("", "", "desconocido"),
        "formato": "las",
        "nombre": "wkt.las",
    },
    "las-coordenadas-grandes": {
        "acompanantes": [],
        "avisos": [
            "Las coordenadas son demasiado grandes para float32: "
            "pasarlas a precisión simple sin restar el "
            "desplazamiento de cabecera mueve los puntos unos 20 "
            "cm. Cualquier visor que lo haga mal se notará."
        ],
        "bytes": 305,
        "cabeceras": ["las"],
        "confianza": "firma",
        "crs": ("EPSG", "32719", "incrustado"),
        "formato": "las",
        "nombre": "lejos.las",
    },
    "las-sin-crs": {
        "acompanantes": [],
        "avisos": [
            "Las coordenadas son demasiado grandes para float32: pasarlas a "
            "precisión simple sin restar el desplazamiento de cabecera mueve "
            "los puntos unos 20 cm. Cualquier visor que lo haga mal se "
            "notará."
        ],
        "bytes": 227,
        "cabeceras": ["las"],
        "confianza": "firma",
        "crs": ("", "", "desconocido"),
        "formato": "las",
        "nombre": "sin.las",
    },
    "las-truncado": {
        "acompanantes": [],
        "avisos": ["Empieza como un LAS pero la cabecera no se pudo leer: No empieza con LASF."],
        "bytes": 60,
        "cabeceras": [],
        "confianza": "firma",
        "crs": ("", "", "desconocido"),
        "formato": "las",
        "nombre": "trunc.las",
    },
    "laz": {
        "acompanantes": [],
        "avisos": [
            "Las coordenadas son demasiado grandes para float32: pasarlas a precisión "
            "simple sin restar el desplazamiento de cabecera mueve los puntos unos 20 "
            "cm. Cualquier visor que lo haga mal se notará."
        ],
        "bytes": 305,
        "cabeceras": ["las"],
        "confianza": "firma",
        "crs": ("EPSG", "32719", "incrustado"),
        "formato": "laz",
        "nombre": "nube.laz",
    },
    "libreta": {
        "acompanantes": [("puntos.prj", ".prj", False, True)],
        "avisos": [
            "Orden de columnas PENZ, deducido del rango UTM de las coordenadas. "
            "Compruébelo en la vista previa antes de convertir."
        ],
        "bytes": 80,
        "cabeceras": ["puntos"],
        "confianza": "extensión",
        "crs": ("", "", "desconocido"),
        "formato": "puntos",
        "nombre": "puntos.csv",
    },
    "pdf": {
        "acompanantes": [],
        "avisos": ["Contiene 1 página(s) · A4 vertical."],
        "bytes": 431,
        "cabeceras": ["pdf"],
        "confianza": "firma",
        "crs": ("", "", "desconocido"),
        "formato": "pdf",
        "nombre": "plano.pdf",
    },
    "pdf-cifrado": {
        "acompanantes": [],
        "avisos": [
            "Pide contraseña, así que no se puede leer ni componer. Ábralo con "
            "la clave y guárdelo sin ella."
        ],
        "bytes": 828,
        "cabeceras": ["pdf"],
        "confianza": "firma",
        "crs": ("", "", "desconocido"),
        "formato": "pdf",
        "nombre": "secreto.pdf",
    },
    "pdf-roto": {
        "acompanantes": [],
        "avisos": [
            "Empieza como un PDF pero no se pudo leer: No se pudo leer el PDF: "
            "Stream has ended unexpectedly"
        ],
        "bytes": 22,
        "cabeceras": [],
        "confianza": "firma",
        "crs": ("", "", "desconocido"),
        "formato": "pdf",
        "nombre": "roto.pdf",
    },
    "rinex-que-no-lo-es": {
        "acompanantes": [],
        "avisos": [
            "Tiene extensión de RINEX de observación pero no lo es: La "
            "primera línea no es «RINEX VERSION / TYPE»."
        ],
        "bytes": 33,
        "cabeceras": [],
        "confianza": "desconocido",
        "crs": ("", "", "desconocido"),
        "formato": "",
        "nombre": "falso.obs",
    },
    "rinex-v2": {
        "acompanantes": [],
        "avisos": ["RINEX 2.11 de observación, receptor TRIMBLE NETR9."],
        "bytes": 1953,
        "cabeceras": [],
        "confianza": "extensión",
        "crs": ("", "", "desconocido"),
        "formato": "rinex_obs",
        "nombre": "obs.24o",
    },
    "rinex-v3": {
        "acompanantes": [],
        "avisos": ["RINEX 3.04 de observación, receptor TRIMBLE NETR9."],
        "bytes": 2048,
        "cabeceras": [],
        "confianza": "extensión",
        "crs": ("", "", "desconocido"),
        "formato": "rinex_obs",
        "nombre": "obs.rnx",
    },
    "tiff-con-cabecera-rota": {
        "acompanantes": [
            ("roto.tif.aux.xml", ".aux.xml", False, False),
            ("roto.msk", ".msk", False, False),
            ("roto.ovr", ".ovr", False, False),
            ("roto.prj", ".prj", False, False),
            ("roto.tfw", ".tfw", False, False),
        ],
        "avisos": [
            "Empieza como un TIFF pero la cabecera no se pudo leer: "
            "El primer directorio no declara ancho y alto."
        ],
        "bytes": 48,
        "cabeceras": [],
        "confianza": "firma",
        "crs": ("", "", "desconocido"),
        "formato": "geotiff",
        "nombre": "roto.tif",
    },
    "tiff-solo-la-marca": {
        "acompanantes": [
            ("corto.tif.aux.xml", ".aux.xml", False, False),
            ("corto.msk", ".msk", False, False),
            ("corto.ovr", ".ovr", False, False),
            ("corto.prj", ".prj", False, False),
            ("corto.tfw", ".tfw", False, False),
        ],
        "avisos": [
            "Empieza como un TIFF pero la cabecera no se pudo leer: El "
            "archivo tiene menos de 8 bytes."
        ],
        "bytes": 6,
        "cabeceras": [],
        "confianza": "firma",
        "crs": ("", "", "desconocido"),
        "formato": "geotiff",
        "nombre": "corto.tif",
    },
    "trimble": {
        "acompanantes": [],
        "avisos": ["Dato crudo de TRIMBLE NETR9, serie 5303K49763."],
        "bytes": 194,
        "cabeceras": ["trimble"],
        "confianza": "firma",
        "crs": ("", "", "desconocido"),
        "formato": "trimble_t0x",
        "nombre": "sesion.T02",
    },
    "trimble-que-no-lo-es": {
        "acompanantes": [],
        "avisos": [
            "Empieza como un crudo de Trimble pero no lo es: No trae "
            "el bloque comprimido que esperan estos archivos."
        ],
        "bytes": 25,
        "cabeceras": [],
        "confianza": "desconocido",
        "crs": ("", "", "desconocido"),
        "formato": "",
        "nombre": "falso.T02",
    },
    "vrt-declarado": {
        "acompanantes": [],
        "avisos": [],
        "bytes": 228,
        "cabeceras": [],
        "confianza": "extensión",
        "crs": ("", "", "desconocido"),
        "formato": "vrt",
        "nombre": "mosaico.vrt",
    },
    "vrt-disfrazado": {
        "acompanantes": [],
        "avisos": [
            "falso.asc es un mosaico virtual (VRT) con otra extensión. Un "
            "VRT apunta a otros archivos del disco, así que solo se acepta "
            "con la extensión .vrt."
        ],
        "bytes": 228,
        "cabeceras": [],
        "confianza": "desconocido",
        "crs": ("", "", "desconocido"),
        "formato": "",
        "nombre": "falso.asc",
    },
    "xml-que-no-es-landxml": {
        "acompanantes": [],
        "avisos": [
            "Tiene extensión .xml pero no es un LandXML: El archivo "
            "es XML pero su raiz no es <LandXML>."
        ],
        "bytes": 38,
        "cabeceras": [],
        "confianza": "desconocido",
        "crs": ("", "", "desconocido"),
        "formato": "",
        "nombre": "otro.xml",
    },
}


@pytest.mark.parametrize("caso", sorted(CASOS))
def test_lo_que_devuelve_hoy(tmp_path, caso):
    ruta = _escribir(tmp_path, caso)
    assert _foto(deteccion.inspeccionar(ruta), tmp_path) == ESPERADO[caso]


# --- Las rutas por las que no se llega a mirar dentro ---------------------------------------


class TestOrigenIlegible:
    def test_no_existe(self, tmp_path):
        ruta = tmp_path / "nada.tif"
        with pytest.raises(deteccion.OrigenIlegible) as fallo:
            deteccion.inspeccionar(ruta)
        assert fallo.value.codigo == "origen-no-legible"
        assert str(fallo.value) == f"No hay ningún archivo en {ruta}."

    def test_una_carpeta(self, tmp_path):
        with pytest.raises(deteccion.OrigenIlegible) as fallo:
            deteccion.inspeccionar(tmp_path)
        assert fallo.value.codigo == "origen-no-legible"
        assert str(fallo.value) == f"{tmp_path} es una carpeta, no un archivo."

    def test_cero_bytes(self, tmp_path):
        ruta = tmp_path / "vacio.tif"
        ruta.write_bytes(b"")
        with pytest.raises(deteccion.OrigenIlegible) as fallo:
            deteccion.inspeccionar(ruta)
        assert (fallo.value.codigo, str(fallo.value)) == (
            "origen-no-legible",
            "vacio.tif tiene 0 bytes.",
        )

    def test_un_marcador_de_onedrive(self, tmp_path, monkeypatch):
        ruta = tmp_path / "nube.tif"
        ruta.write_bytes(geotiff_minimo())
        monkeypatch.setattr(deteccion, "_es_marcador_en_la_nube", lambda r: True)
        with pytest.raises(deteccion.OrigenIlegible) as fallo:
            deteccion.inspeccionar(ruta)
        assert fallo.value.codigo == "solo-marcador-en-la-nube"
        assert str(fallo.value).startswith("nube.tif figura en la carpeta pero su contenido")

    @pytest.mark.parametrize(
        ("excepcion", "codigo", "texto"),
        [
            (
                PermissionError("denegado"),
                "origen-bloqueado",
                "a.tif esta abierto en otro programa o no hay permiso de lectura.",
            ),
            (OSError("disco roto"), "origen-no-legible", "No se pudo leer a.tif: disco roto"),
        ],
        ids=["permiso", "otro-os"],
    )
    def test_no_se_puede_abrir(self, tmp_path, monkeypatch, excepcion, codigo, texto):
        ruta = tmp_path / "a.tif"
        ruta.write_bytes(geotiff_minimo())
        reales = builtins.open

        def abrir(destino, modo="r", *a, **k):
            if str(destino) == str(ruta):
                raise excepcion
            return reales(destino, modo, *a, **k)

        monkeypatch.setattr(builtins, "open", abrir)
        with pytest.raises(deteccion.OrigenIlegible) as fallo:
            deteccion.inspeccionar(ruta)
        assert (fallo.value.codigo, str(fallo.value)) == (codigo, texto)

    def test_el_nombre_de_texto_y_la_ruta_de_texto_valen_igual(self, tmp_path):
        ruta = tmp_path / "orto.tif"
        ruta.write_bytes(geotiff_minimo())
        a = deteccion.inspeccionar(ruta)
        b = deteccion.inspeccionar(str(ruta))
        assert _foto(a, tmp_path) == _foto(b, tmp_path)
