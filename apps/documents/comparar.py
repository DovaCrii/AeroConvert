"""Comparar dos PDF y ver **dónde** difieren, lado a lado.

Es lo que se necesita cuando llega la «revisión B» de un plano y nadie dice qué cambió: no
importa qué cambió en el archivo —el PDF puede haberse regenerado entero sin cambiar nada de lo
que se ve— sino **qué cambió en la hoja**.

## Cómo se compara

Se dibujan las dos páginas con PDFium a la misma escala y se restan. Lo que difiere se agrupa en
regiones (celdas de `CELDA_PX` unidas con sus vecinas) y se informa en puntos de la página, con la
y desde arriba, que es como se miran. Una página que solo está en uno de los dos, o que cambió
de tamaño, se informa entera: ahí no hay nada que superponer.

## Lo que se entrega

Un PDF con **solo las páginas que difieren**, cada una con tres columnas: antes, después y las
diferencias marcadas en rojo sobre el «después». Si no hay ninguna, no hay archivo: el desenlace
`sin-diferencias` lo dice, que es la respuesta correcta y no un fallo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .composicion import ComposicionInvalida

#: Píxeles por punto al dibujar. 1,5 distingue una línea fina de plano y no se come la memoria
#: con una lámina A0 (unos 5 000 × 3 500 px).
ESCALA = 1.5

#: Lado, en píxeles, de la celda con la que se agrupan las diferencias.
CELDA_PX = 12

#: Cuánto tiene que cambiar el gris de un píxel (0-255) para contar. Deja fuera el ruido de
#: suavizado entre dos dibujos del mismo trazo y coge una línea que se movió.
UMBRAL = 48

#: Tope de píxeles de una página dibujada; una hoja más grande se dibuja a menos escala.
MAXIMO_PX = 40_000_000


@dataclass(frozen=True)
class Region:
    pagina: int
    #: En puntos de la página, con el origen arriba a la izquierda.
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class Comparacion:
    paginas_a: int
    paginas_b: int
    regiones: tuple[Region, ...]
    #: Páginas (desde 1) que difieren en algo, incluidas las que solo están en un documento.
    paginas_distintas: tuple[int, ...]
    #: Las que cambiaron de tamaño o faltan en uno: no se pueden superponer.
    sin_superponer: tuple[int, ...]

    @property
    def iguales(self) -> bool:
        return not self.paginas_distintas


def _abrir(ruta: Path):
    import pypdfium2

    try:
        return pypdfium2.PdfDocument(str(ruta))
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo abrir {ruta.name}: {fallo}") from fallo


def _dibujar(documento, indice: int, escala: float):
    pagina = documento[indice]
    try:
        ancho, alto = pagina.get_size()
        propia = min(escala, (MAXIMO_PX / max(ancho * alto, 1)) ** 0.5)
        return pagina.render(scale=propia).to_pil().convert("RGB"), propia, (ancho, alto)
    finally:
        pagina.close()


def _componentes(celdas: set[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    """Agrupa celdas vecinas (8 direcciones) y devuelve la caja de cada grupo."""
    pendientes = set(celdas)
    cajas = []
    while pendientes:
        inicio = pendientes.pop()
        pila = [inicio]
        cx0 = cx1 = inicio[0]
        cy0 = cy1 = inicio[1]
        while pila:
            cx, cy = pila.pop()
            cx0, cx1, cy0, cy1 = min(cx0, cx), max(cx1, cx), min(cy0, cy), max(cy1, cy)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    vecino = (cx + dx, cy + dy)
                    if vecino in pendientes:
                        pendientes.remove(vecino)
                        pila.append(vecino)
        cajas.append((cx0, cy0, cx1, cy1))
    return sorted(cajas, key=lambda c: (c[1], c[0]))


def _diferencias(a, b, escala: float, pagina: int) -> tuple[list[Region], object]:
    """Las regiones en que dos imágenes del mismo tamaño difieren, y la máscara de diferencia."""
    from PIL import ImageChops

    resta = ImageChops.difference(a, b).convert("L")
    mascara = resta.point(lambda p: 255 if p >= UMBRAL else 0)
    if mascara.getbbox() is None:
        return [], mascara

    ancho, alto = mascara.size
    celdas: set[tuple[int, int]] = set()
    for cy in range(0, alto, CELDA_PX):
        for cx in range(0, ancho, CELDA_PX):
            recorte = mascara.crop((cx, cy, min(cx + CELDA_PX, ancho), min(cy + CELDA_PX, alto)))
            if recorte.getbbox() is not None:
                celdas.add((cx // CELDA_PX, cy // CELDA_PX))

    regiones = [
        Region(
            pagina,
            x0 * CELDA_PX / escala,
            y0 * CELDA_PX / escala,
            min((x1 + 1) * CELDA_PX, ancho) / escala,
            min((y1 + 1) * CELDA_PX, alto) / escala,
        )
        for x0, y0, x1, y1 in _componentes(celdas)
    ]
    return regiones, mascara


def _hoja_de_comparacion(a, b, mascara, regiones: list[Region], escala: float, numero: int):
    """Tres columnas: antes, después y el después con lo que cambió en rojo."""
    from PIL import Image, ImageDraw

    ancho, alto = b.size
    marcado = b.copy()
    rojo = Image.new("RGB", b.size, (220, 30, 30))
    marcado.paste(rojo, mask=mascara)
    trazo = ImageDraw.Draw(marcado)
    for r in regiones:
        trazo.rectangle(
            (r.x0 * escala - 3, r.y0 * escala - 3, r.x1 * escala + 3, r.y1 * escala + 3),
            outline=(220, 30, 30),
            width=3,
        )

    cabecera = 34
    hoja = Image.new("RGB", (ancho * 3 + 40, alto + cabecera), (255, 255, 255))
    pincel = ImageDraw.Draw(hoja)
    for columna, (imagen, titulo) in enumerate(
        ((a, "Antes"), (b, "Después"), (marcado, "Diferencias"))
    ):
        x = columna * (ancho + 20)
        pincel.text((x + 6, 10), f"{titulo} · página {numero}", fill=(40, 40, 40))
        hoja.paste(imagen, (x, cabecera))
    return hoja


def _hoja_de_aviso(texto: str):
    """Una hoja con una línea, para lo que no se puede superponer."""
    from PIL import Image, ImageDraw

    hoja = Image.new("RGB", (900, 200), (255, 255, 255))
    ImageDraw.Draw(hoja).text((20, 90), texto, fill=(40, 40, 40))
    return hoja


def comparar(
    antes: str | Path,
    despues: str | Path,
    destino: str | Path | None = None,
    *,
    escala: float = ESCALA,
    progreso: Callable[[float], None] | None = None,
) -> Comparacion:
    """Compara dos PDF. Con `destino`, escribe el informe de las páginas que difieren."""
    antes, despues = Path(antes), Path(despues)
    doc_a, doc_b = _abrir(antes), _abrir(despues)
    hojas = []
    regiones: list[Region] = []
    distintas: list[int] = []
    sin_superponer: list[int] = []
    try:
        n_a, n_b = len(doc_a), len(doc_b)
        total = max(n_a, n_b)
        for i in range(total):
            numero = i + 1
            if i >= n_a or i >= n_b:
                distintas.append(numero)
                sin_superponer.append(numero)
                if destino is not None:
                    donde = "solo en «antes»" if i >= n_b else "solo en «después»"
                    hojas.append(_hoja_de_aviso(f"La página {numero} está {donde}."))
                continue

            img_a, esc_a, tam_a = _dibujar(doc_a, i, escala)
            img_b, esc_b, tam_b = _dibujar(doc_b, i, escala)
            if (
                img_a.size != img_b.size
                or abs(tam_a[0] - tam_b[0]) > 0.5
                or abs(tam_a[1] - tam_b[1]) > 0.5
            ):
                distintas.append(numero)
                sin_superponer.append(numero)
                regiones.append(Region(numero, 0.0, 0.0, tam_b[0], tam_b[1]))
                if destino is not None:
                    hojas.append(_hoja_de_aviso(f"La página {numero} cambió de tamaño."))
                continue

            de_la_pagina, mascara = _diferencias(img_a, img_b, esc_a, numero)
            if de_la_pagina:
                distintas.append(numero)
                regiones.extend(de_la_pagina)
                if destino is not None:
                    hojas.append(
                        _hoja_de_comparacion(img_a, img_b, mascara, de_la_pagina, esc_a, numero)
                    )
            if progreso is not None:
                progreso(numero / total)
    finally:
        doc_a.close()
        doc_b.close()

    resultado = Comparacion(
        paginas_a=n_a,
        paginas_b=n_b,
        regiones=tuple(regiones),
        paginas_distintas=tuple(distintas),
        sin_superponer=tuple(sin_superponer),
    )
    if destino is not None and hojas:
        primera, *resto = hojas
        primera.save(destino, "PDF", save_all=True, append_images=resto, resolution=72 * escala)
    return resultado
