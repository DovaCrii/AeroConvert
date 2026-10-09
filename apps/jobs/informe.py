"""El informe de verificación de un trabajo, en PDF, para que acompañe la entrega.

Una conversión entregada a un cliente se cree más si trae **qué entró, qué salió y quién lo
comprobó**: el nombre y la huella `sha256` del original y de la salida, el programa y su versión,
el sistema de coordenadas, lo que midió el lector que verificó el resultado y los avisos que hubo
por el camino. Aquí se arma con lo que el propio trabajo ya guardó; **no se recalcula nada** y no se
afirma nada que el trabajo no haya registrado.

## Lo que no dice

- No dice «sin pérdida» ni «correcto»: dice lo que se midió y con qué lector.
- Las opciones se muestran **sin** lo que pueda ser un secreto o un dato del cliente (contraseñas,
  términos de tachado, valores de una portada): se omiten por el nombre de la opción.
"""

from __future__ import annotations

import html
import io
from datetime import datetime

from django.utils import timezone

from .models import JobEvent

#: Opciones que no se imprimen nunca: llevan secretos o datos de quien pidió el trabajo.
OPCIONES_OCULTAS = (
    "contrasena",
    "clave",
    "secreto",
    "token",
    "terminos",
    "areas",
    "valores",
    "certificado",
    "pide_contrasena",
)

ESTADOS = {
    "done": "Terminado",
    "error": "Falló",
    "cancelled": "Cancelado",
    "queued": "En cola",
    "running": "En marcha",
}

MAXIMO_FILAS_DE_VERIFICACION = 40


def _texto(valor) -> str:
    return html.escape(str(valor)).encode("cp1252", "replace").decode("cp1252")


