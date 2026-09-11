"""Numerar las páginas y poner una marca de agua.

Las dos cosas son lo mismo por dentro: se dibuja una hoja transparente del tamaño exacto de
la página y se le pone encima. El original no se toca y el texto que ya había no se altera —
se le superpone una capa, no se reescribe el documento.

## Por qué esto hace falta justo después de unir

Una entrega que sale de juntar cinco PDF **no tiene numeración**: cada uno traía la suya, o
ninguna. Y una lámina que se emite para revisión tiene que ir estampada, porque un plano sin
marca que circula por correo acaba en obra como si estuviera aprobado.

## Las tres trampas, que son de geometría

**1. Las hojas no son todas iguales.** Una entrega real mezcla A4 de memoria con A1 de
planos. La capa se dibuja **por página, al tamaño de esa página**; una sola capa reutilizada
deja el número fuera del papel en cuanto cambia el formato.

**2. El `/Rotate` mueve el pie de página a un lateral.** Fusionar una capa dibujada en el
sistema de la caja sobre una página girada pone el número de canto, en el borde equivocado.
Aquí la capa se dibuja en el sistema de coordenadas **de lo que se ve**, aplicando al lienzo
la transformación inversa del giro. Ver `_encuadrar()`.

**3. El tamaño de letra no puede ser fijo.** Diez puntos en un A4 se leen; los mismos diez
puntos en un A1 son una mota. Se escala con el lado corto de la hoja, con tope, para que el
número ocupe una proporción parecida en cualquier formato.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from .composicion import ComposicionInvalida

#: Los cuatro giros que un PDF puede declarar. Cualquier otro valor es un archivo roto y se
#: trata como 0.
GIROS = (0, 90, 180, 270)

MM_POR_PUNTO = 25.4 / 72

#: Helvetica es una de las catorce fuentes que todo lector de PDF trae, asi que **no se
#: incrusta nada**: la capa pesa unos cientos de bytes por pagina en vez de medio mega.
FUENTE = "Helvetica"

#: Cuerpo base, medido sobre A4. Se escala con el lado corto de la hoja (ver `_cuerpo`).
CUERPO_BASE = 10.0
CUERPO_MAXIMO = 30.0

#: Margen en milimetros, tambien sobre A4 y tambien escalado.
MARGEN_MM = 12.0

#: Donde va el numero. El pie a la derecha es la convencion en planos -- queda junto a la
#: vinyeta -- y el pie centrado lo es en memorias.
POSICIONES = {
    "pie-derecha": "Pie, a la derecha — junto a la viñeta del plano",
    "pie-centro": "Pie, centrado — lo normal en una memoria",
    "pie-izquierda": "Pie, a la izquierda",
    "cabecera-derecha": "Cabecera, a la derecha",
    "cabecera-centro": "Cabecera, centrada",
    "cabecera-izquierda": "Cabecera, a la izquierda",
}

#: Como se escribe el numero. Con `{n}` y `{total}`, que es lo unico que se sustituye.
FORMATOS = {
    "{n}": "3",
    "{n} / {total}": "3 / 56",
    "Página {n} de {total}": "Página 3 de 56",
}

#: Cuanto se ve la marca de agua. Es lo que mas se pide cambiar: demasiado suave no cumple
#: su funcion y demasiado fuerte tapa las cotas del plano.
OPACIDADES = {
    "suave": 0.08,
    "normal": 0.15,
    "marcada": 0.30,
}

#: Tope del texto de la marca. «CONFIDENCIAL», «NO VÁLIDO PARA CONSTRUCCIÓN», «BORRADOR».
#: Una frase larga sale ilegible por pequena y no ayuda a nadie.
MAXIMO_TEXTO = 60


@dataclass(frozen=True)
class Marcado:
    """Lo que se hizo, para el recibo."""

    paginas: int
    #: Cuantas llevan marca. Al numerar puede ser menos que el total, si se salta la portada.
    marcadas: int


def _giro(pagina) -> int:
    try:
        valor = int(pagina.get("/Rotate", 0) or 0) % 360
    except (TypeError, ValueError):
        return 0
    return valor if valor in GIROS else 0


def _encuadrar(lienzo, ancho: float, alto: float, giro: int) -> tuple[float, float]:
    """Deja el lienzo en el sistema de coordenadas de **lo que se ve**.

    `/Rotate` es el giro **en sentido horario** que el lector aplica al mostrar la página, así
    que para que el dibujo caiga donde se ve hay que aplicarle al lienzo el giro contrario.
    Devuelve el ancho y el alto ya como se ven, que es contra lo que se colocan las cosas.
    """
    if giro == 90:
        lienzo.translate(ancho, 0)
        lienzo.rotate(90)
        return alto, ancho
    if giro == 180:
        lienzo.translate(ancho, alto)
        lienzo.rotate(180)
        return ancho, alto
    if giro == 270:
        lienzo.translate(0, alto)
        lienzo.rotate(-90)
        return alto, ancho
    return ancho, alto


def _cuerpo(ancho_vista: float, alto_vista: float) -> float:
    """Tamaño de letra proporcionado a la hoja.

    Se escala con el **lado corto**, no con el área ni con la diagonal: es el lado corto el
    que determina a qué distancia se mira una hoja.
    """
    corto_mm = min(ancho_vista, alto_vista) * MM_POR_PUNTO
    return min(CUERPO_MAXIMO, max(CUERPO_BASE, CUERPO_BASE * corto_mm / 210.0))


def _capa(ancho: float, alto: float):
    from reportlab.pdfgen import canvas

    memoria = io.BytesIO()
    lienzo = canvas.Canvas(memoria, pagesize=(ancho, alto))
    return lienzo, memoria


def _pegar(pagina, lienzo, memoria) -> None:
    """Cierra la capa y la superpone a la página."""
    from pypdf import PdfReader

    lienzo.save()
    memoria.seek(0)
    pagina.merge_page(PdfReader(memoria).pages[0], over=True)


def _abrir(origen: Path):
    from pypdf import PdfReader

    try:
        lector = PdfReader(str(origen))
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo leer {origen.name}: {fallo}") from fallo
    if lector.is_encrypted:
        raise ComposicionInvalida(
            f"{origen.name} pide contraseña. Quítasela primero en «Proteger PDF»."
        )
    return lector


def numerar(
    origen: str | Path,
    destino: str | Path,
    *,
    posicion: str = "pie-derecha",
    formato: str = "{n} / {total}",
    desde: int = 1,
    empezar_en: int = 1,
) -> Marcado:
    """Escribe una copia numerada.

    `desde` es la primera página que **lleva** número —una portada no se numera— y
    `empezar_en` es el número que se le pone. Son dos cosas distintas y las dos se piden: una
    memoria con portada y contraportada empieza a numerar en la 3 y quiere que ahí ponga 1.
    """
    from pypdf import PdfWriter
    from reportlab.pdfbase.pdfmetrics import stringWidth

    origen, destino = Path(origen), Path(destino)

    if posicion not in POSICIONES:
        raise ComposicionInvalida(f"«{posicion}» no es una posición de las que se ofrecen.")
    if formato not in FORMATOS:
        raise ComposicionInvalida(f"«{formato}» no es un formato de numeración de los que hay.")

    lector = _abrir(origen)
    total_paginas = len(lector.pages)

    if desde < 1 or desde > total_paginas:
        raise ComposicionInvalida(
            f"{origen.name} tiene {total_paginas} página(s): no se puede empezar en la {desde}."
        )

    cuantas_marcadas = total_paginas - desde + 1
    # «de 56» tiene que ser el ultimo numero que de verdad aparece impreso. Si la portada no
    # se numera y se empieza a contar en 1, el documento de 57 hojas dice «de 56», que es lo
    # que cuadra con lo que el lector ve escrito en la ultima.
    ultimo = empezar_en + cuantas_marcadas - 1

    # Se clona **al escritor** y se marca sobre sus paginas, no sobre las del lector: pypdf
    # avisa de que fusionar sobre una pagina suelta es poco fiable y lo va a quitar.
    escritor = PdfWriter(clone_from=lector)
    numero = empezar_en

    for indice, pagina in enumerate(escritor.pages, start=1):
        if indice >= desde:
            caja = pagina.mediabox
            ancho, alto = float(caja.width), float(caja.height)
            lienzo, memoria = _capa(ancho, alto)
            lienzo.translate(float(caja.left), float(caja.bottom))
            ancho_vista, alto_vista = _encuadrar(lienzo, ancho, alto, _giro(pagina))

            cuerpo = _cuerpo(ancho_vista, alto_vista)
            margen = MARGEN_MM / MM_POR_PUNTO * (cuerpo / CUERPO_BASE)
            texto = formato.format(n=numero, total=ultimo)

            lienzo.setFont(FUENTE, cuerpo)
            lienzo.setFillGray(0.15)
            ancho_texto = stringWidth(texto, FUENTE, cuerpo)

            if posicion.endswith("izquierda"):
                x = margen
            elif posicion.endswith("centro"):
                x = (ancho_vista - ancho_texto) / 2
            else:
                x = ancho_vista - margen - ancho_texto

            y = alto_vista - margen - cuerpo if posicion.startswith("cabecera") else margen

            lienzo.drawString(x, y, texto)
            _pegar(pagina, lienzo, memoria)
            numero += 1

    with open(destino, "wb") as salida:
        escritor.write(salida)

    return Marcado(paginas=total_paginas, marcadas=cuantas_marcadas)


def marca_de_agua(
    origen: str | Path,
    destino: str | Path,
    texto: str,
    *,
    opacidad: str = "normal",
    diagonal: bool = True,
) -> Marcado:
    """Escribe una copia con el texto estampado en todas las páginas.

    Va **encima** del contenido, no debajo: una marca que el dibujo del plano tapa no marca
    nada. Por eso importa la opacidad, y por eso son tres valores medidos y no un control
    deslizante que invita a dejarlo al 100 %.
    """
    from pypdf import PdfWriter
    from reportlab.pdfbase.pdfmetrics import stringWidth

    origen, destino = Path(origen), Path(destino)
    texto = " ".join((texto or "").split())

    if not texto:
        raise ComposicionInvalida("No escribiste el texto de la marca.")
    if len(texto) > MAXIMO_TEXTO:
        raise ComposicionInvalida(
            f"El texto no puede pasar de {MAXIMO_TEXTO} caracteres: más largo sale ilegible."
        )
    if opacidad not in OPACIDADES:
        raise ComposicionInvalida(f"«{opacidad}» no es una de las intensidades que se ofrecen.")

    lector = _abrir(origen)
    escritor = PdfWriter(clone_from=lector)

    for pagina in escritor.pages:
        caja = pagina.mediabox
        ancho, alto = float(caja.width), float(caja.height)
        lienzo, memoria = _capa(ancho, alto)
        lienzo.translate(float(caja.left), float(caja.bottom))
        ancho_vista, alto_vista = _encuadrar(lienzo, ancho, alto, _giro(pagina))

        # Se busca el cuerpo que hace que el texto ocupe el 80 % de lo que tiene que cruzar.
        # Medir con un cuerpo cualquiera y escalar es exacto: el ancho de una cadena es
        # proporcional al tamano de la letra.
        cruce = (ancho_vista**2 + alto_vista**2) ** 0.5 if diagonal else ancho_vista
        patron = stringWidth(texto, FUENTE, 100.0)
        cuerpo = 100.0 * (cruce * 0.8) / patron if patron else CUERPO_BASE

        lienzo.saveState()
        lienzo.setFillGray(0.35, alpha=OPACIDADES[opacidad])
        lienzo.setFont(FUENTE, cuerpo)
        lienzo.translate(ancho_vista / 2, alto_vista / 2)
        if diagonal:
            # El angulo de la propia diagonal de la hoja, no 45 fijos: en un A1 apaisado 45
            # grados deja el texto cruzando por una esquina.
            from math import atan2, degrees

            lienzo.rotate(degrees(atan2(alto_vista, ancho_vista)))
        # Centrado sobre el origen ya trasladado. El 0,35 del cuerpo aproxima la mitad de la
        # altura de una mayuscula de Helvetica, que es lo que centra a ojo.
        lienzo.drawCentredString(0, -cuerpo * 0.35, texto)
        lienzo.restoreState()
        _pegar(pagina, lienzo, memoria)

    with open(destino, "wb") as salida:
        escritor.write(salida)

    cuantas = len(lector.pages)
    return Marcado(paginas=cuantas, marcadas=cuantas)
