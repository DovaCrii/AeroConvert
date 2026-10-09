"""Caracterización de `informe.construir` (F11.8, etapa 3), antes de partirla en secciones.

`construir` tiene ~180 líneas: estilos, una `tabla()` interna y siete secciones seguidas. Aquí se
fija, para varios trabajos con fechas, identificadores y huellas **fijos**, el texto que sale
en el PDF (extraído con pypdf, que no lo escribió) y el orden de sus secciones. El refactor no
puede cambiar ni una palabra ni el orden.

El texto se compara tal cual sale de pypdf; si una versión de pypdf cambia cómo parte las
líneas, se regenera `ESPERADO` y se revisa a ojo contra el trabajo.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime

import pypdf
import pytest
from django.contrib.auth import get_user_model

from apps.jobs import informe
from apps.jobs.models import ConversionJob, EntradaDeTrabajo, JobEvent

pytestmark = pytest.mark.django_db

SHA_A = "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801"
SHA_B = "0b9e8d7c6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa9988776655"
SHA_C = "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00"

AHORA = datetime(2026, 10, 9, 15, 30, 0, tzinfo=UTC)


def _t(minutos: int) -> datetime:
    return datetime(2026, 10, 9, 15, minutos, 0, tzinfo=UTC)


BASE = {
    "source_path": "/datos/orto.tif",
    "source_name": "orto_bhp.tif",
    "source_size_bytes": 123_456_789,
    "source_sha256": SHA_A,
    "source_format_code": "geotiff",
    "source_format_confidence": "firma",
    "source_crs_authority": "EPSG",
    "source_crs_code": "32719",
    "source_crs_origin": "incrustado",
    "target_format_code": "cog",
    "engine_id": "gdal-raster",
    "engine_version": "GDAL 3.12.4",
    "output_path": "C:\\salidas\\orto_bhp.cog.tif",
    "output_size_bytes": 98_765_432,
    "output_sha256": SHA_B,
    "status": "done",
    "queued_at": _t(25),
    "started_at": _t(26),
    "finished_at": _t(28),
    "verified_at": _t(28),
    "verification": {"epsg": "32719", "ancho_px": 14526, "alto_px": 14443, "bandas": 4},
    "options": {"compresion": "DEFLATE", "tamano_tesela": "512"},
}

#: nombre del caso -> campos que se cambian respecto de BASE.
CASOS: dict[str, dict] = {
    "hecho-geoespacial": {},
    "error-con-motivo": {
        "status": "error",
        "reason_code": "sin-salida",
        "reason_detail": "El motor termino sin escribir ningún archivo.",
        "output_path": "",
        "output_size_bytes": 0,
        "output_sha256": "",
        "verified_at": None,
        "verification": {},
    },
    "error-solo-codigo": {
        "status": "error",
        "reason_code": "crs-ausente",
        "output_path": "",
        "verification": {},
    },
    "cancelado": {"status": "cancelled", "verification": {}, "options": {}},
    "en-cola": {
        "status": "queued",
        "started_at": None,
        "finished_at": None,
        "verified_at": None,
        "verification": {},
        "output_path": "",
        "output_size_bytes": 0,
        "output_sha256": "",
    },
    "con-reproyeccion-y-opciones-ocultas": {
        "target_crs_authority": "EPSG",
        "target_crs_code": "32718",
        "options": {
            "compresion": "JPEG",
            "contrasena": "no-debe-salir",
            "terminos": ["secreto"],
            "calidad": 85,
            "con_piramides": True,
            "complejo": {"x": 1},
            "ratio": 0.5,
        },
    },
    "verificacion-anidada-y-larga": {
        "verification": {
            "dimensiones": {"ancho_px": 100, "alto_px": 80},
            "cuenta": list(range(25)),
            "tupla": (1, 2),
            "texto_largo": "palabra " * 10,
            "nulo": None,
            "bandas": 3,
        },
    },
    "verificacion-de-muchas-filas": {
        "verification": {f"medida_{i}": i for i in range(60)},
    },
    "herramienta-de-documentos": {
        "herramienta": "numerar",
        "engine_id": "documentos",
        "engine_version": "docs 1.0",
        "source_format_code": "",
        "source_format_confidence": "",
        "source_crs_authority": "",
        "source_crs_code": "",
        "source_crs_origin": "",
        "target_format_code": "doc:numerar",
        "options": {"posicion": "abajo-derecha", "formato": "Página {n}"},
    },
    "sin-huellas": {
        "source_sha256": "",
        "output_sha256": "",
        "source_size_bytes": 0,
        "source_name": "",
        "source_format_code": "",
        "source_format_confidence": "",
        "source_crs_code": "",
    },
    "tamanos-de-todas-las-magnitudes": {"source_size_bytes": 512, "output_size_bytes": 2048},
    "terabytes": {"source_size_bytes": 3 * 1024**4, "output_size_bytes": 5 * 1024**5},
    "nombre-con-caracteres-fuera-de-cp1252": {
        "source_name": "ortofoto_ñandú_日本.tif",
        "reason_detail": "x",
    },
}


def _crear(caso: str) -> ConversionJob:
    usuario = get_user_model().objects.create_user(f"u-{caso}"[:30], password="x" * 20)  # nosec B106
    campos = {**BASE, **CASOS.get(caso, {})}
    job = ConversionJob.objects.create(
        id=uuid.UUID("12345678-1234-5678-1234-567812345678"), owner=usuario, **campos
    )
    return job


def _crear_con_avisos_y_entradas() -> ConversionJob:
    job = _crear("hecho-geoespacial")
    job.registrar("Aviso uno del motor.", nivel=JobEvent.AVISO)
    job.registrar("Falló un paso menor.", nivel=JobEvent.ERROR)
    job.registrar("Esto es solo información.", nivel=JobEvent.INFO)
    for n in range(25):  # más de veinte: se cortan
        job.registrar(f"Aviso número {n}", nivel=JobEvent.AVISO)
    EntradaDeTrabajo.objects.create(
        job=job, orden=0, ruta="/datos/a.pdf", nombre="a.pdf", bytes=1500, sha256=SHA_A
    )
    EntradaDeTrabajo.objects.create(
        job=job, orden=1, ruta="/datos/b.pdf", nombre="b.pdf", bytes=2_500_000, sha256=""
    )
    return job


def _crear_con_una_entrada() -> ConversionJob:
    job = _crear("hecho-geoespacial")
    EntradaDeTrabajo.objects.create(
        job=job, orden=0, ruta="/datos/a.pdf", nombre="a.pdf", bytes=1500, sha256=SHA_A
    )
    return job


CASOS_ESPECIALES = {
    "con-avisos-y-varias-entradas": _crear_con_avisos_y_entradas,
    "una-sola-entrada-no-se-lista": _crear_con_una_entrada,
}


def _casos() -> list[str]:
    return sorted(set(CASOS) | set(CASOS_ESPECIALES))


def _texto(caso: str, monkeypatch) -> str:
    class Reloj:
        @staticmethod
        def now():
            return AHORA

        localtime = staticmethod(informe.timezone.localtime)

    monkeypatch.setattr(informe, "timezone", Reloj)
    job = CASOS_ESPECIALES[caso]() if caso in CASOS_ESPECIALES else _crear(caso)
    datos = informe.construir(job)
    lector = pypdf.PdfReader(io.BytesIO(datos))
    return "\n".join(p.extract_text() or "" for p in lector.pages)


#: Lo que sale **hoy** para cada caso (generado con el código sin tocar y revisado a ojo).
ESPERADO: dict[str, str] = {
    "cancelado": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · generado el 09/10/2026 12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "Cancelado\n"
    "Programa\n"
    "gdal-raster · GDAL 3.12.4\n"
    "Conversión\n"
    "geotiff a cog\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "09/10/2026 12:26:00\n"
    "Terminó\n"
    "09/10/2026 12:28:00\n"
    "Verificado\n"
    "09/10/2026 12:28:00\n"
    "Duración\n"
    "120.0 s\n"
    "Lo que entró\n"
    "Archivo\n"
    "orto_bhp.tif\n"
    "Tamaño\n"
    "117.7 MB (123.456.789 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Formato leído\n"
    "geotiff (confianza: firma)\n"
    "Sistema de coordenadas\n"
    "EPSG:32719 (declarado por: incrustado)\n"
    "Lo que salió\n"
    "Archivo\n"
    "orto_bhp.cog.tif\n"
    "Tamaño\n"
    "94.2 MB (98.765.432 bytes)\n"
    "sha256\n"
    "0b9e8d7c6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa9988776655\n"
    "Sistema de coordenadas\n"
    "el mismo del original\n"
    "Lo que se midió en la salida\n"
    "Este trabajo no guardó mediciones de la salida.\n"
    "El original\n"
    "El trabajo no terminó: no hay entrega que acompañe este informe.\n",
    "con-avisos-y-varias-entradas": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · generado el "
    "09/10/2026 12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "Terminado\n"
    "Programa\n"
    "gdal-raster · GDAL 3.12.4\n"
    "Conversión\n"
    "geotiff a cog\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "09/10/2026 12:26:00\n"
    "Terminó\n"
    "09/10/2026 12:28:00\n"
    "Verificado\n"
    "09/10/2026 12:28:00\n"
    "Duración\n"
    "120.0 s\n"
    "Lo que entró\n"
    "Archivo\n"
    "orto_bhp.tif\n"
    "Tamaño\n"
    "117.7 MB (123.456.789 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Formato leído\n"
    "geotiff (confianza: firma)\n"
    "Sistema de coordenadas\n"
    "EPSG:32719 (declarado por: incrustado)\n"
    "Entrada 1\n"
    "a.pdf — 1.5 KB (1.500 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Entrada 2\n"
    "b.pdf — 2.4 MB (2.500.000 bytes)\n"
    "sha256\n"
    "no calculado\n"
    "Lo que salió\n"
    "Archivo\n"
    "orto_bhp.cog.tif\n"
    "Tamaño\n"
    "94.2 MB (98.765.432 bytes)\n"
    "sha256\n"
    "0b9e8d7c6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa9988776655\n"
    "Sistema de coordenadas\n"
    "el mismo del original\n"
    "Lo que se midió en la salida\n"
    "epsg\n"
    "32719\n"
    "ancho px\n"
    "14526\n"
    "alto px\n"
    "14443\n"
    "bandas\n"
    "4\n"
    "Opciones aplicadas\n"
    "compresion\n"
    "DEFLATE\n"
    "tamano tesela\n"
    "512\n"
    "Avisos durante el trabajo\n"
    "error\n"
    "Falló un paso menor.\n"
    "El original\n"
    "\n"
    "El corredor comprobó al terminar que la fecha de "
    "modificación del original no cambió; si hubiera cambiado, el "
    "trabajo\n"
    "habría fallado. La huella de arriba se calculó antes de "
    "empezar.\n",
    "con-reproyeccion-y-opciones-ocultas": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · "
    "generado el 09/10/2026 12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "Terminado\n"
    "Programa\n"
    "gdal-raster · GDAL 3.12.4\n"
    "Conversión\n"
    "geotiff a cog\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "09/10/2026 12:26:00\n"
    "Terminó\n"
    "09/10/2026 12:28:00\n"
    "Verificado\n"
    "09/10/2026 12:28:00\n"
    "Duración\n"
    "120.0 s\n"
    "Lo que entró\n"
    "Archivo\n"
    "orto_bhp.tif\n"
    "Tamaño\n"
    "117.7 MB (123.456.789 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Formato leído\n"
    "geotiff (confianza: firma)\n"
    "Sistema de coordenadas\n"
    "EPSG:32719 (declarado por: incrustado)\n"
    "Lo que salió\n"
    "Archivo\n"
    "orto_bhp.cog.tif\n"
    "Tamaño\n"
    "94.2 MB (98.765.432 bytes)\n"
    "sha256\n"
    "0b9e8d7c6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa9988776655\n"
    "Sistema de coordenadas\n"
    "EPSG:32718\n"
    "Lo que se midió en la salida\n"
    "epsg\n"
    "32719\n"
    "ancho px\n"
    "14526\n"
    "alto px\n"
    "14443\n"
    "bandas\n"
    "4\n"
    "Opciones aplicadas\n"
    "compresion\n"
    "JPEG\n"
    "calidad\n"
    "85\n"
    "con piramides\n"
    "True\n"
    "ratio\n"
    "0.5\n"
    "El original\n"
    "El corredor comprobó al terminar que la fecha de "
    "modificación del original no cambió; si hubiera "
    "cambiado, el trabajo\n"
    "habría fallado. La huella de arriba se calculó antes "
    "de empezar.\n",
    "en-cola": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · generado el 09/10/2026 12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "En cola\n"
    "Programa\n"
    "gdal-raster · GDAL 3.12.4\n"
    "Conversión\n"
    "geotiff a cog\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "—\n"
    "Terminó\n"
    "—\n"
    "Verificado\n"
    "—\n"
    "Lo que entró\n"
    "Archivo\n"
    "orto_bhp.tif\n"
    "Tamaño\n"
    "117.7 MB (123.456.789 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Formato leído\n"
    "geotiff (confianza: firma)\n"
    "Sistema de coordenadas\n"
    "EPSG:32719 (declarado por: incrustado)\n"
    "Lo que salió\n"
    "Archivo\n"
    "—\n"
    "Tamaño\n"
    "—\n"
    "sha256\n"
    "no calculado\n"
    "Sistema de coordenadas\n"
    "el mismo del original\n"
    "Lo que se midió en la salida\n"
    "Este trabajo no guardó mediciones de la salida.\n"
    "Opciones aplicadas\n"
    "compresion\n"
    "DEFLATE\n"
    "tamano tesela\n"
    "512\n"
    "El original\n"
    "El trabajo no terminó: no hay entrega que acompañe este informe.\n",
    "error-con-motivo": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · generado el 09/10/2026 "
    "12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "Falló\n"
    "Programa\n"
    "gdal-raster · GDAL 3.12.4\n"
    "Conversión\n"
    "geotiff a cog\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "09/10/2026 12:26:00\n"
    "Terminó\n"
    "09/10/2026 12:28:00\n"
    "Verificado\n"
    "—\n"
    "Duración\n"
    "120.0 s\n"
    "Motivo\n"
    "sin-salida — El motor termino sin escribir ningún archivo.\n"
    "Lo que entró\n"
    "Archivo\n"
    "orto_bhp.tif\n"
    "Tamaño\n"
    "117.7 MB (123.456.789 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Formato leído\n"
    "geotiff (confianza: firma)\n"
    "Sistema de coordenadas\n"
    "EPSG:32719 (declarado por: incrustado)\n"
    "Lo que salió\n"
    "Archivo\n"
    "—\n"
    "Tamaño\n"
    "—\n"
    "sha256\n"
    "no calculado\n"
    "Sistema de coordenadas\n"
    "el mismo del original\n"
    "Lo que se midió en la salida\n"
    "Este trabajo no guardó mediciones de la salida.\n"
    "Opciones aplicadas\n"
    "compresion\n"
    "DEFLATE\n"
    "tamano tesela\n"
    "512\n"
    "El original\n"
    "El trabajo no terminó: no hay entrega que acompañe este informe.\n",
    "error-solo-codigo": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · generado el 09/10/2026 "
    "12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "Falló\n"
    "Programa\n"
    "gdal-raster · GDAL 3.12.4\n"
    "Conversión\n"
    "geotiff a cog\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "09/10/2026 12:26:00\n"
    "Terminó\n"
    "09/10/2026 12:28:00\n"
    "Verificado\n"
    "09/10/2026 12:28:00\n"
    "Duración\n"
    "120.0 s\n"
    "Motivo\n"
    "crs-ausente\n"
    "Lo que entró\n"
    "Archivo\n"
    "orto_bhp.tif\n"
    "Tamaño\n"
    "117.7 MB (123.456.789 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Formato leído\n"
    "geotiff (confianza: firma)\n"
    "Sistema de coordenadas\n"
    "EPSG:32719 (declarado por: incrustado)\n"
    "Lo que salió\n"
    "Archivo\n"
    "—\n"
    "Tamaño\n"
    "94.2 MB (98.765.432 bytes)\n"
    "sha256\n"
    "0b9e8d7c6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa9988776655\n"
    "Sistema de coordenadas\n"
    "el mismo del original\n"
    "Lo que se midió en la salida\n"
    "Este trabajo no guardó mediciones de la salida.\n"
    "Opciones aplicadas\n"
    "compresion\n"
    "DEFLATE\n"
    "tamano tesela\n"
    "512\n"
    "El original\n"
    "El trabajo no terminó: no hay entrega que acompañe este informe.\n",
    "hecho-geoespacial": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · generado el 09/10/2026 "
    "12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "Terminado\n"
    "Programa\n"
    "gdal-raster · GDAL 3.12.4\n"
    "Conversión\n"
    "geotiff a cog\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "09/10/2026 12:26:00\n"
    "Terminó\n"
    "09/10/2026 12:28:00\n"
    "Verificado\n"
    "09/10/2026 12:28:00\n"
    "Duración\n"
    "120.0 s\n"
    "Lo que entró\n"
    "Archivo\n"
    "orto_bhp.tif\n"
    "Tamaño\n"
    "117.7 MB (123.456.789 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Formato leído\n"
    "geotiff (confianza: firma)\n"
    "Sistema de coordenadas\n"
    "EPSG:32719 (declarado por: incrustado)\n"
    "Lo que salió\n"
    "Archivo\n"
    "orto_bhp.cog.tif\n"
    "Tamaño\n"
    "94.2 MB (98.765.432 bytes)\n"
    "sha256\n"
    "0b9e8d7c6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa9988776655\n"
    "Sistema de coordenadas\n"
    "el mismo del original\n"
    "Lo que se midió en la salida\n"
    "epsg\n"
    "32719\n"
    "ancho px\n"
    "14526\n"
    "alto px\n"
    "14443\n"
    "bandas\n"
    "4\n"
    "Opciones aplicadas\n"
    "compresion\n"
    "DEFLATE\n"
    "tamano tesela\n"
    "512\n"
    "El original\n"
    "El corredor comprobó al terminar que la fecha de modificación del "
    "original no cambió; si hubiera cambiado, el trabajo\n"
    "habría fallado. La huella de arriba se calculó antes de empezar.\n",
    "herramienta-de-documentos": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · generado el "
    "09/10/2026 12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "Terminado\n"
    "Programa\n"
    "numerar · docs 1.0\n"
    "Conversión\n"
    "— a doc:numerar\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "09/10/2026 12:26:00\n"
    "Terminó\n"
    "09/10/2026 12:28:00\n"
    "Verificado\n"
    "09/10/2026 12:28:00\n"
    "Duración\n"
    "120.0 s\n"
    "Lo que entró\n"
    "Archivo\n"
    "orto_bhp.tif\n"
    "Tamaño\n"
    "117.7 MB (123.456.789 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Formato leído\n"
    "—\n"
    "Sistema de coordenadas\n"
    "no declarado\n"
    "Lo que salió\n"
    "Archivo\n"
    "orto_bhp.cog.tif\n"
    "Tamaño\n"
    "94.2 MB (98.765.432 bytes)\n"
    "sha256\n"
    "0b9e8d7c6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa9988776655\n"
    "Sistema de coordenadas\n"
    "el mismo del original\n"
    "Lo que se midió en la salida\n"
    "epsg\n"
    "32719\n"
    "ancho px\n"
    "14526\n"
    "alto px\n"
    "14443\n"
    "bandas\n"
    "4\n"
    "Opciones aplicadas\n"
    "posicion\n"
    "abajo-derecha\n"
    "formato\n"
    "Página {n}\n"
    "El original\n"
    "El corredor comprobó al terminar que la fecha de modificación "
    "del original no cambió; si hubiera cambiado, el trabajo\n"
    "habría fallado. La huella de arriba se calculó antes de "
    "empezar.\n",
    "nombre-con-caracteres-fuera-de-cp1252": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · "
    "generado el 09/10/2026 12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "Terminado\n"
    "Programa\n"
    "gdal-raster · GDAL 3.12.4\n"
    "Conversión\n"
    "geotiff a cog\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "09/10/2026 12:26:00\n"
    "Terminó\n"
    "09/10/2026 12:28:00\n"
    "Verificado\n"
    "09/10/2026 12:28:00\n"
    "Duración\n"
    "120.0 s\n"
    "Lo que entró\n"
    "Archivo\n"
    "ortofoto_ñandú_??.tif\n"
    "Tamaño\n"
    "117.7 MB (123.456.789 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Formato leído\n"
    "geotiff (confianza: firma)\n"
    "Sistema de coordenadas\n"
    "EPSG:32719 (declarado por: incrustado)\n"
    "Lo que salió\n"
    "Archivo\n"
    "orto_bhp.cog.tif\n"
    "Tamaño\n"
    "94.2 MB (98.765.432 bytes)\n"
    "sha256\n"
    "0b9e8d7c6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa9988776655\n"
    "Sistema de coordenadas\n"
    "el mismo del original\n"
    "Lo que se midió en la salida\n"
    "epsg\n"
    "32719\n"
    "ancho px\n"
    "14526\n"
    "alto px\n"
    "14443\n"
    "bandas\n"
    "4\n"
    "Opciones aplicadas\n"
    "compresion\n"
    "DEFLATE\n"
    "tamano tesela\n"
    "512\n"
    "El original\n"
    "El corredor comprobó al terminar que la fecha de "
    "modificación del original no cambió; si hubiera "
    "cambiado, el trabajo\n"
    "habría fallado. La huella de arriba se calculó "
    "antes de empezar.\n",
    "sin-huellas": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · generado el 09/10/2026 "
    "12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "Terminado\n"
    "Programa\n"
    "gdal-raster · GDAL 3.12.4\n"
    "Conversión\n"
    "— a cog\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "09/10/2026 12:26:00\n"
    "Terminó\n"
    "09/10/2026 12:28:00\n"
    "Verificado\n"
    "09/10/2026 12:28:00\n"
    "Duración\n"
    "120.0 s\n"
    "Lo que entró\n"
    "Archivo\n"
    "—\n"
    "Tamaño\n"
    "—\n"
    "sha256\n"
    "no calculado\n"
    "Formato leído\n"
    "—\n"
    "Sistema de coordenadas\n"
    "no declarado\n"
    "Lo que salió\n"
    "Archivo\n"
    "orto_bhp.cog.tif\n"
    "Tamaño\n"
    "94.2 MB (98.765.432 bytes)\n"
    "sha256\n"
    "no calculado\n"
    "Sistema de coordenadas\n"
    "el mismo del original\n"
    "Lo que se midió en la salida\n"
    "epsg\n"
    "32719\n"
    "ancho px\n"
    "14526\n"
    "alto px\n"
    "14443\n"
    "bandas\n"
    "4\n"
    "Opciones aplicadas\n"
    "compresion\n"
    "DEFLATE\n"
    "tamano tesela\n"
    "512\n"
    "El original\n"
    "El corredor comprobó al terminar que la fecha de modificación del original no "
    "cambió; si hubiera cambiado, el trabajo\n"
    "habría fallado. La huella de arriba se calculó antes de empezar.\n",
    "tamanos-de-todas-las-magnitudes": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · generado "
    "el 09/10/2026 12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "Terminado\n"
    "Programa\n"
    "gdal-raster · GDAL 3.12.4\n"
    "Conversión\n"
    "geotiff a cog\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "09/10/2026 12:26:00\n"
    "Terminó\n"
    "09/10/2026 12:28:00\n"
    "Verificado\n"
    "09/10/2026 12:28:00\n"
    "Duración\n"
    "120.0 s\n"
    "Lo que entró\n"
    "Archivo\n"
    "orto_bhp.tif\n"
    "Tamaño\n"
    "512 B (512 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Formato leído\n"
    "geotiff (confianza: firma)\n"
    "Sistema de coordenadas\n"
    "EPSG:32719 (declarado por: incrustado)\n"
    "Lo que salió\n"
    "Archivo\n"
    "orto_bhp.cog.tif\n"
    "Tamaño\n"
    "2.0 KB (2.048 bytes)\n"
    "sha256\n"
    "0b9e8d7c6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa9988776655\n"
    "Sistema de coordenadas\n"
    "el mismo del original\n"
    "Lo que se midió en la salida\n"
    "epsg\n"
    "32719\n"
    "ancho px\n"
    "14526\n"
    "alto px\n"
    "14443\n"
    "bandas\n"
    "4\n"
    "Opciones aplicadas\n"
    "compresion\n"
    "DEFLATE\n"
    "tamano tesela\n"
    "512\n"
    "El original\n"
    "El corredor comprobó al terminar que la fecha de "
    "modificación del original no cambió; si hubiera cambiado, "
    "el trabajo\n"
    "habría fallado. La huella de arriba se calculó antes de "
    "empezar.\n",
    "terabytes": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · generado el 09/10/2026 12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "Terminado\n"
    "Programa\n"
    "gdal-raster · GDAL 3.12.4\n"
    "Conversión\n"
    "geotiff a cog\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "09/10/2026 12:26:00\n"
    "Terminó\n"
    "09/10/2026 12:28:00\n"
    "Verificado\n"
    "09/10/2026 12:28:00\n"
    "Duración\n"
    "120.0 s\n"
    "Lo que entró\n"
    "Archivo\n"
    "orto_bhp.tif\n"
    "Tamaño\n"
    "3.0 TB (3.298.534.883.328 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Formato leído\n"
    "geotiff (confianza: firma)\n"
    "Sistema de coordenadas\n"
    "EPSG:32719 (declarado por: incrustado)\n"
    "Lo que salió\n"
    "Archivo\n"
    "orto_bhp.cog.tif\n"
    "Tamaño\n"
    "5.120.0 TB (5.629.499.534.213.120 bytes)\n"
    "sha256\n"
    "0b9e8d7c6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa9988776655\n"
    "Sistema de coordenadas\n"
    "el mismo del original\n"
    "Lo que se midió en la salida\n"
    "epsg\n"
    "32719\n"
    "ancho px\n"
    "14526\n"
    "alto px\n"
    "14443\n"
    "bandas\n"
    "4\n"
    "Opciones aplicadas\n"
    "compresion\n"
    "DEFLATE\n"
    "tamano tesela\n"
    "512\n"
    "El original\n"
    "El corredor comprobó al terminar que la fecha de modificación del original no "
    "cambió; si hubiera cambiado, el trabajo\n"
    "habría fallado. La huella de arriba se calculó antes de empezar.\n",
    "una-sola-entrada-no-se-lista": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · generado el "
    "09/10/2026 12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "Terminado\n"
    "Programa\n"
    "gdal-raster · GDAL 3.12.4\n"
    "Conversión\n"
    "geotiff a cog\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "09/10/2026 12:26:00\n"
    "Terminó\n"
    "09/10/2026 12:28:00\n"
    "Verificado\n"
    "09/10/2026 12:28:00\n"
    "Duración\n"
    "120.0 s\n"
    "Lo que entró\n"
    "Archivo\n"
    "orto_bhp.tif\n"
    "Tamaño\n"
    "117.7 MB (123.456.789 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Formato leído\n"
    "geotiff (confianza: firma)\n"
    "Sistema de coordenadas\n"
    "EPSG:32719 (declarado por: incrustado)\n"
    "Lo que salió\n"
    "Archivo\n"
    "orto_bhp.cog.tif\n"
    "Tamaño\n"
    "94.2 MB (98.765.432 bytes)\n"
    "sha256\n"
    "0b9e8d7c6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa9988776655\n"
    "Sistema de coordenadas\n"
    "el mismo del original\n"
    "Lo que se midió en la salida\n"
    "epsg\n"
    "32719\n"
    "ancho px\n"
    "14526\n"
    "alto px\n"
    "14443\n"
    "bandas\n"
    "4\n"
    "Opciones aplicadas\n"
    "compresion\n"
    "DEFLATE\n"
    "tamano tesela\n"
    "512\n"
    "El original\n"
    "El corredor comprobó al terminar que la fecha de "
    "modificación del original no cambió; si hubiera cambiado, el "
    "trabajo\n"
    "habría fallado. La huella de arriba se calculó antes de "
    "empezar.\n",
    "verificacion-anidada-y-larga": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · generado el "
    "09/10/2026 12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "Terminado\n"
    "Programa\n"
    "gdal-raster · GDAL 3.12.4\n"
    "Conversión\n"
    "geotiff a cog\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "09/10/2026 12:26:00\n"
    "Terminó\n"
    "09/10/2026 12:28:00\n"
    "Verificado\n"
    "09/10/2026 12:28:00\n"
    "Duración\n"
    "120.0 s\n"
    "Lo que entró\n"
    "Archivo\n"
    "orto_bhp.tif\n"
    "Tamaño\n"
    "117.7 MB (123.456.789 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Formato leído\n"
    "geotiff (confianza: firma)\n"
    "Sistema de coordenadas\n"
    "EPSG:32719 (declarado por: incrustado)\n"
    "Lo que salió\n"
    "Archivo\n"
    "orto_bhp.cog.tif\n"
    "Tamaño\n"
    "94.2 MB (98.765.432 bytes)\n"
    "sha256\n"
    "0b9e8d7c6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa9988776655\n"
    "Sistema de coordenadas\n"
    "el mismo del original\n"
    "Lo que se midió en la salida\n"
    "dimensiones · ancho px\n"
    "100\n"
    "dimensiones · alto px\n"
    "80\n"
    "cuenta\n"
    "0, 1, 2, 3, 4, 5, 6, 7, 8, 9 (+15 más)\n"
    "tupla\n"
    "1, 2\n"
    "texto largo\n"
    "palabra palabra palabra palabra palabra palabra palabra "
    "palabra palabra palabra\n"
    "nulo\n"
    "None\n"
    "bandas\n"
    "3\n"
    "Opciones aplicadas\n"
    "compresion\n"
    "DEFLATE\n"
    "tamano tesela\n"
    "512\n"
    "El original\n"
    "El corredor comprobó al terminar que la fecha de "
    "modificación del original no cambió; si hubiera cambiado, el "
    "trabajo\n"
    "habría fallado. La huella de arriba se calculó antes de "
    "empezar.\n",
    "verificacion-de-muchas-filas": "Informe de verificación\n"
    "Trabajo 12345678-1234-5678-1234-567812345678 · generado el "
    "09/10/2026 12:30:00\n"
    "Resumen\n"
    "Estado\n"
    "Terminado\n"
    "Programa\n"
    "gdal-raster · GDAL 3.12.4\n"
    "Conversión\n"
    "geotiff a cog\n"
    "En cola\n"
    "09/10/2026 12:25:00\n"
    "Empezó\n"
    "09/10/2026 12:26:00\n"
    "Terminó\n"
    "09/10/2026 12:28:00\n"
    "Verificado\n"
    "09/10/2026 12:28:00\n"
    "Duración\n"
    "120.0 s\n"
    "Lo que entró\n"
    "Archivo\n"
    "orto_bhp.tif\n"
    "Tamaño\n"
    "117.7 MB (123.456.789 bytes)\n"
    "sha256\n"
    "a3f1c9d2e47b05861f2ac3d4e5b60718293a4b5c6d7e8f9012a3b4c5d6e7f801\n"
    "Formato leído\n"
    "geotiff (confianza: firma)\n"
    "Sistema de coordenadas\n"
    "EPSG:32719 (declarado por: incrustado)\n"
    "Lo que salió\n"
    "Archivo\n"
    "orto_bhp.cog.tif\n"
    "Tamaño\n"
    "94.2 MB (98.765.432 bytes)\n"
    "sha256\n"
    "0b9e8d7c6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa9988776655\n"
    "Sistema de coordenadas\n"
    "el mismo del original\n"
    "Lo que se midió en la salida\n"
    "medida 0\n"
    "0\n"
    "medida 1\n"
    "1\n"
    "medida 2\n"
    "2\n"
    "medida 3\n"
    "3\n"
    "medida 4\n"
    "4\n"
    "medida 5\n"
    "5\n"
    "medida 6\n"
    "6\n"
    "medida 7\n"
    "7\n"
    "medida 8\n"
    "8\n"
    "medida 9\n"
    "9\n"
    "medida 10\n"
    "10\n"
    "medida 11\n"
    "11\n"
    "medida 12\n"
    "12\n"
    "medida 13\n"
    "13\n"
    "medida 14\n"
    "14\n"
    "medida 15\n"
    "15\n"
    "medida 16\n"
    "16\n"
    "medida 17\n"
    "17\n"
    "\n"
    "medida 18\n"
    "18\n"
    "medida 19\n"
    "19\n"
    "medida 20\n"
    "20\n"
    "medida 21\n"
    "21\n"
    "medida 22\n"
    "22\n"
    "medida 23\n"
    "23\n"
    "medida 24\n"
    "24\n"
    "medida 25\n"
    "25\n"
    "medida 26\n"
    "26\n"
    "medida 27\n"
    "27\n"
    "medida 28\n"
    "28\n"
    "medida 29\n"
    "29\n"
    "medida 30\n"
    "30\n"
    "medida 31\n"
    "31\n"
    "medida 32\n"
    "32\n"
    "medida 33\n"
    "33\n"
    "medida 34\n"
    "34\n"
    "medida 35\n"
    "35\n"
    "medida 36\n"
    "36\n"
    "medida 37\n"
    "37\n"
    "medida 38\n"
    "38\n"
    "medida 39\n"
    "39\n"
    "Opciones aplicadas\n"
    "compresion\n"
    "DEFLATE\n"
    "tamano tesela\n"
    "512\n"
    "El original\n"
    "El corredor comprobó al terminar que la fecha de "
    "modificación del original no cambió; si hubiera cambiado, el "
    "trabajo\n"
    "habría fallado. La huella de arriba se calculó antes de "
    "empezar.\n",
}


@pytest.mark.parametrize("caso", _casos())
def test_el_texto_del_informe_no_cambia(caso, monkeypatch):
    assert _texto(caso, monkeypatch) == ESPERADO[caso]


def test_las_secciones_salen_en_el_mismo_orden(monkeypatch):
    texto = _texto("con-avisos-y-varias-entradas", monkeypatch)
    secciones = [
        "Informe de verificación",
        "Resumen",
        "Lo que entró",
        "Lo que salió",
        "Lo que se midió en la salida",
        "Opciones aplicadas",
        "Avisos durante el trabajo",
        "El original",
    ]
    posiciones = [texto.index(s) for s in secciones]
    assert posiciones == sorted(posiciones)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Defecto hallado al caracterizar (F11.8): `informe.construir` filtra los eventos por "
        "`level__in=('warning', 'error')`, pero `JobEvent.AVISO` vale `'warn'`, así que los avisos "
        "reales de la bitácora (los que escribe el corredor) nunca salen en el informe; solo "
        "salen los errores. `test_informe.py::test_los_avisos_del_trabajo_salen` pasa porque crea "
        "el evento con el nivel inventado `'warning'`. No se arregla en el refactor."
    ),
)
def test_un_aviso_real_de_la_bitacora_sale_en_el_informe(monkeypatch):
    class Reloj:
        @staticmethod
        def now():
            return AHORA

        localtime = staticmethod(informe.timezone.localtime)

    monkeypatch.setattr(informe, "timezone", Reloj)
    job = _crear("hecho-geoespacial")
    job.registrar("El archivo no declara sistema de referencia.", nivel=JobEvent.AVISO)
    lector = pypdf.PdfReader(io.BytesIO(informe.construir(job)))
    texto = "\n".join(p.extract_text() or "" for p in lector.pages)
    assert "El archivo no declara sistema de referencia." in texto