def _fecha(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return timezone.localtime(dt).strftime("%d/%m/%Y %H:%M:%S")


def _tamano(n: int) -> str:
    if not n:
        return "—"
    unidades = ("B", "KB", "MB", "GB", "TB")
    valor = float(n)
    for unidad in unidades:
        if valor < 1024 or unidad == unidades[-1]:
            cifra = f"{valor:,.0f}" if unidad == "B" else f"{valor:,.1f}"
            return f"{cifra.replace(',', '.')} {unidad} ({n:,} bytes)".replace(",", ".")
        valor /= 1024
    return str(n)


def _crs(autoridad: str, codigo: str, origen: str = "") -> str:
    if not codigo:
        return "no declarado"
    base = f"{autoridad or 'EPSG'}:{codigo}"
    return f"{base} (declarado por: {origen})" if origen else base


def _aplanar(valor, prefijo: str = "") -> list[tuple[str, str]]:
    """Pares (clave, texto) de un diccionario anidado, sin listas enormes."""
    filas: list[tuple[str, str]] = []
    if isinstance(valor, dict):
        for clave, hijo in valor.items():
            nombre = f"{prefijo}{clave}".replace("_", " ")
            if isinstance(hijo, dict):
                filas += _aplanar(hijo, f"{nombre} · ")
            elif isinstance(hijo, (list, tuple)):
                visibles = [str(x) for x in hijo[:10]]
                resto = f" (+{len(hijo) - 10} más)" if len(hijo) > 10 else ""
                filas.append((nombre, ", ".join(visibles) + resto))
            else:
                filas.append((nombre, str(hijo)))
    return filas


def _opciones_visibles(opciones: dict) -> list[tuple[str, str]]:
    visibles = {
        k: v
        for k, v in (opciones or {}).items()
        if not any(oculta in k.lower() for oculta in OPCIONES_OCULTAS)
        and isinstance(v, (str, int, float, bool))
    }
    return [(k.replace("_", " "), str(v)) for k, v in visibles.items()]


class _Hoja:
    """Los estilos del informe y la fábrica de sus tablas (reportlab, que se importa tarde)."""

    def __init__(self) -> None:
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

        estilos = getSampleStyleSheet()
        self.normal = ParagraphStyle(
            "n", parent=estilos["Normal"], fontName="Helvetica", fontSize=9, leading=12
        )
        self.etiqueta = ParagraphStyle(
            "e", parent=self.normal, textColor=colors.HexColor("#555555")
        )
        self.huella = ParagraphStyle(
            "h", parent=self.normal, fontName="Courier", fontSize=7.5, leading=10
        )
        self.titulo = ParagraphStyle(
            "t", parent=estilos["Title"], fontName="Helvetica-Bold", fontSize=18, alignment=0
        )
        self.seccion = ParagraphStyle(
            "s",
            parent=estilos["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            spaceBefore=12,
            spaceAfter=4,
        )

    def parrafo(self, texto: str, estilo):
        from reportlab.platypus import Paragraph

        return Paragraph(texto, estilo)

    def tabla(self, filas: list[tuple[str, str, bool]]):
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, Table, TableStyle

        datos = [
            [
                Paragraph(_texto(k), self.etiqueta),
                Paragraph(_texto(v), self.huella if mono else self.normal),
            ]
            for k, v, mono in filas
        ]
        t = Table(datos, colWidths=[44 * mm, 130 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        return t


def construir(job) -> bytes:
    """El PDF del informe de `job`, en memoria."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    hoja = _Hoja()

    historia = [
        hoja.parrafo("Informe de verificación", hoja.titulo),
        hoja.parrafo(
            f"Trabajo {job.pk} · generado el {_fecha(timezone.now())}",
            hoja.etiqueta,
        ),
    ]
    historia += _seccion_resumen(job, hoja)
    historia += _seccion_lo_que_entro(job, hoja)
    historia += _seccion_lo_que_salio(job, hoja)
    historia += _seccion_mediciones(job, hoja)
    historia += _seccion_opciones(job, hoja)
    historia += _seccion_avisos(job, hoja)
    historia += _seccion_el_original(job, hoja)

    memoria = io.BytesIO()
    documento = SimpleDocTemplate(
        memoria,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Informe de verificación {job.pk}",
        author="AeroConvert",
    )
    documento.build(historia)
    return memoria.getvalue()


def _seccion_resumen(job, hoja: _Hoja) -> list:
    duracion = ""
    if job.started_at and job.finished_at:
        duracion = f"{(job.finished_at - job.started_at).total_seconds():.1f} s"
    programa = job.herramienta or job.engine_id or "—"
    if job.engine_version:
        programa += f" · {job.engine_version}"
    return [
        hoja.parrafo("Resumen", hoja.seccion),
        hoja.tabla(
            [
                ("Estado", ESTADOS.get(job.status, job.status), False),
                ("Programa", programa, False),
                (
                    "Conversión",
                    f"{job.source_format_code or '—'} a {job.target_format_code}",
                    False,
                ),
                ("En cola", _fecha(job.queued_at), False),
                ("Empezó", _fecha(job.started_at), False),
                ("Terminó", _fecha(job.finished_at), False),
                ("Verificado", _fecha(job.verified_at), False),
                *([("Duración", duracion, False)] if duracion else []),
                *([("Motivo", f"{job.reason_code} — {job.reason_detail}".strip(" —"), False)]
                  if job.status != "done" and (job.reason_code or job.reason_detail) else []),
            ]
        ),
    ]  # fmt: skip


def _seccion_lo_que_entro(job, hoja: _Hoja) -> list:
    from reportlab.platypus import Spacer

    entradas = list(job.entradas.all())
    antes: list[tuple[str, str, bool]] = [
        ("Archivo", job.source_name or "—", False),
        ("Tamaño", _tamano(job.source_size_bytes), False),
        ("sha256", job.source_sha256 or "no calculado", True),
        (
            "Formato leído",
            f"{job.source_format_code or '—'}"
            + (
                f" (confianza: {job.source_format_confidence})"
                if job.source_format_confidence
                else ""
            ),
            False,
        ),
        (
            "Sistema de coordenadas",
            _crs(job.source_crs_authority, job.source_crs_code, job.source_crs_origin),
            False,
        ),
    ]
    historia = [hoja.parrafo("Lo que entró", hoja.seccion), hoja.tabla(antes)]
    if len(entradas) > 1:
        extra: list[tuple[str, str, bool]] = []
        for e in entradas:
            extra += [
                (f"Entrada {e.orden + 1}", f"{e.nombre} — {_tamano(e.bytes)}", False),
                ("sha256", e.sha256 or "no calculado", True),
            ]
        historia += [Spacer(1, 4), hoja.tabla(extra)]
    return historia


def _seccion_lo_que_salio(job, hoja: _Hoja) -> list:
    salida_nombre = (
        job.output_path.replace("\\", "/").rsplit("/", 1)[-1] if job.output_path else "—"
    )
    despues: list[tuple[str, str, bool]] = [
        ("Archivo", salida_nombre, False),
        ("Tamaño", _tamano(job.output_size_bytes), False),
        ("sha256", job.output_sha256 or "no calculado", True),
        (
            "Sistema de coordenadas",
            _crs(job.target_crs_authority, job.target_crs_code)
            if job.target_crs_code
            else "el mismo del original",
            False,
        ),
    ]
    return [hoja.parrafo("Lo que salió", hoja.seccion), hoja.tabla(despues)]


def _seccion_mediciones(job, hoja: _Hoja) -> list:
    """Lo que midió el lector que verificó."""
    filas = _aplanar(job.verification or {})[:MAXIMO_FILAS_DE_VERIFICACION]
    historia = [hoja.parrafo("Lo que se midió en la salida", hoja.seccion)]
    if filas:
        historia.append(hoja.tabla([(k, v, False) for k, v in filas]))
    else:
        historia.append(
            hoja.parrafo("Este trabajo no guardó mediciones de la salida.", hoja.normal)
        )
    return historia


def _seccion_opciones(job, hoja: _Hoja) -> list:
    opciones = _opciones_visibles(job.options)
    if not opciones:
        return []
    return [
        hoja.parrafo("Opciones aplicadas", hoja.seccion),
        hoja.tabla([(k, v, False) for k, v in opciones]),
    ]


def _seccion_avisos(job, hoja: _Hoja) -> list:
    avisos = list(
        job.eventos.filter(level__in=(JobEvent.AVISO, JobEvent.ERROR)).order_by("sequence")[:20]
    )
    if not avisos:
        return []
    return [
        hoja.parrafo("Avisos durante el trabajo", hoja.seccion),
        hoja.tabla([(a.level, a.message, False) for a in avisos]),
    ]


def _seccion_el_original(job, hoja: _Hoja) -> list:
    historia = [hoja.parrafo("El original", hoja.seccion)]
    if job.status == "done":
        historia.append(
            hoja.parrafo(
                "El corredor comprobó al terminar que la fecha de modificación del original "
                "no cambió; si hubiera cambiado, el trabajo habría fallado. La huella de arriba "
                "se calculó antes de empezar.",
                hoja.normal,
            )
        )
    elif job.reason_code == "original-modificado":
        historia.append(
            hoja.parrafo(
                "El original cambió mientras se trabajaba con él, y por eso el trabajo terminó "
                "en error y la salida no se entregó. El antes y el después (fecha, tamaño y "
                "huella) están en «Avisos durante el trabajo».",
                hoja.normal,
            )
        )
    else:
        historia.append(
            hoja.parrafo(
                "El trabajo no terminó: no hay entrega que acompañe este informe.", hoja.normal
            )
        )
    return historia
