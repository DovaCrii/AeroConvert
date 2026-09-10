"""Dibujar una página de un PDF, para poder verla antes de ordenarla.

Ordenar cincuenta y seis filas de texto no es ordenar: hay que ver las hojas. Es la misma
idea que la vista previa de una libreta de puntos — enseñar el dato en vez de describirlo —
y aquí es todavía más directa, porque una página de un PDF **es** una imagen.

## Se dibuja al vuelo y no se guarda nada

Sin caché en disco. Una miniatura de 220 px tarda unas decenas de milisegundos, y guardarla
traería lo de siempre: una carpeta que crece, que hay que barrer, y que se queda obsoleta
cuando el archivo cambia. En su lugar la respuesta lleva un `ETag` que depende del archivo
—su fecha, su tamaño, la página y el ancho— así que **la caché la hace el navegador**: la
primera vez pide las cincuenta y seis, y al pulsar «bajar» las recibe todas con un 304.

Eso encaja además con la promesa del modo taller: no se copia nada, no se deja nada.

## Y el que dibuja es PDFium, no nosotros

`pypdfium2` es el motor de PDF de Chrome, con licencia Apache-2.0. La alternativa cómoda
—PyMuPDF— es AGPL-3, la misma razón por la que ya se descartó LibreDWG.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

#: Ancho de la miniatura, en píxeles. Suficiente para reconocer una lámina y ver si está
#: derecha; muy por debajo de lo que costaría leerla, que no es lo que se pide aquí.
ANCHO = 220

#: Tope de seguridad. Una petición manipulada no puede pedir una imagen de 20.000 px.
ANCHO_MAXIMO = 600


class NoSePudoDibujar(Exception):
    """Esa página no se pudo dibujar. No es motivo para tumbar la pantalla."""


def etiqueta(ruta: Path, pagina: int, giro: int, ancho: int) -> str:
    """El `ETag` de esa miniatura.

    Depende del archivo **y de su fecha y tamaño**: si alguien regenera el PDF con el mismo
    nombre, la etiqueta cambia y el navegador vuelve a pedirla. Sin eso, la pantalla
    enseñaría la hoja de ayer con toda la confianza del mundo.
    """
    try:
        estado = ruta.stat()
        sello = f"{estado.st_mtime_ns}:{estado.st_size}"
    except OSError:
        sello = "0:0"
    crudo = f"{ruta}|{sello}|{pagina}|{giro}|{ancho}"
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:32]


def dibujar(ruta: Path, pagina: int, *, giro: int = 0, ancho: int = ANCHO) -> bytes:
    """Devuelve el PNG de esa página, con el giro pedido ya aplicado.

    `pagina` empieza en 1, como en el visor y como en la lista de la pantalla.
    """
    import pypdfium2

    ancho = max(40, min(int(ancho), ANCHO_MAXIMO))

    try:
        documento = pypdfium2.PdfDocument(str(ruta))
    except Exception as fallo:
        raise NoSePudoDibujar(f"No se pudo abrir {ruta.name}: {fallo}") from fallo

    try:
        if not 1 <= pagina <= len(documento):
            raise NoSePudoDibujar(
                f"{ruta.name} tiene {len(documento)} página(s) y se pidió la {pagina}."
            )

        hoja = documento[pagina - 1]
        # `get_size()` ya viene con el giro del propio PDF aplicado, así que la escala se
        # calcula sobre lo que se ve y no sobre la caja.
        ancho_pt, _alto_pt = hoja.get_size()
        escala = ancho / float(ancho_pt or ancho)

        # El giro que pide la pantalla se suma al que la página ya traía, igual que en la
        # composición: quien mira ve una hoja tumbada, pulsa girar, y la quiere de pie.
        if giro:
            hoja.set_rotation((hoja.get_rotation() + giro) % 360)
            ancho_pt, _alto_pt = hoja.get_size()
            escala = ancho / float(ancho_pt or ancho)

        imagen = hoja.render(scale=escala).to_pil()
    except NoSePudoDibujar:
        raise
    except Exception as fallo:
        raise NoSePudoDibujar(f"No se pudo dibujar la página {pagina}: {fallo}") from fallo
    finally:
        documento.close()

    import io

    memoria = io.BytesIO()
    # PNG y no JPEG: una página de plano son líneas finas sobre blanco, y el JPEG deja
    # suciedad justo en el borde de cada línea — que es lo único que hay que mirar.
    imagen.save(memoria, format="PNG", optimize=True)
    return memoria.getvalue()
