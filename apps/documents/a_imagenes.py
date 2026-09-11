"""Sacar las páginas de un PDF como imágenes.

Es lo contrario de `dividir.desde_imagenes`, y el caso real no es «quiero fotos»: es meter
una lámina en un informe de Word, en una presentación o en un correo, donde un PDF no se
pega.

## La resolución es la decisión, no el formato

Una hoja A4 a 150 ppp son 1.240 × 1.754 px: se lee bien en pantalla y pesa poco. La misma a
300 ppp pesa cuatro veces más y solo hace falta si se va a imprimir. Un plano A1 a 300 ppp
son casi 10.000 px de lado y varios cientos de megabytes en memoria, así que hay un tope.

## JPG para fotos, PNG para líneas

Un plano son líneas finas sobre blanco y el JPEG deja suciedad en el borde de cada una —
justo donde está la información. Un escaneo de una foto, en cambio, pesa tres veces menos en
JPEG y no se nota. Por eso se elige, y por eso el aviso está en la pantalla y no aquí.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .composicion import ComposicionInvalida
from .dividir import Trozo

#: Resoluciones que se ofrecen, con para que sirve cada una. Un campo libre de ppp invita a
#: teclear 1200 y descubrir el problema cuando la maquina lleva dos minutos parada.
RESOLUCIONES = {
    96: "Pantalla — la más ligera",
    150: "Normal — para leer y para un informe",
    300: "Impresión — pesa cuatro veces más",
}

#: Tope de pixeles por lado. Un A1 a 300 ppp ya roza los 10.000, y por encima de esto la
#: imagen no la abre comodamente ningun programa de oficina.
LADO_MAXIMO = 12_000

FORMATOS = {"jpg": "JPEG", "png": "PNG"}


def paginas_a_imagenes(
    origen: str | Path,
    trozos: Iterable[Trozo],
    *,
    formato: str = "png",
    ppp: int = 150,
    carpeta: Path | None = None,
) -> list[Path]:
    """Escribe una imagen por página y devuelve las rutas.

    **Todas o ninguna**, igual que al partir: media entrega de imágenes sueltas con nombres
    correlativos es peor que un error.
    """
    import pypdfium2

    origen = Path(origen)
    carpeta = Path(carpeta) if carpeta else origen.parent

    if formato not in FORMATOS:
        raise ComposicionInvalida(f"«{formato}» no es un formato de imagen de los que se hacen.")
    if ppp not in RESOLUCIONES:
        raise ComposicionInvalida(f"«{ppp}» no es una de las resoluciones que se ofrecen.")

    numeros = sorted({n for trozo in trozos for n in range(trozo.desde, trozo.hasta + 1)})
    if not numeros:
        raise ComposicionInvalida("No indicaste ninguna página.")

    try:
        documento = pypdfium2.PdfDocument(str(origen))
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo abrir {origen.name}: {fallo}") from fallo

    escritas: list[Path] = []
    try:
        total = len(documento)
        for numero in numeros:
            if not 1 <= numero <= total:
                raise ComposicionInvalida(
                    f"{origen.name} tiene {total} página(s) y se pidió la {numero}."
                )

            hoja = documento[numero - 1]
            ancho_pt, alto_pt = hoja.get_size()
            escala = ppp / 72

            if max(ancho_pt, alto_pt) * escala > LADO_MAXIMO:
                raise ComposicionInvalida(
                    f"La página {numero} a {ppp} ppp saldría de más de {LADO_MAXIMO} píxeles "
                    "de lado. Baja la resolución."
                )

            imagen = hoja.render(scale=escala).to_pil()
            destino = carpeta / f"{origen.stem}_{numero}.{formato}"
            try:
                if formato == "jpg":
                    # El JPEG no admite alfa, y lo que hay detrás de una página es papel.
                    imagen = imagen.convert("RGB")
                    imagen.save(destino, FORMATOS[formato], quality=88, optimize=True)
                else:
                    imagen.save(destino, FORMATOS[formato], optimize=True)
            finally:
                imagen.close()
            escritas.append(destino)
    except Exception:
        for hecha in escritas:
            hecha.unlink(missing_ok=True)
        raise
    finally:
        documento.close()

    return escritas
