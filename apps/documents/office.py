"""Word, Excel y PowerPoint a PDF, con el Office que hay instalado.

## Por qué con Office y no con una biblioteca

Porque **un anexo de contrato que «se parece» al original no sirve**. Cualquier conversor
propio —o LibreOffice— reescribe el documento con sus propias métricas de fuente y su propio
motor de saltos: las tablas se descuadran, la paginación se corre, y el resultado es
plausible y distinto. Para un entregable que lleva firma, eso no vale.

Word exportando a PDF es el mismo motor que dibuja el documento en pantalla, así que lo que
sale es lo que se ve.

## El precio: solo en modo taller, y solo si hay Office

Esta herramienta **no existe en modo nube**, porque no hay Office en un servidor. Y en taller
aparece **apagada con su motivo** cuando no lo hay, igual que ECW — nunca desaparece. Ocultar
una capacidad ausente hace parecer que nunca existió.

## Siempre en un proceso hijo

Word se cuelga de verdad: un documento con una macro, un vínculo a una plantilla que ya no
está, un panel de recuperación esperando respuesta. Si se colgara dentro de Django se
llevaría el servidor. Aquí, como mucho, se mata al hijo y se dice qué pasó.

Ese es además el motivo de que el trabajo sucio lo haga **PowerShell**: ya habla COM, así que
no entra ninguna dependencia nueva y el aislamiento sale de regalo. Ver
`scripts/office_a_pdf.ps1`, donde están las trampas de cada programa.
"""

from __future__ import annotations

# La justificacion de lanzar un proceso esta en `convertir`, y la de que sea PowerShell en el
# docstring del modulo. El texto va aqui arriba y no detras del `nosec`: bandit lee lo que
# sigue al marcador como nombres de prueba y avisa de cada palabra.
import subprocess  # nosec B404
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

from .composicion import ComposicionInvalida

#: Que extension va a que programa. Los formatos viejos entran igual: un `.doc` de 2003 es
#: justamente el que nadie mas sabe leer bien, y Word lo abre sin pestanear.
PROGRAMAS = {
    ".doc": "word",
    ".docx": "word",
    ".docm": "word",
    ".rtf": "word",
    ".odt": "word",
    ".xls": "excel",
    ".xlsx": "excel",
    ".xlsm": "excel",
    ".ods": "excel",
    ".ppt": "powerpoint",
    ".pptx": "powerpoint",
    ".odp": "powerpoint",
}

#: Como se llama cada uno para quien lee la pantalla.
NOMBRES = {"word": "Word", "excel": "Excel", "powerpoint": "PowerPoint"}

#: El camino de vuelta. No es un programa: es Word abriendo un PDF.
PDF_A_WORD = "pdf-a-word"

#: Cuantas paginas se miran para decidir si el PDF trae texto o es un escaneo. Cinco: un
#: documento de texto lo demuestra en la primera, y recorrer quinientas para confirmarlo
#: costaria mas que la conversion entera.
PAGINAS_A_OLFATEAR = 5

#: Por debajo de esto se considera que no hay texto. No es cero porque un escaneo suele
#: traer una marca de agua o un pie del propio escaner -- veinte o treinta caracteres sueltos
#: que no son el documento.
MINIMO_DE_TEXTO = 80

#: Cuanto se le da a Office antes de darlo por colgado. Un informe de doscientas paginas con
#: imagenes tarda de verdad; cinco minutos es holgado y a la vez no deja una pestana girando
#: para siempre.
TIEMPO_MAXIMO_S = 300

#: Lo mismo que las sondas de GDAL: diez minutos. Preguntarle al registro es barato, pero
#: esto se consulta al pintar el indice de herramientas.
SEGUNDOS_DE_CACHE = 600

CLAVE_DE_CACHE = "documentos:office"


@dataclass(frozen=True)
class Disponible:
    """Qué programas de Office hay. Con el motivo cuando no hay ninguno."""

    programas: frozenset[str]
    motivo: str = ""
    sugerencia: str = ""

    def __bool__(self) -> bool:
        return bool(self.programas)

    def tiene(self, programa: str) -> bool:
        return programa in self.programas

    @property
    def extensiones(self) -> tuple[str, ...]:
        return tuple(sorted(ext for ext, prog in PROGRAMAS.items() if prog in self.programas))

    @property
    def nombres(self) -> tuple[str, ...]:
        return tuple(NOMBRES[p] for p in ("word", "excel", "powerpoint") if p in self.programas)


def _registrado(prog_id: str) -> bool:
    """¿Está ese servidor COM registrado en esta máquina?

    Se mira el **registro**, no se arranca el programa: lanzar Word para preguntarle si
    existe cuesta segundos y esto se consulta al pintar una página. Es la misma regla que
    `apps/engines/sondas.py`.
    """
    try:
        import winreg
    except ImportError:  # pragma: no cover -- no es Windows
        return False

    for raiz in (winreg.HKEY_CLASSES_ROOT,):
        try:
            with winreg.OpenKey(raiz, rf"{prog_id}\CurVer"):
                return True
        except OSError:
            continue
    return False


