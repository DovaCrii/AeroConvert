"""Un PDF a PDF/A-2b, para archivar (F14.9). Con Ghostscript, sondeado y ejecutado aparte (D1).

## Qué se promete, y qué no

PDF/A es un PDF **que se basta a sí mismo** dentro de veinte años: las fuentes van incrustadas, el
color está definido por un perfil (sRGB) y los metadatos dicen qué norma cumple. Ghostscript lo
escribe; **otro lector lo comprueba**:

- **pikepdf** (que no escribió el archivo) mira que la identificación diga PDF/A-2B, que esté la
  intención de salida con su perfil ICC, y que **todas** las fuentes vayan incrustadas.
- **veraPDF**, si está en la máquina, valida la conformidad entera. **Sin veraPDF no se afirma que
  el archivo sea conforme**: el recibo dice «PDF/A-2b escrito; conformidad sin validar», que es lo
  que se sabe. Es la regla del plan para esta fila.

## Por qué el perfil se crea aquí y no se busca

Ghostscript necesita un archivo ICC para la intención de salida, y su ubicación cambia con cada
instalación (en la de QGIS no viene suelto). Pillow crea un sRGB estándar en memoria: el mismo en
todas las máquinas, sin buscar nada. Se escribe en una carpeta de trabajo propia junto al parcial
y se borra al terminar, también si falla.

## Seguridad

`-dSAFER` y `--permit-file-read` solo de esa carpeta: el documento es de fuera, y PostScript es un
lenguaje con acceso a archivos.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - Ghostscript y veraPDF se lanzan con lista de argumentos
from dataclasses import dataclass
from pathlib import Path

from .composicion import ComposicionInvalida

SEGUNDOS_DE_CACHE = 600
CLAVE_DE_CACHE = "documentos:ghostscript"

#: Ghostscript con un documento de 300 páginas con imágenes tarda; esto es holgado.
TIEMPO_MAXIMO_S = 600

#: Cómo se llama el programa en cada sistema.
_NOMBRES = ("gs", "gswin64c", "gswin32c")


@dataclass(frozen=True)
class Disponible:
    programa: str = ""
    motivo: str = ""
    sugerencia: str = ""

    def __bool__(self) -> bool:
        return bool(self.programa)


def sondar(*, recordar: bool = True) -> Disponible:
    """Dónde está Ghostscript. Configuración, PATH y la carpeta de GDAL (QGIS lo trae al lado)."""
    from django.conf import settings
    from django.core.cache import cache

    if recordar:
        guardado = cache.get(CLAVE_DE_CACHE)
        if guardado is not None:
            return guardado
    candidatos = []
    configurado = (getattr(settings, "GHOSTSCRIPT", "") or "").strip().strip('"')
    if configurado:
        candidatos.append(Path(configurado))
    for nombre in _NOMBRES:
        encontrado = shutil.which(nombre)
        if encontrado:
            candidatos.append(Path(encontrado))
    carpeta_gdal = (getattr(settings, "GDAL_BIN", "") or "").strip().strip('"')
    if carpeta_gdal:
        candidatos += [Path(carpeta_gdal) / f"{n}.exe" for n in _NOMBRES[1:]]
    programa = next((str(c) for c in candidatos if c.is_file()), "")
    if programa:
        estado = Disponible(programa=programa)
    else:
        estado = Disponible(
            motivo="Esta máquina no tiene Ghostscript, que es lo que escribe el PDF/A.",
            sugerencia=(
                "En el servidor: sudo despliegue/instalar_faltantes.sh. En Windows lo trae QGIS."
            ),
        )
    if recordar:
        cache.set(CLAVE_DE_CACHE, estado, SEGUNDOS_DE_CACHE)
    return estado


def sondar_verapdf() -> str:
    """La ruta de veraPDF, o cadena vacía. Opcional: sin él no se afirma conformidad."""
    from django.conf import settings

    configurado = (getattr(settings, "VERAPDF", "") or "").strip().strip('"')
    if configurado and Path(configurado).is_file():
        return configurado
    return shutil.which("verapdf") or ""


_DEFINICION = """%!
/ICCProfile ({icc}) def
[/_objdef {{icc_PDFA}} /type /stream /OBJ pdfmark
[{{icc_PDFA}} << /N 3 >> /PUT pdfmark
[{{icc_PDFA}} ICCProfile (r) file /PUT pdfmark
[/_objdef {{OutputIntent_PDFA}} /type /dict /OBJ pdfmark
[{{OutputIntent_PDFA}} <<
  /Type /OutputIntent
  /S /GTS_PDFA1
  /DestOutputProfile {{icc_PDFA}}
  /OutputConditionIdentifier (sRGB)
>> /PUT pdfmark
[{{Catalog}} << /OutputIntents [ {{OutputIntent_PDFA}} ] >> /PUT pdfmark
"""


def plan(programa: str, origen: Path, destino: Path, trabajo: Path) -> list[str]:
    """El argv de Ghostscript. Separado para poder comprobarlo sin Ghostscript."""
    carpeta = str(trabajo.resolve()).replace("\\", "/")
    return [
        programa,
        "-dPDFA=2",
        "-dPDFACompatibilityPolicy=1",
        "-dBATCH",
        "-dNOPAUSE",
        "-dNOOUTERSAVE",
        "-dSAFER",
        f"--permit-file-read={carpeta}/",
        "-sColorConversionStrategy=RGB",
        "-sDEVICE=pdfwrite",
        f"-sOutputFile={destino}",
        str(trabajo / "PDFA_def.ps"),
        str(origen),
    ]


def convertir(origen: Path, destino: Path, programa: str, *, verapdf: str = "") -> dict:
    """Escribe `destino` en PDF/A-2b y lo comprueba con otro lector. Devuelve lo comprobado."""
    from PIL import ImageCms

    trabajo = destino.with_name(destino.name + ".pdfa")
    shutil.rmtree(trabajo, ignore_errors=True)
    trabajo.mkdir(parents=True)
    try:
        # La copia del original va a la carpeta de trabajo: Ghostscript solo puede leer de ahí.
        copia = trabajo / "entrada.pdf"
        shutil.copyfile(origen, copia)
        icc = trabajo / "srgb.icc"
        icc.write_bytes(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
        ruta_icc = str(icc.resolve()).replace("\\", "/").replace("(", "\\(").replace(")", "\\)")
        (trabajo / "PDFA_def.ps").write_text(_DEFINICION.format(icc=ruta_icc), encoding="latin-1")
        try:
            resultado = subprocess.run(  # nosec B603
                plan(programa, copia, destino, trabajo),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=TIEMPO_MAXIMO_S,
                check=False,
            )
        except subprocess.TimeoutExpired as fallo:
            destino.unlink(missing_ok=True)
            raise ComposicionInvalida(
                f"Ghostscript lleva {TIEMPO_MAXIMO_S} s sin terminar con {origen.name}."
            ) from fallo
        if not destino.is_file() or destino.stat().st_size == 0:
            queja = (resultado.stderr or resultado.stdout or "").strip().splitlines()
            destino.unlink(missing_ok=True)
            raise ComposicionInvalida(
                f"Ghostscript no escribió el PDF/A. {queja[-1][:300] if queja else ''}".strip()
            )
        comprobado = comprobar(destino)
        if comprobado["problemas"]:
            destino.unlink(missing_ok=True)
            raise ComposicionInvalida(
                "Ghostscript escribió un PDF que no cumple lo mínimo de PDF/A: "
                + "; ".join(comprobado["problemas"])
            )
        comprobado["conforme"] = validar_con_verapdf(destino, verapdf) if verapdf else None
        if comprobado["conforme"] is False:
            destino.unlink(missing_ok=True)
            raise ComposicionInvalida("veraPDF dice que el resultado no es PDF/A-2b conforme.")
        return comprobado
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)


def comprobar(ruta: Path) -> dict:
    """Lo mínimo de PDF/A-2b, mirado con **pikepdf** (que no escribió el archivo)."""
    import pikepdf

    problemas: list[str] = []
    sin_incrustar: set[str] = set()
    with pikepdf.open(ruta) as pdf:
        paginas = len(pdf.pages)
        meta = pdf.open_metadata()
        parte = str(meta.get("pdfaid:part", "") or "")
        conformidad = str(meta.get("pdfaid:conformance", "") or "").upper()
        if (parte, conformidad) != ("2", "B"):
            problemas.append(f"la identificación dice PDF/A-{parte or '?'}{conformidad or '?'}")
        intenciones = pdf.Root.get("/OutputIntents") or []
        if not any(
            i.get("/S") == "/GTS_PDFA1" and i.get("/DestOutputProfile") is not None
            for i in intenciones
        ):
            problemas.append("no hay intención de salida PDF/A con su perfil de color")
        for pagina in pdf.pages:
            fuentes = (pagina.get("/Resources") or {}).get("/Font") or {}
            for _nombre, fuente in fuentes.items():
                if not _incrustada(fuente):
                    sin_incrustar.add(str(fuente.get("/BaseFont", "?")))
    if sin_incrustar:
        problemas.append("fuentes sin incrustar: " + ", ".join(sorted(sin_incrustar)))
    return {
        "paginas": paginas,
        "pdfa": f"{parte}{conformidad}",
        "problemas": problemas,
        "fuentes_sin_incrustar": sorted(sin_incrustar),
    }


def _incrustada(fuente) -> bool:
    if fuente.get("/Subtype") == "/Type3":
        return True  # se dibuja con el propio PDF
    descendientes = fuente.get("/DescendantFonts")
    if descendientes:
        return all(_incrustada(d) for d in descendientes)
    descriptor = fuente.get("/FontDescriptor")
    if descriptor is None:
        return False
    return any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3"))


def validar_con_verapdf(ruta: Path, verapdf: str) -> bool | None:
    """`True` o `False` según veraPDF; `None` si no se pudo preguntar (y entonces no se afirma)."""
    try:
        resultado = subprocess.run(  # nosec B603
            [verapdf, "--flavour", "2b", "--format", "text", str(ruta)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    salida = resultado.stdout or ""
    if "PASS" in salida:
        return True
    if "FAIL" in salida:
        return False
    return None
