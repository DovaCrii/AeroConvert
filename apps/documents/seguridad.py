"""Poner y quitar la contraseña de un PDF.

## Solo AES-256

pypdf sabe cifrar de tres maneras y **dos de ellas no sirven**: RC4 de 40 y de 128 bits
están rotos desde hace veinte años y se abren con herramientas que se descargan en un
minuto. Un PDF «protegido» así da una sensación de seguridad que no existe, y en un
entregable bajo acuerdo de confidencialidad eso es peor que no protegerlo — quien lo manda
cree que va cerrado.

Así que aquí solo hay una opción, y no es un desplegable.

## La contraseña no se guarda en ninguna parte

No se escribe en la bitácora, no se queda en el formulario que se devuelve, y no viaja en la
URL. Entra en un POST, se usa, y se va con la petición.

**Y no hay forma de recuperarla.** Si se pierde, el archivo se pierde: eso es lo que
significa que el cifrado funcione. La pantalla lo dice antes, no después.

## Quitar la contraseña exige saberla

Esto no abre nada: descifra un archivo para el que ya se tiene la clave, que es el caso real
—«me mandaron el plano protegido y tengo la clave del correo, pero necesito componerlo con
los demás»—. Sin la clave correcta, pypdf se niega y aquí se dice y se para.
"""

from __future__ import annotations

from pathlib import Path

from .composicion import ComposicionInvalida

#: El unico algoritmo que se ofrece. Ver el docstring del modulo.
ALGORITMO = "AES-256"

#: Minimo de caracteres. No es una politica de contrasenas -- esto no es una cuenta, es un
#: archivo que se manda por correo -- pero cuatro caracteres no protegen de nada y conviene
#: decirlo en el sitio donde se escribe.
MINIMO = 6


class ContrasenaIncorrecta(ComposicionInvalida):
    """Con su código, para que la ficha no la confunda con un documento roto."""

    codigo = "contrasena-incorrecta"


def abre(origen: str | Path, contrasena: str) -> bool:
    """Si esa contraseña abre el archivo. Es barato: no descifra ninguna página.

    Lo usa la pantalla para decirlo **antes** de encolar. Descubrirlo en la cola manda a la
    persona a una ficha roja y de vuelta aquí a escribirla otra vez, que es el mismo trabajo
    con un viaje de más.
    """
    from pypdf import PdfReader

    try:
        lector = PdfReader(str(origen))
        return not lector.is_encrypted or bool(lector.decrypt(contrasena or ""))
    except Exception:  # noqa: BLE001 - si no se puede ni leer, tampoco la abre
        return False


def proteger(origen: str | Path, destino: str | Path, contrasena: str) -> int:
    """Escribe una copia cifrada. Devuelve cuántas páginas tiene.

    El original se queda como está: protegerlo *en el sitio* dejaría a alguien sin el
    archivo si se equivoca al teclear la clave dos veces.
    """
    from pypdf import PdfReader, PdfWriter

    origen, destino = Path(origen), Path(destino)
    contrasena = contrasena or ""

    if len(contrasena) < MINIMO:
        raise ComposicionInvalida(f"La contraseña tiene que tener al menos {MINIMO} caracteres.")

    try:
        lector = PdfReader(str(origen))
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo leer {origen.name}: {fallo}") from fallo

    if lector.is_encrypted:
        raise ComposicionInvalida(
            f"{origen.name} ya está protegido. Quítale la contraseña primero si quieres cambiarla."
        )

    escritor = PdfWriter()
    for pagina in lector.pages:
        escritor.add_page(pagina)
    escritor.encrypt(contrasena, algorithm=ALGORITMO)

    with open(destino, "wb") as salida:
        escritor.write(salida)

    return len(lector.pages)


def quitar_contrasena(origen: str | Path, destino: str | Path, contrasena: str) -> int:
    """Escribe una copia sin cifrar, usando la clave que ya se tiene."""
    from pypdf import PdfReader, PdfWriter

    origen, destino = Path(origen), Path(destino)

    try:
        lector = PdfReader(str(origen))
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo leer {origen.name}: {fallo}") from fallo

    if not lector.is_encrypted:
        raise ComposicionInvalida(f"{origen.name} no pide contraseña: no hay nada que quitar.")

    try:
        abierto = lector.decrypt(contrasena or "")
    except Exception as fallo:
        raise ComposicionInvalida(f"No se pudo abrir {origen.name}: {fallo}") from fallo

    if not abierto:
        raise ContrasenaIncorrecta("Esa contraseña no abre el archivo.")

    escritor = PdfWriter()
    for pagina in lector.pages:
        escritor.add_page(pagina)

    with open(destino, "wb") as salida:
        escritor.write(salida)

    return len(lector.pages)