def sondar(*, recordar: bool = True) -> Disponible:
    """Qué hay instalado. Cacheado, como las demás sondas."""
    if recordar:
        guardado = cache.get(CLAVE_DE_CACHE)
        if guardado is not None:
            return guardado

    if getattr(settings, "MODO", "taller") != "taller":
        estado = Disponible(
            frozenset(),
            motivo="Esto solo funciona en modo taller.",
            sugerencia=(
                "La conversión la hace el Office instalado en el equipo, y en el servidor no "
                "hay ninguno."
            ),
        )
    else:
        encontrados = {
            programa
            for programa, prog_id in (
                ("word", "Word.Application"),
                ("excel", "Excel.Application"),
                ("powerpoint", "PowerPoint.Application"),
            )
            if _registrado(prog_id)
        }
        if encontrados:
            estado = Disponible(frozenset(encontrados))
        else:
            estado = Disponible(
                frozenset(),
                motivo="No hay Microsoft Office instalado en este equipo.",
                sugerencia=(
                    "Es lo que hace la conversión, y es a propósito: cualquier otra cosa "
                    "entrega un documento que se parece al original, y un anexo de contrato "
                    "que se parece no sirve."
                ),
            )

    if recordar:
        cache.set(CLAVE_DE_CACHE, estado, SEGUNDOS_DE_CACHE)
    return estado


def olvidar() -> None:
    """Vacía la caché de la sonda. La usan las pruebas."""
    cache.delete(CLAVE_DE_CACHE)


def programa_de(origen: str | Path) -> str:
    """Qué programa abre ese archivo, por su extensión."""
    sufijo = Path(origen).suffix.lower()
    programa = PROGRAMAS.get(sufijo)
    if not programa:
        raise ComposicionInvalida(
            f"«{sufijo or Path(origen).name}» no es un documento de Office de los que se "
            "convierten."
        )
    return programa


@dataclass(frozen=True)
class QueTraeElPdf:
    """Lo que hace falta saber **antes** de mandarle un PDF a Word."""

    paginas: int
    caracteres: int

    @property
    def es_un_escaneo(self) -> bool:
        return self.caracteres < MINIMO_DE_TEXTO


def mirar_pdf(origen: str | Path) -> QueTraeElPdf:
    """Cuántas páginas trae y cuánto texto de verdad hay dentro.

    **Es lo que decide si merece la pena convertirlo.** Un PDF escaneado no tiene texto: son
    fotos de un papel. Word lo «convierte» igual, devuelve un documento de medio mega y sale
    con código cero — y lo que hay dentro son las mismas fotos pegadas, sin una palabra
    editable. Medido sobre una bitácora escaneada de esta oficina: **cero caracteres**.

    Eso hay que decirlo antes, no después.
    """
    from apps.formats import pdf as lectura_pdf

    origen = Path(origen)
    try:
        cabecera = lectura_pdf.leer_cabecera(origen)
    except lectura_pdf.NoEsPdf as fallo:
        raise ComposicionInvalida(str(fallo)) from fallo

    if cabecera.cifrado:
        raise ComposicionInvalida(
            f"{origen.name} pide contraseña. Quítasela primero en «Proteger PDF»."
        )

    from pypdf import PdfReader

    lector = PdfReader(str(origen))
    caracteres = sum(_cuanto_texto(pagina) for pagina in lector.pages[:PAGINAS_A_OLFATEAR])
    return QueTraeElPdf(paginas=cabecera.cuantas, caracteres=caracteres)


def _cuanto_texto(pagina) -> int:
    """Caracteres de texto de una página. Cero si no se deja leer.

    Una página que revienta al extraer cuenta como **sin texto**, que es exactamente lo que
    se va a ver: si Word tampoco puede sacar letras de ahí, lo que devuelve es una imagen.
    """
    try:
        return len((pagina.extract_text() or "").strip())
    except Exception:  # pragma: no cover -- una pagina rota no impide decidir
        return 0


def plan(origen: Path, destino: Path, programa: str, *, ajustar_ancho: bool = False) -> list[str]:
    """El `argv` exacto, sin ejecutar nada.

    Separado para poder comprobarlo en una máquina sin Office, que es la misma idea que hace
    testeable toda la capa de motores: el plan se describe y otro lo ejecuta.
    """
    guion = Path(settings.BASE_DIR) / "scripts" / "office_convertir.ps1"
    argv = [
        "pwsh",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(guion),
        "-Origen",
        str(origen),
        "-Destino",
        str(destino),
        "-Programa",
        programa,
    ]
    if ajustar_ancho and programa == "excel":
        argv.append("-AjustarAncho")
    return argv


