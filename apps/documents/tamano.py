"""Recortar los márgenes de un PDF y cambiar el tamaño de sus páginas.

Tres cosas distintas que se piden juntas porque salen del mismo problema —«este plano no entra
en mi papel»— y que no se parecen:

- **Recortar al contenido**: se mira lo que hay dibujado (con PDFium, que es quien lo dibuja) y
  se deja la hoja del tamaño de eso más un margen. Sirve para quitar el blanco de un plano
  exportado en una hoja mucho mayor.
- **Recortar a mano**: se quitan tantos milímetros de cada lado.
- **Cambiar el tamaño**: el contenido se escala para que quepa en la hoja pedida, sin
  deformarse y centrado. Una lámina apaisada sigue apaisada.

## Qué no es

Recortar **no es borrar**: reduce lo que se ve, pero el contenido que quedó fuera sigue dentro
del archivo. Para quitar algo de verdad hace falta *redactar* (F14.8), y la pantalla lo dice.

## La página girada

Todo se mide en lo que se **ve**. Una página con `/Rotate 90` tiene el ancho y el alto
cambiados respecto de su caja, y un margen «de arriba» es el de arriba de lo que el lector
muestra; `_a_caja` hace esa cuenta.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apps.formats import pdf as _pdf_lectura

from .composicion import ComposicionInvalida
from .marcas import GIROS, MM_POR_PUNTO

#: Tamaños que se ofrecen, en puntos (vertical). Los de la serie A por su definición en mm.
TAMANOS_MM = {
    "a0": (841.0, 1189.0),
    "a1": (594.0, 841.0),
    "a2": (420.0, 594.0),
    "a3": (297.0, 420.0),
    "a4": (210.0, 297.0),
    "carta": (215.9, 279.4),
    "oficio": (215.9, 330.2),
}

ETIQUETAS = {
    "a0": "A0 (841 × 1189 mm)",
    "a1": "A1 (594 × 841 mm)",
    "a2": "A2 (420 × 594 mm)",
    "a3": "A3 (297 × 420 mm)",
    "a4": "A4 (210 × 297 mm)",
    "carta": "Carta (216 × 279 mm)",
    "oficio": "Oficio (216 × 330 mm)",
}

#: Por debajo de este valor de gris (0-255) un píxel cuenta como contenido. Un 250 deja fuera el
#: blanco casi blanco del papel escaneado y aun así coge una línea fina de plano.
UMBRAL_DE_BLANCO = 250

#: Un recorte automático no deja la hoja en menos de esto: una página con un punto perdido
#: quedaría de 1 mm y no sería una hoja.
MINIMO_PT = 36.0

MAXIMO_RECORTE_MM = 400.0


@dataclass(frozen=True)
class Resultado:
    paginas: int
    #: Páginas que cambiaron. Al recortar al contenido, una hoja en blanco queda como estaba.
    modificadas: int


def a_puntos(mm: float) -> float:
    return mm / MM_POR_PUNTO


def _abrir(origen: Path):
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        lector = PdfReader(str(origen))
    except (PyPdfError, OSError) as fallo:
        raise ComposicionInvalida(f"No se pudo abrir {origen.name}: {fallo}") from fallo
    if _pdf_lectura.pide_clave(lector):
        raise ComposicionInvalida(
            f"{origen.name} pide contraseña. Quítesela primero en «Proteger o desbloquear PDF»."
        )
    return lector


def _giro(pagina) -> int:
    try:
        valor = int(pagina.get("/Rotate", 0) or 0) % 360
    except (TypeError, ValueError):
        return 0
    return valor if valor in GIROS else 0


def _caja(pagina) -> tuple[float, float, float, float]:
    c = pagina.mediabox
    return float(c.left), float(c.bottom), float(c.right), float(c.top)


def _a_caja(pagina, vx0: float, vy0_arriba: float, vx1: float, vy1_arriba: float):
    """De un rectángulo en lo que se ve (x desde la izquierda, y desde arriba) a la caja de la
    página (origen abajo a la izquierda, sin girar). Devuelve `(izq, abajo, der, arriba)`."""
    izq, abajo, der, arriba = _caja(pagina)
    ancho, alto = der - izq, arriba - abajo
    giro = _giro(pagina)

    def punto(vx: float, vy: float) -> tuple[float, float]:
        if giro == 90:
            return vy, vx
        if giro == 180:
            return ancho - vx, vy
        if giro == 270:
            return ancho - vy, alto - vx
        return vx, alto - vy

    a = punto(vx0, vy0_arriba)
    b = punto(vx1, vy1_arriba)
    return (
        izq + min(a[0], b[0]),
        abajo + min(a[1], b[1]),
        izq + max(a[0], b[0]),
        abajo + max(a[1], b[1]),
    )


def _poner_caja(pagina, caja: tuple[float, float, float, float]) -> None:
    from pypdf.generic import RectangleObject

    rectangulo = RectangleObject(list(caja))
    pagina.mediabox = rectangulo
    pagina.cropbox = rectangulo
    # Las demás cajas no pueden quedar fuera de la nueva: algunos lectores usan la menor.
    for nombre in ("trimbox", "bleedbox", "artbox"):
        setattr(pagina, nombre, rectangulo)


def _escribir(escritor, destino: Path) -> None:
    with open(destino, "wb") as salida:
        escritor.write(salida)


def recortar_a_mano(
    origen: str | Path,
    destino: str | Path,
    *,
    arriba_mm: float = 0.0,
    derecha_mm: float = 0.0,
    abajo_mm: float = 0.0,
    izquierda_mm: float = 0.0,
) -> Resultado:
    """Quita esos milímetros de cada lado, **de lo que se ve**, en todas las páginas."""
    from pypdf import PdfWriter

    lados = (arriba_mm, derecha_mm, abajo_mm, izquierda_mm)
    if any(not 0 <= lado <= MAXIMO_RECORTE_MM for lado in lados) or not any(lados):
        raise ComposicionInvalida(
            f"Cada lado se recorta entre 0 y {int(MAXIMO_RECORTE_MM)} mm, y al menos uno no es 0."
        )

    origen, destino = Path(origen), Path(destino)
    escritor = PdfWriter(clone_from=_abrir(origen))
    arriba, derecha, abajo, izquierda = (a_puntos(m) for m in lados)

    for numero, pagina in enumerate(escritor.pages, start=1):
        izq, bajo, der, alto = _caja(pagina)
        ancho_v, alto_v = (
            (der - izq, alto - bajo) if _giro(pagina) in (0, 180) else (alto - bajo, der - izq)
        )
        if izquierda + derecha >= ancho_v - MINIMO_PT or arriba + abajo >= alto_v - MINIMO_PT:
            raise ComposicionInvalida(
                f"Esos márgenes dejan la página {numero} sin nada: mide "
                f"{ancho_v * MM_POR_PUNTO:.0f} × {alto_v * MM_POR_PUNTO:.0f} mm."
            )
        _poner_caja(pagina, _a_caja(pagina, izquierda, arriba, ancho_v - derecha, alto_v - abajo))

    _escribir(escritor, destino)
    return Resultado(paginas=len(escritor.pages), modificadas=len(escritor.pages))


def _contenido_visible(documento, numero: int) -> tuple[float, float, float, float] | None:
    """El rectángulo de lo dibujado, en puntos de lo que se ve (y desde arriba), o `None`.

    Se mide **dibujando la página con PDFium** a 2 px por punto y buscando lo que no es papel:
    lo que se ve es lo que cuenta, no lo que el PDF dice que hay (una hoja puede tener un
    dibujo blanco sobre blanco o un recuadro invisible que ocupa toda la caja).
    """
    pagina = documento[numero]
    try:
        escala = 2.0
        imagen = pagina.render(scale=escala).to_pil().convert("L")
    finally:
        pagina.close()
    contenido = imagen.point(lambda p: 255 if p < UMBRAL_DE_BLANCO else 0).getbbox()
    if contenido is None:
        return None
    x0, y0, x1, y1 = contenido
    return x0 / escala, y0 / escala, x1 / escala, y1 / escala


def recortar_al_contenido(
    origen: str | Path, destino: str | Path, *, margen_mm: float = 5.0
) -> Resultado:
    """Deja cada página del tamaño de lo que tiene dibujado, más un margen."""
    import pypdfium2
    from pypdf import PdfWriter

    if not 0 <= margen_mm <= 50:
        raise ComposicionInvalida("El margen va de 0 a 50 mm.")
    origen, destino = Path(origen), Path(destino)
    escritor = PdfWriter(clone_from=_abrir(origen))
    margen = a_puntos(margen_mm)

    try:
        documento = pypdfium2.PdfDocument(str(origen))
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo dibujar {origen.name}: {fallo}") from fallo

    modificadas = 0
    try:
        for indice, pagina in enumerate(escritor.pages):
            izq, bajo, der, alto = _caja(pagina)
            ancho_v, alto_v = (
                (der - izq, alto - bajo) if _giro(pagina) in (0, 180) else (alto - bajo, der - izq)
            )
            visto = _contenido_visible(documento, indice)
            if visto is None:
                continue  # una hoja en blanco se queda como estaba
            x0 = max(0.0, visto[0] - margen)
            y0 = max(0.0, visto[1] - margen)
            x1 = min(ancho_v, visto[2] + margen)
            y1 = min(alto_v, visto[3] + margen)
            if x1 - x0 < MINIMO_PT or y1 - y0 < MINIMO_PT:
                continue
            _poner_caja(pagina, _a_caja(pagina, x0, y0, x1, y1))
            modificadas += 1
    finally:
        documento.close()

    _escribir(escritor, destino)
    return Resultado(paginas=len(escritor.pages), modificadas=modificadas)


def cambiar_tamano(origen: str | Path, destino: str | Path, tamano: str) -> Resultado:
    """Pone cada página en una hoja del tamaño pedido, escalando el contenido sin deformarlo.

    La orientación se conserva: una lámina apaisada sale en la hoja apaisada.
    """
    from pypdf import PdfWriter, Transformation
    from pypdf.generic import RectangleObject

    if tamano not in TAMANOS_MM:
        raise ComposicionInvalida(f"«{tamano}» no es un tamaño de los que se ofrecen.")
    origen, destino = Path(origen), Path(destino)
    escritor = PdfWriter(clone_from=_abrir(origen))
    corto, largo = (a_puntos(m) for m in sorted(TAMANOS_MM[tamano]))

    for pagina in escritor.pages:
        izq, bajo, der, alto = _caja(pagina)
        ancho, altura = der - izq, alto - bajo
        # En lo que se ve: con giro de 90 o 270 el ancho visible es la altura de la caja.
        visible_ancho, visible_alto = (
            (ancho, altura) if _giro(pagina) in (0, 180) else (altura, ancho)
        )
        horizontal = visible_ancho > visible_alto
        destino_ancho, destino_alto = (largo, corto) if horizontal else (corto, largo)

        # Se trabaja en el espacio de la caja (sin girar): el destino se expresa en él.
        if _giro(pagina) in (90, 270):
            caja_ancho, caja_alto = destino_alto, destino_ancho
        else:
            caja_ancho, caja_alto = destino_ancho, destino_alto

        escala = min(caja_ancho / ancho, caja_alto / altura)
        sobra_x = caja_ancho - ancho * escala
        sobra_y = caja_alto - altura * escala
        pagina.add_transformation(
            Transformation()
            .translate(-izq, -bajo)
            .scale(escala, escala)
            .translate(sobra_x / 2, sobra_y / 2)
        )
        nueva = RectangleObject([0, 0, caja_ancho, caja_alto])
        for nombre in ("mediabox", "cropbox", "trimbox", "bleedbox", "artbox"):
            setattr(pagina, nombre, nueva)

    _escribir(escritor, destino)
    return Resultado(paginas=len(escritor.pages), modificadas=len(escritor.pages))
