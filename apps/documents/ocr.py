"""Reconocer el texto de un PDF escaneado, para que se pueda buscar y copiar.

## Por qué esto existía como promesa antes que como código

`a_markdown.py` le dice a la gente, desde el 2026-09-15, que un PDF escaneado «no tiene
texto: es una imagen de un texto» y que «para sacarlo hace falta reconocimiento óptico, que
todavía no está». Eso es una promesa escrita en pantalla, y llevaba seis días sin cumplirse.

## Se sondea, no se declara

Tesseract es un programa externo, como GDAL, como Office y como el motor de Access. **No
entra en `pyproject.toml` y no se da por hecho**: se busca, y si no está la herramienta sale
apagada con su motivo. La regla de la casa desde ECW: una capacidad ausente se apaga, no se
esconde — porque esconderla hace parecer que nunca existió.

## Qué entrega, y qué no

Entrega **el mismo PDF con una capa de texto invisible debajo de la imagen**: se ve idéntico,
y ahora se puede buscar, copiar y pasar a Markdown. No redibuja nada ni «mejora» el escaneo.

**El reconocimiento se equivoca.** Un plano con anotaciones a mano, un sello girado o un fax
de tercera generación dan texto con erratas, y eso no se puede evitar — lo que sí se puede es
no fingir lo contrario. La pantalla lo dice antes, y el resultado nunca sustituye al original.

## Y no se toca lo que ya tiene texto

Un PDF que ya trae su capa de texto no se pasa por OCR: tardaría minutos para producir una
versión peor que la que ya hay. Se mira primero y se dice.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - se invoca un binario fijo con argumentos construidos aquí
import tempfile
from dataclasses import dataclass
from pathlib import Path

from django.core.cache import cache

from .composicion import ComposicionInvalida

SEGUNDOS_DE_CACHE = 600
CLAVE_DE_CACHE = "documentos:ocr"

#: Los idiomas que se ofrecen, con su código de Tesseract.
IDIOMAS = {
    "spa": "Español",
    "eng": "Inglés",
    "spa+eng": "Español e inglés mezclados",
}

#: A cuántos puntos por pulgada se rasteriza cada página antes de reconocerla.
#:
#: 300 es el número que recomienda la documentación de Tesseract y no es negociable a la
#: baja: por debajo, las letras pequeñas de un cajetín se convierten en manchas y el
#: reconocimiento empieza a inventar. Por encima tarda el doble sin acertar más.
PPP = 300

#: Tope de páginas. Cada una tarda entre uno y varios segundos, así que un PDF de quinientas
#: bloquea el obrero durante un cuarto de hora. Es un tope para decirlo, no para impedirlo.
TOPE_PAGINAS = 100


@dataclass(frozen=True)
class Disponible:
    """Si esta máquina sabe reconocer texto. Con el motivo cuando no."""

    programa: str = ""
    idiomas: frozenset[str] = frozenset()
    motivo: str = ""
    sugerencia: str = ""

    def __bool__(self) -> bool:
        return bool(self.programa)

    def tiene(self, idioma: str) -> bool:
        """Un idioma compuesto —`spa+eng`— necesita **todos** sus trozos instalados."""
        return all(trozo in self.idiomas for trozo in idioma.split("+"))


def sondar(*, recordar: bool = True) -> Disponible:
    if recordar:
        guardado = cache.get(CLAVE_DE_CACHE)
        if guardado is not None:
            return guardado

    estado = _mirar()
    if recordar:
        cache.set(CLAVE_DE_CACHE, estado, SEGUNDOS_DE_CACHE)
    return estado


def _mirar() -> Disponible:
    programa = shutil.which("tesseract")
    if not programa:
        return Disponible(
            motivo="Esta máquina no tiene Tesseract, que es lo que reconoce el texto.",
            sugerencia=(
                "Es gratuito y de código abierto. En Ubuntu: «sudo apt install tesseract-ocr "
                "tesseract-ocr-spa». En Windows se instala desde el proyecto UB-Mannheim."
            ),
        )

    try:
        salida = subprocess.run(  # nosec B603 - ruta resuelta por `which`, sin shell
            [programa, "--list-langs"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as fallo:
        return Disponible(motivo=f"Tesseract está pero no responde: {fallo}")

    # La primera línea es un encabezado, no un idioma.
    idiomas = frozenset(linea.strip() for linea in salida.stdout.splitlines()[1:] if linea.strip())
    if not idiomas:
        return Disponible(
            motivo="Tesseract está instalado pero sin ningún idioma.",
            sugerencia="Falta el paquete de datos, por ejemplo «tesseract-ocr-spa».",
        )
    return Disponible(programa=programa, idiomas=idiomas)


def ya_tiene_texto(origen: str | Path) -> bool:
    """`True` si el PDF ya trae capa de texto y no hace falta reconocerlo.

    Pasarlo por OCR tardaría minutos para producir una versión **peor** que la que ya hay:
    el reconocimiento se equivoca y el texto incrustado no.
    """
    from pypdf import PdfReader

    try:
        lector = PdfReader(str(origen))
    except Exception:
        return False
    for hoja in lector.pages:
        try:
            if (hoja.extract_text() or "").strip():
                return True
        except Exception:  # nosec B112 - una hoja ilegible no prueba que el PDF no tenga texto
            continue
    return False


def reconocer(
    origen: str | Path,
    *,
    idioma: str = "spa",
    destino: Path | None = None,
) -> Path:
    """Escribe una copia con la capa de texto debajo de la imagen. Devuelve su ruta.

    ## Por qué se rasteriza y se junta, en vez de usar una herramienta que lo haga todo

    `ocrmypdf` hace esto mismo y mejor, y trae detrás una cadena de dependencias —Ghostscript,
    qpdf, pikepdf— que en el servidor compartido es media instalación más. Aquí ya están
    `pypdfium2` para rasterizar y `pypdf` para juntar: lo único que falta es Tesseract, que
    es el que hace el trabajo de verdad.

    Página a página **en un directorio temporal que se borra solo**, incluso si algo revienta
    a la mitad.
    """
    import pypdfium2
    from pypdf import PdfReader, PdfWriter

    estado = sondar()
    if not estado:
        raise ComposicionInvalida(estado.motivo)
    if idioma not in IDIOMAS:
        raise ComposicionInvalida(f"«{idioma}» no es uno de los idiomas que se ofrecen.")
    if not estado.tiene(idioma):
        raise ComposicionInvalida(
            f"Tesseract no tiene instalado el idioma «{IDIOMAS[idioma]}». "
            f"Los que hay: {', '.join(sorted(estado.idiomas))}."
        )

    origen = Path(origen)
    try:
        documento = pypdfium2.PdfDocument(str(origen))
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo abrir {origen.name}: {fallo}") from fallo

    total = len(documento)
    if total > TOPE_PAGINAS:
        documento.close()
        raise ComposicionInvalida(
            f"{origen.name} tiene {total} páginas y el tope son {TOPE_PAGINAS}. "
            "Cada página tarda unos segundos: pártelo antes con «Dividir PDF»."
        )

    destino = Path(destino) if destino else origen.with_name(f"{origen.stem}_con_texto.pdf")
    escritor = PdfWriter()

    try:
        with tempfile.TemporaryDirectory(prefix="aeroconvert-ocr-") as carpeta:
            temporal = Path(carpeta)
            for numero in range(total):
                imagen = documento[numero].render(scale=PPP / 72).to_pil()
                png = temporal / f"{numero}.png"
                try:
                    imagen.save(png)
                finally:
                    imagen.close()

                base = temporal / f"{numero}_ocr"
                resultado = subprocess.run(  # nosec B603 - binario resuelto por `which`
                    [estado.programa, str(png), str(base), "-l", idioma, "pdf"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                hecha = base.with_suffix(".pdf")
                if resultado.returncode != 0 or not hecha.exists():
                    raise ComposicionInvalida(
                        f"El reconocimiento falló en la página {numero + 1}: "
                        f"{resultado.stderr.strip()[:200] or 'sin mensaje'}"
                    )
                for hoja in PdfReader(str(hecha)).pages:
                    escritor.add_page(hoja)
    finally:
        documento.close()

    parcial = destino.with_name(destino.name + ".parcial")
    try:
        with parcial.open("wb") as salida:
            escritor.write(salida)
    except Exception as fallo:
        parcial.unlink(missing_ok=True)
        raise ComposicionInvalida(f"No se pudo escribir el PDF: {fallo}") from fallo

    parcial.replace(destino)
    return destino