def a_word(
    origen: str | Path,
    destino: str | Path,
    *,
    tiempo_maximo_s: int = TIEMPO_MAXIMO_S,
    argv: list[str] | None = None,
) -> Path:
    """El camino de vuelta: un PDF a `.docx`, convertido por el propio Word.

    **Se comprueba antes que sea un PDF de verdad**, y no por pedantería: a Word le das un
    archivo de texto con la extensión cambiada y lo abre tan contento, lo guarda como `.docx`
    y sale con código cero. Probado. La extensión no es el formato, y aquí ya hay un lector
    de firmas para decirlo.
    """
    origen, destino = Path(origen), Path(destino)

    if not origen.is_file():
        raise ComposicionInvalida(f"No existe {origen.name}.")

    # Levanta si no es un PDF, o si pide contrasena. Se hace **aqui**, en Python, y no en el
    # guion: es donde ya sabemos leer firmas.
    mirar_pdf(origen)

    disponible = sondar()
    if not disponible.tiene("word"):
        raise ComposicionInvalida(
            f"Word no está disponible en este equipo. {disponible.motivo or ''}".strip()
        )

    orden = argv if argv is not None else plan(origen, destino, PDF_A_WORD)
    return _lanzar(orden, destino, "Word", tiempo_maximo_s)


def convertir(
    origen: str | Path,
    destino: str | Path,
    *,
    ajustar_ancho: bool = False,
    tiempo_maximo_s: int = TIEMPO_MAXIMO_S,
    argv: list[str] | None = None,
) -> Path:
    """Exporta el documento a PDF y devuelve la ruta escrita."""
    origen, destino = Path(origen), Path(destino)
    programa = programa_de(origen)

    disponible = sondar()
    if not disponible.tiene(programa):
        raise ComposicionInvalida(
            f"{NOMBRES[programa]} no está disponible en este equipo. "
            f"{disponible.motivo or ''}".strip()
        )

    if not origen.is_file():
        raise ComposicionInvalida(f"No existe {origen.name}.")

    orden = (
        argv if argv is not None else plan(origen, destino, programa, ajustar_ancho=ajustar_ancho)
    )
    return _lanzar(orden, destino, NOMBRES[programa], tiempo_maximo_s)


def _lanzar(orden: list[str], destino: Path, nombre: str, tiempo_maximo_s: int) -> Path:
    """Lanza el hijo y decide si salió bien. Lo comparten los dos sentidos."""

    try:
        # Lista y `shell=False`: la ruta la teclea una persona y trae tildes, espacios y
        # OneDrive. Una cadena la interpretaria el interprete de ordenes.
        resultado = subprocess.run(  # nosec B603
            orden,
            capture_output=True,
            text=True,
            # **UTF-8 explicito.** Con `text=True` a secas, Python decodifica con la pagina
            # de codigos de Windows -- cp1252 aqui -- mientras que pwsh escribe UTF-8, y un
            # Office en espanol devuelve «el documento pide una contraseÃ±a». El mensaje que
            # mas falta hace es justo el que sale ilegible.
            encoding="utf-8",
            errors="replace",
            timeout=tiempo_maximo_s,
            check=False,
        )
    except FileNotFoundError as fallo:
        raise ComposicionInvalida(
            "No se encontró PowerShell 7 (pwsh) para hablar con Office."
        ) from fallo
    except subprocess.TimeoutExpired as fallo:
        destino.unlink(missing_ok=True)
        raise ComposicionInvalida(
            f"{nombre} lleva {tiempo_maximo_s} segundos sin responder y se ha cerrado. Suele "
            "pasar cuando el documento pide algo al abrirse: una contraseña, una plantilla "
            "que ya no está, o una macro."
        ) from fallo

    # **El codigo de salida no es la prueba de que funciono.** Office devuelve 0 sin escribir
    # nada mas veces de las que parece, asi que lo que decide es que el archivo este.
    if not destino.exists():
        raise ComposicionInvalida(
            f"{nombre} no llegó a escribir el archivo. {_queja(resultado)}".strip()
        )
    if resultado.returncode != 0:
        destino.unlink(missing_ok=True)
        raise ComposicionInvalida(f"{nombre} falló al convertir. {_queja(resultado)}".strip())

    return destino


def _queja(resultado) -> str:
    """La última línea útil de lo que dijo PowerShell, acotada.

    Acotada porque un volcado de COM son varias pantallas de nombres de interfaz que no le
    dicen nada a nadie, y porque lo mismo se hace con el `stderr` de GDAL.
    """
    crudo = (resultado.stderr or resultado.stdout or "").strip()
    if not crudo:
        return ""
    linea = next((texto.strip() for texto in reversed(crudo.splitlines()) if texto.strip()), "")
    return linea[:300]
