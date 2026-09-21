"""Bajar el peso de un PDF sin que deje de servir para lo que sirve.

## El caso real, que no es «ocupa mucho»

**Un juego de planos no entra en un correo.** Esa es la frase con la que llega esto: no es
higiene de disco, es que el envío rebota y la entrega se retrasa un día. Por eso lo que
importa no es cuánto baja, sino **cuánto baja sin estropear el plano**.

## Dónde está el peso de verdad

En las imágenes, casi siempre. Un juego de planos escaneados a 600 ppp pesa diez veces lo que
el mismo a 200, y a 200 se lee igual en pantalla y se imprime bien en A3. El texto vectorial y
las líneas no pesan nada en comparación, y **no se tocan**: reducirlos sí estropearía el plano.

Así que hay dos palancas y ninguna es un botón mágico:

1. **Recomprimir los flujos de contenido.** Gratis y sin pérdida — es volver a empaquetar lo
   que ya está. Suele dar poco, y nunca estropea nada.
2. **Bajar la resolución de las imágenes incrustadas.** Es donde está el peso y es donde se
   puede hacer daño, así que la resolución la elige quien convierte, con las consecuencias
   escritas al lado.

## Lo que no se hace, y es deliberado

**No se entrega un archivo que pese más que el original.** Recomprimir un PDF que ya venía
optimizado puede engordarlo, y entregar eso —después de que alguien haya pulsado «comprimir»—
es la peor respuesta posible: parece que funcionó y empeoró el problema. Si no baja, se dice.

Y **no se toca el original**, como en todas las demás: se escribe un parcial y se renombra.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from .composicion import ComposicionInvalida

#: Las tres resoluciones que se ofrecen, con **para qué sirve cada una**.
#:
#: Un campo libre de ppp invita a teclear 72 y descubrir que los planos salieron ilegibles
#: cuando el cliente ya los tiene. Las tres cubren los casos reales de una oficina.
RESOLUCIONES = {
    0: "Sin tocar las imágenes — solo recomprime. Nunca estropea nada",
    200: "Para mandar por correo y leer en pantalla. Se imprime bien hasta A3",
    150: "Lo más ligero que sigue siendo legible. Para revisar, no para entregar",
}

#: Calidad del JPEG al recomprimir. 82 es el punto donde una foto deja de ganar peso
#: visiblemente y todavía no pierde detalle a simple vista.
CALIDAD = 82

#: Por debajo de esto no se toca la imagen: un logotipo de 200 px no tiene nada que bajar y
#: recomprimirlo solo añade artefactos.
LADO_MINIMO = 400


@dataclass(frozen=True)
class Resultado:
    """Qué pasó, en números. Es lo que la pantalla enseña antes de descargar."""

    origen_bytes: int
    salida_bytes: int
    imagenes_tocadas: int
    paginas: int

    @property
    def reduccion_pct(self) -> int:
        if not self.origen_bytes:
            return 0
        return round((1 - self.salida_bytes / self.origen_bytes) * 100)

    @property
    def merecio_la_pena(self) -> bool:
        """**El resultado tiene que pesar menos.** Recomprimir un PDF ya optimizado puede
        engordarlo, y entregar eso después de pulsar «comprimir» empeora el problema que se
        venía a resolver."""
        return self.salida_bytes < self.origen_bytes


def comprimir(
    origen: str | Path,
    *,
    ppp: int = 200,
    destino: Path | None = None,
) -> tuple[Path | None, Resultado]:
    """Devuelve `(ruta, resultado)`. La ruta es `None` si no valió la pena y no se escribió.

    Devolver el resultado aunque no se escriba nada es lo que permite que la pantalla diga
    «ya estaba comprimido, pesa 4,2 MB y así se queda» en vez de un error — porque no es un
    error: es la respuesta correcta.
    """
    from pypdf import PdfReader, PdfWriter

    origen = Path(origen)
    if ppp not in RESOLUCIONES:
        raise ComposicionInvalida(f"«{ppp}» no es una de las resoluciones que se ofrecen.")

    try:
        lector = PdfReader(str(origen))
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo abrir {origen.name}: {fallo}") from fallo

    if lector.is_encrypted:
        raise ComposicionInvalida(
            f"{origen.name} está protegido con contraseña. Quítasela primero con «Proteger PDF»."
        )

    escritor = PdfWriter()
    tocadas = 0
    for hoja in lector.pages:
        escritor.add_page(hoja)

    if ppp:
        tocadas = _encoger_imagenes(escritor, ppp)

    for hoja in escritor.pages:
        try:
            hoja.compress_content_streams()
        except Exception:  # nosec B112 - saltar es la respuesta correcta, ver debajo
            # Un flujo que pypdf no sabe recomprimir se queda como está. Perder la página
            # entera por no poder apretarla sería cambiar peso por contenido.
            continue

    destino = Path(destino) if destino else origen.with_name(f"{origen.stem}_ligero.pdf")
    parcial = destino.with_name(destino.name + ".parcial")
    try:
        with parcial.open("wb") as salida:
            escritor.write(salida)
    except Exception as fallo:
        parcial.unlink(missing_ok=True)
        raise ComposicionInvalida(f"No se pudo escribir el PDF: {fallo}") from fallo

    resultado = Resultado(
        origen_bytes=origen.stat().st_size,
        salida_bytes=parcial.stat().st_size,
        imagenes_tocadas=tocadas,
        paginas=len(lector.pages),
    )

    if not resultado.merecio_la_pena:
        parcial.unlink(missing_ok=True)
        return None, resultado

    parcial.replace(destino)
    return destino, resultado


def _encoger_imagenes(escritor, ppp: int) -> int:
    """Baja la resolución de las imágenes incrustadas. Devuelve cuántas tocó.

    **Se salta las pequeñas.** Un logotipo de 200 px no tiene nada que bajar, y recomprimirlo
    solo le añade artefactos JPEG sin ahorrar un byte que se note.

    Y se salta en silencio lo que no sabe manejar: una imagen con máscara de transparencia, un
    formato raro, una que Pillow no abra. **Perder la imagen sería cambiar peso por contenido**,
    que es justo lo contrario de lo que se pidió.
    """
    from PIL import Image

    tocadas = 0
    for hoja in escritor.pages:
        try:
            imagenes = list(hoja.images)
        except Exception:  # nosec B112 - una hoja cuyo inventario no se lee se deja entera
            continue

        for imagen in imagenes:
            try:
                original = imagen.image
                if original is None:
                    continue
                ancho, alto = original.size
                if max(ancho, alto) < LADO_MINIMO:
                    continue

                # La escala sale de comparar la resolución que tiene con la que se pide,
                # tomando el ancho de una hoja A4 en pulgadas como referencia.
                objetivo = int(ppp * 8.27)
                if ancho <= objetivo:
                    continue

                escala = objetivo / ancho
                nuevo = original.resize(
                    (objetivo, max(1, int(alto * escala))), Image.LANCZOS
                ).convert("RGB")

                crudo = io.BytesIO()
                nuevo.save(crudo, format="JPEG", quality=CALIDAD, optimize=True)
                imagen.replace(nuevo, quality=CALIDAD)
                tocadas += 1
            except Exception:  # nosec B112 - la imagen se deja como venía, nunca se pierde
                continue
    return tocadas
