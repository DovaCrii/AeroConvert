"""Redactar de verdad: tachar un texto o un área para que **ya no exista** en el archivo.

## Por qué no basta con dibujar un rectángulo negro

Es el error clásico: un rectángulo negro encima de un nombre lo tapa a la vista y deja el nombre
debajo, en el texto del PDF, donde se copia y se busca. Una redacción así se ha publicado más de
una vez con el nombre a un `Ctrl+C` de distancia.

## Cómo se hace aquí

Las páginas que llevan algo que tachar se **convierten en imagen**: PDFium dibuja la página con
los rectángulos negros puestos y esa imagen sustituye a la página. Del original no queda nada de
esa página —ni el texto, ni los trazos, ni las imágenes que había debajo—, porque el documento
resultante se escribe **nuevo** y solo con lo que se eligió llevar. Las páginas sin nada que tachar
pasan tal cual.

El precio, dicho en la pantalla: **las páginas redactadas ya no tienen texto buscable ni
seleccionable** (son una imagen), y pierden sus marcadores y anotaciones. Para recuperar la
búsqueda se puede pasar luego por «Reconocer texto (OCR)».

## Qué se tacha

- **Textos**: cada coincidencia (sin mayúsculas ni minúsculas) se tacha con el recuadro de sus
  letras, unas décimas de punto más grande. Un texto partido en dos renglones son dos recuadros.
- **Áreas**: rectángulos en milímetros, desde la esquina de arriba a la izquierda **de lo que se
  ve**, como se miden en una hoja.

Lo que se informa de vuelta lleva **cuántas veces** apareció cada término, nunca el término: eso
acaba en la base de datos y es justo lo que se está tapando.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .composicion import ComposicionInvalida
from .marcas import MM_POR_PUNTO

#: Resoluciones a las que se dibuja la página redactada. 200 ppp se lee bien y pesa poco; un
#: plano grande a 300 sería enorme.
RESOLUCIONES = {150: "Normal — la más ligera", 200: "Buena — lo habitual", 300: "Alta — pesa mucho"}

#: Holgura, en puntos, que se le da a cada recuadro de texto: que no asome el borde de una letra.
HOLGURA_PT = 1.5

#: Lado mayor, en píxeles, que se admite al dibujar una página redactada.
LADO_MAXIMO_PX = 14_000

MAXIMO_TERMINOS = 50
MAXIMO_LARGO_TERMINO = 120


class NadaQueRedactar(ComposicionInvalida):
    """Ningún término apareció y no se pidió ningún área. No es un fallo: es la respuesta."""

    codigo = "nada-que-redactar"


@dataclass(frozen=True)
class Area:
    pagina: int
    #: Milímetros desde la esquina de arriba a la izquierda de lo que se ve.
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class Resultado:
    paginas: int
    paginas_redactadas: tuple[int, ...]
    #: Cuántas coincidencias tuvo cada término, **en el orden en que se pidieron**. El término
    #: no vuelve: esto se guarda en la base y es justo lo que se tapa.
    coincidencias: tuple[int, ...]
    areas: int


def limpiar_terminos(terminos) -> list[str]:
    """Quita vacíos y repetidos, y rechaza lo que no sirve. Conserva el orden."""
    vistos: list[str] = []
    for termino in terminos or ():
        limpio = " ".join(str(termino).split())
        if not limpio or limpio.lower() in (v.lower() for v in vistos):
            continue
        if len(limpio) < 2:
            raise ComposicionInvalida("Un término de una sola letra tacharía medio documento.")
        if len(limpio) > MAXIMO_LARGO_TERMINO:
            raise ComposicionInvalida(f"Un término no puede pasar de {MAXIMO_LARGO_TERMINO}.")
        vistos.append(limpio)
    if len(vistos) > MAXIMO_TERMINOS:
        raise ComposicionInvalida(f"Son demasiados términos: el máximo es {MAXIMO_TERMINOS}.")
    return vistos


def _abrir_pypdf(ruta: Path):
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        lector = PdfReader(str(ruta))
    except (PyPdfError, OSError) as fallo:
        raise ComposicionInvalida(f"No se pudo abrir {ruta.name}: {fallo}") from fallo
    if lector.is_encrypted:
        raise ComposicionInvalida(
            f"{ruta.name} pide contraseña. Quítesela primero en «Proteger o desbloquear PDF»."
        )
    return lector


def _cajas_del_termino(texto_pagina, termino: str) -> list[tuple[float, float, float, float]]:
    """Los recuadros (izq, abajo, der, arriba) de cada coincidencia, uno por renglón."""
    # PDFium no pliega mayúsculas fuera del ASCII («PÉREZ» no casa con «Pérez»): se busca como se
    # escribió, en minúsculas y en mayúsculas, y se quitan los recuadros repetidos.
    variantes = list(dict.fromkeys([termino, termino.lower(), termino.upper()]))
    cajas: list[tuple[float, float, float, float]] = []
    vistas: set[tuple[int, int, int, int]] = set()
    for variante in variantes:
        for caja in _cajas_de_una_busqueda(texto_pagina, variante):
            huella = tuple(round(v) for v in caja)
            if huella not in vistas:
                vistas.add(huella)
                cajas.append(caja)
    return cajas


def _cajas_de_una_busqueda(texto_pagina, termino: str) -> list[tuple[float, float, float, float]]:
    buscador = texto_pagina.search(termino, match_case=False, match_whole_word=False)
    cajas: list[tuple[float, float, float, float]] = []
    while True:
        hallado = buscador.get_next()
        if hallado is None:
            break
        inicio, cuantos = hallado
        actual = None
        for i in range(inicio, inicio + cuantos):
            izq, abajo, der, arriba = texto_pagina.get_charbox(i, loose=True)
            if der <= izq and arriba <= abajo:
                continue  # un espacio o un salto: no ocupa sitio
            if actual is not None and _mismo_renglon(actual, (izq, abajo, der, arriba)):
                actual = (
                    min(actual[0], izq),
                    min(actual[1], abajo),
                    max(actual[2], der),
                    max(actual[3], arriba),
                )
            else:
                if actual is not None:
                    cajas.append(actual)
                actual = (izq, abajo, der, arriba)
        if actual is not None:
            cajas.append(actual)
    return cajas


def _mismo_renglon(a, b) -> bool:
    solape = min(a[3], b[3]) - max(a[1], b[1])
    return solape > 0.5 * min(a[3] - a[1], b[3] - b[1])


def _poner_rectangulo(pagina, caja: tuple[float, float, float, float]) -> None:
    """Un rectángulo negro **dentro de la página**, para que el dibujo lo lleve puesto."""
    import pypdfium2.raw as raw

    izq, abajo, der, arriba = caja
    rectangulo = raw.FPDFPageObj_CreateNewRect(izq, abajo, der - izq, arriba - abajo)
    raw.FPDFPageObj_SetFillColor(rectangulo, 0, 0, 0, 255)
    raw.FPDFPath_SetDrawMode(rectangulo, raw.FPDF_FILLMODE_ALTERNATE, False)
    raw.FPDFPage_InsertObject(pagina.raw, rectangulo)


def _area_a_caja(lector_pypdf, area: Area):
    """Del área en milímetros de lo que se ve a la caja de la página (con su giro)."""
    from .tamano import _a_caja

    pagina = lector_pypdf.pages[area.pagina - 1]
    return _a_caja(
        pagina,
        area.x0 / MM_POR_PUNTO,
        area.y0 / MM_POR_PUNTO,
        area.x1 / MM_POR_PUNTO,
        area.y1 / MM_POR_PUNTO,
    )


def redactar(
    origen: str | Path,
    destino: str | Path,
    *,
    terminos=(),
    areas: tuple[Area, ...] | list[Area] = (),
    ppp: int = 200,
    progreso: Callable[[float], None] | None = None,
) -> Resultado:
    """Escribe un documento nuevo con lo pedido tachado de verdad."""
    import pypdfium2
    from pypdf import PdfReader, PdfWriter

    origen, destino = Path(origen), Path(destino)
    terminos = limpiar_terminos(terminos)
    if ppp not in RESOLUCIONES:
        raise ComposicionInvalida(f"«{ppp}» no es una de las resoluciones que se ofrecen.")

    lector = _abrir_pypdf(origen)
    total = len(lector.pages)
    for area in areas:
        if not 1 <= area.pagina <= total:
            raise ComposicionInvalida(
                f"{origen.name} tiene {total} página(s): no existe la {area.pagina}."
            )
        if not (area.x1 > area.x0 and area.y1 > area.y0 and min(area.x0, area.y0) >= 0):
            raise ComposicionInvalida(f"El área de la página {area.pagina} no tiene tamaño.")

    try:
        documento = pypdfium2.PdfDocument(str(origen))
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo dibujar {origen.name}: {fallo}") from fallo

    coincidencias = [0] * len(terminos)
    por_pagina: dict[int, list[tuple[float, float, float, float]]] = {}
    for area in areas:
        por_pagina.setdefault(area.pagina, []).append(_area_a_caja(lector, area))

    imagenes: dict[int, bytes] = {}
    try:
        for indice in range(total):
            numero = indice + 1
            pagina = documento[indice]
            try:
                cajas = list(por_pagina.get(numero, ()))
                if terminos:
                    texto = pagina.get_textpage()
                    try:
                        for orden, termino in enumerate(terminos):
                            encontradas = _cajas_del_termino(texto, termino)
                            coincidencias[orden] += len(encontradas)
                            cajas.extend(encontradas)
                    finally:
                        texto.close()
                if not cajas:
                    continue

                for izq, abajo, der, arriba in cajas:
                    _poner_rectangulo(
                        pagina,
                        (
                            izq - HOLGURA_PT,
                            abajo - HOLGURA_PT,
                            der + HOLGURA_PT,
                            arriba + HOLGURA_PT,
                        ),
                    )
                import pypdfium2.raw as raw

                raw.FPDFPage_GenerateContent(pagina.raw)

                ancho_pt, alto_pt = pagina.get_size()
                escala = ppp / 72
                if max(ancho_pt, alto_pt) * escala > LADO_MAXIMO_PX:
                    raise ComposicionInvalida(
                        f"La página {numero} a {ppp} ppp saldría de más de {LADO_MAXIMO_PX} px "
                        "de lado. Baje la resolución."
                    )
                imagen = pagina.render(scale=escala).to_pil().convert("RGB")
                puesta = io.BytesIO()
                imagen.save(puesta, "PDF", resolution=ppp, quality=90)
                imagen.close()
                imagenes[numero] = puesta.getvalue()
            finally:
                pagina.close()
            if progreso is not None:
                progreso(numero / total)
    finally:
        documento.close()

    if not imagenes:
        raise NadaQueRedactar(
            "No hay nada que tachar: ningún término apareció y no se pidió ningún área."
        )

    escritor = PdfWriter()
    for numero, pagina in enumerate(lector.pages, start=1):
        if numero in imagenes:
            escritor.add_page(PdfReader(io.BytesIO(imagenes[numero])).pages[0])
        else:
            escritor.add_page(pagina)
    # El `Info` del escritor nuevo trae solo su propio `Producer`: del original no pasa nada.
    if escritor._info is not None:
        escritor._info.clear()
    with open(destino, "wb") as salida:
        escritor.write(salida)

    return Resultado(
        paginas=total,
        paginas_redactadas=tuple(sorted(imagenes)),
        coincidencias=tuple(coincidencias),
        areas=len(areas),
    )
