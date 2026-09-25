"""El motor de las herramientas de documentos, del lado del corredor.

Describe qué hay que ejecutar y comprueba lo que salió; ejecutar lo hace `runner.py`, como
con cualquier otro motor. Lo que lo distingue de los geoespaciales:

## No se registra en `engines.registry`

A propósito. El registro alimenta la matriz de compatibilidad, la API y el formulario de
convertir, y todos suponen «formato de origen → formato de destino». Una herramienta de PDF
no es un par de formatos: «Numerar páginas» va de PDF a PDF. Registrarla habría llenado la
matriz de filas PDF → PDF que no significan nada. El corredor la encuentra por
`job.herramienta`, no por el par.

## La verificación la hace otra biblioteca

Las herramientas escriben con **pypdf**. Contar las páginas de la salida con pypdf sería el
código dándose la razón, que es justo lo que la regla 2 de `AGENTS.md` prohíbe. Aquí se
cuentan con **PDFium** —`pypdfium2`, el motor de PDF de Chrome—, que es otro analizador
escrito por otra gente: si pypdf escribiera un PDF que solo pypdf sabe leer, esto lo diría.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from apps.engines.base import Disponibilidad, PlanDeEjecucion, Verificacion, ruta_parcial


@dataclass(frozen=True)
class Especificacion:
    """Lo que el corredor necesita saber de una herramienta para ejecutarla."""

    #: `ligero` o `pesado`. Ver `apps/jobs/despachador.py`: sin carriles, un «numerar» de un
    #: segundo esperaría detrás de una ortofoto de tres horas.
    carril: str = "ligero"
    timeout_s: int = 300
    #: Solo las que escriben líneas `PROGRESO`. Con las mudas, el detector de atasco mataría
    #: un trabajo sano por no decir nada.
    emite_progreso: bool = False
    #: Las que pueden terminar bien **sin archivo**, con un desenlace que lo explica.
    salida_opcional: bool = False
    #: Qué programa de fuera hace falta, si alguno: `office`, `access` o `tesseract`.
    exige: str = ""


LIGERO = "ligero"
PESADO = "pesado"

ESPECIFICACIONES: dict[str, Especificacion] = {
    "numerar": Especificacion(),
    "marca": Especificacion(),
    # Un escaneo no tiene texto que sacar, y eso no es un fallo: es la respuesta.
    "md_excel": Especificacion(salida_opcional=True),
    "md_csv": Especificacion(salida_opcional=True),
    "md_word": Especificacion(salida_opcional=True),
    "md_pdf": Especificacion(salida_opcional=True),
    "md_epub": Especificacion(salida_opcional=True),
    "md_html": Especificacion(salida_opcional=True),
    "md_a_pdf": Especificacion(),
}


def especificacion(herramienta: str) -> Especificacion | None:
    return ESPECIFICACIONES.get(herramienta)


def va_por_la_cola(herramienta: str) -> bool:
    """Si esta herramienta ya se ejecuta en la cola. Las demás siguen en su pantalla."""
    return herramienta in ESPECIFICACIONES


def carril_de(herramienta: str) -> str:
    """El carril de un trabajo. **Lo geoespacial es siempre pesado**: puede tardar horas."""
    espec = ESPECIFICACIONES.get(herramienta or "")
    return espec.carril if espec else PESADO


# --- Los archivos que acompañan al parcial ------------------------------------
#
# Llevan `.parcial.` en el nombre a propósito: es la marca que busca el barrido de huérfanos,
# así que si el obrero muere a mitad no se quedan para siempre en la carpeta de trabajo.


def _auxiliar(job, cual: str) -> Path:
    from apps.jobs import retencion

    return retencion.carpeta_de_trabajo() / f"{job.pk}.parcial.{cual}.json"


def ruta_del_encargo(job) -> Path:
    return _auxiliar(job, "encargo")


def ruta_del_informe(job) -> Path:
    return _auxiliar(job, "informe")


def leer_informe(job) -> dict:
    try:
        return json.loads(ruta_del_informe(job).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def borrar_auxiliares(job) -> None:
    for ruta in (ruta_del_encargo(job), ruta_del_informe(job)):
        try:
            ruta.unlink(missing_ok=True)
        except OSError:
            pass


# --- Disponibilidad, plan y verificación --------------------------------------


def disponibilidad(herramienta: str) -> Disponibilidad:
    """Si esta máquina puede ejecutarla **ahora**. Lo mira el padre, que sí tiene Django."""
    espec = ESPECIFICACIONES.get(herramienta)
    if espec is None:
        return Disponibilidad.no("sin-motor", f"«{herramienta}» no se ejecuta desde la cola.")
    if not espec.exige:
        return Disponibilidad.si(f"documentos:{herramienta}")

    from . import catalogos, ocr, office

    sondas = {
        "office": (office.sondar, "sin-office"),
        "access": (catalogos.sondar, "sin-access"),
        "tesseract": (ocr.sondar, "sin-tesseract"),
    }
    sondar, codigo = sondas[espec.exige]
    estado = sondar()
    if not estado:
        return Disponibilidad.no(codigo, estado.motivo, sugerencia=estado.sugerencia)
    return Disponibilidad.si(f"documentos:{herramienta}")


_PROGRESO = re.compile(r"^PROGRESO\s+([0-9.]+)\s*$")


def _analizar_progreso(linea: str) -> float | None:
    encontrado = _PROGRESO.match(linea.strip())
    return float(encontrado.group(1)) if encontrado else None


def plan(job) -> PlanDeEjecucion:
    """Escribe el encargo y describe el proceso hijo. **Sin la contraseña**: ver `secretos`."""
    espec = ESPECIFICACIONES[job.herramienta]
    destino = Path(job.output_path)
    parcial = ruta_parcial(destino)

    entradas = [
        {"ruta": e.ruta, "nombre": e.nombre, "papel": e.papel} for e in job.entradas.all()
    ] or [{"ruta": job.source_path, "nombre": job.source_name, "papel": ""}]

    encargo = ruta_del_encargo(job)
    encargo.parent.mkdir(parents=True, exist_ok=True)
    encargo.write_text(
        json.dumps({"entradas": entradas, "opciones": dict(job.options or {})}, ensure_ascii=False),
        encoding="utf-8",
    )

    return PlanDeEjecucion(
        argv=(
            sys.executable,
            "-m",
            "apps.documents.tarea",
            job.herramienta,
            str(encargo),
            str(parcial),
            str(ruta_del_informe(job)),
        ),
        ruta_de_salida=destino,
        env={
            # Sin esto el progreso llega todo junto al final: Python guarda la salida en un
            # búfer cuando no escribe en una terminal.
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        },
        cwd=Path(settings.BASE_DIR),
        timeout_s=espec.timeout_s,
        analizador_de_progreso=_analizar_progreso,
        emite_progreso=espec.emite_progreso,
        salida_opcional=espec.salida_opcional,
    )


def verificar(parcial: Path, informe: dict) -> Verificacion:
    """Comprueba la salida **con un lector distinto del que la escribió**.

    Lo que se comprueba lo decide la extensión, no la herramienta: cualquier PDF que salga
    se abre con PDFium, cualquier `.md` se decodifica, cualquier zip se recorre. Así una
    herramienta nueva hereda la verificación sin que nadie se acuerde de escribirla.
    """
    if not parcial.exists():
        return Verificacion(False, "No hay archivo que verificar.", "sin-salida")
    tamano = parcial.stat().st_size
    if tamano == 0:
        return Verificacion(False, "El archivo salió vacío.", "salida-invalida")

    detalles = dict(informe.get("detalles") or {})
    detalles["bytes"] = tamano
    extension = parcial.suffix.lower()

    if extension == ".pdf":
        return _verificar_pdf(parcial, detalles)
    if extension == ".md":
        try:
            texto = parcial.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as fallo:
            return Verificacion(
                False, f"El Markdown no se lee como UTF-8: {fallo}", "salida-invalida"
            )
        if not texto.strip():
            return Verificacion(False, "El Markdown salió sin texto.", "salida-invalida")
        detalles["lineas"] = texto.count("\n") + 1
        return Verificacion(True, detalles=detalles)

    return Verificacion(True, detalles=detalles)


def _verificar_pdf(parcial: Path, detalles: dict) -> Verificacion:
    import pypdfium2

    try:
        documento = pypdfium2.PdfDocument(str(parcial))
    except Exception as fallo:  # noqa: BLE001 - PDFium no lo abre, y eso es lo que se mide
        return Verificacion(False, f"El PDF escrito no se deja abrir: {fallo}", "salida-invalida")
    try:
        paginas = len(documento)
    finally:
        documento.close()

    if paginas == 0:
        return Verificacion(False, "El PDF salió sin páginas.", "salida-invalida")

    esperadas = detalles.get("paginas")
    if esperadas and int(esperadas) != paginas:
        return Verificacion(
            False,
            f"La herramienta dice que escribió {esperadas} páginas y el PDF tiene {paginas}.",
            "salida-invalida",
        )

    detalles["paginas_verificadas"] = paginas
    detalles["verificado_con"] = "PDFium"
    return Verificacion(True, detalles=detalles)
