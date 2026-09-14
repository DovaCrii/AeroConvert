"""De dónde sale un archivo: de una ruta del disco, o de una subida.

Es **la puerta única** de la aplicación, y sustituye a llamar a `comprobar_ruta()` por su
cuenta desde nueve sitios. Todo lo que hay detrás —la inspección, los motores, las
herramientas de PDF— sigue recibiendo un `Path` y no se entera de nada.

## Cuál es cuál lo dice un prefijo, no una adivinanza

Una subida se escribe `subida:<uuid>`. Y si algo empieza por ese prefijo pero no es un
identificador válido de quien pregunta, **es un error y se para**: nunca se cae de vuelta a
interpretarlo como ruta. Adivinar es exactamente cómo una de las dos vías se cuela por la
puerta de la otra.

## Y una subida es de quien la subió

La carpeta compartida la ve el equipo entero, y eso es deliberado: es la carpeta de la obra.
Pero subir un archivo del propio equipo es un acto privado, así que aquí sí se comprueba el
dueño. Es además lo que permite que la miniatura de un PDF subido no sea legible por
cualquiera que acierte un identificador.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ValidationError

from . import modo

#: Lo que marca una subida. Con dos puntos porque **no puede aparecer al principio de una
#: ruta**: en Windows el segundo caracter de `D:\...` son los dos puntos, nunca el primero, y
#: en POSIX una ruta empieza por `/` o por una letra.
PREFIJO = "subida:"


class EntradaNoPermitida(modo.RutaNoPermitida):
    """No se puede usar ese origen.

    Hereda de `RutaNoPermitida` **a proposito**: las nueve vistas que ya la capturan siguen
    funcionando sin tocar un solo `except`.
    """


@dataclass(frozen=True)
class Origen:
    """Un archivo del que partir, venga de donde venga."""

    ruta: Path
    #: El nombre que la persona reconoce. Para una subida es el que tenía en su equipo, no el
    #: que quedó en el servidor.
    nombre: str
    subida: object | None = None

    @property
    def token(self) -> str:
        """Lo que se devuelve al formulario para el siguiente paso.

        **Para una subida es su identificador, nunca su ruta en el servidor.** Es la única
        línea de este módulo donde equivocarse sería una fuga: devolver la ruta real dejaría
        que el POST siguiente la usara como si fuera una ruta del disco.
        """
        return self.subida.token if self.subida is not None else str(self.ruta)

    @property
    def es_subida(self) -> bool:
        return self.subida is not None


def resolver(crudo: str, *, usuario) -> Origen:
    """Una ruta del disco **o** `subida:<uuid>`, resuelta a algo con un `Path` dentro."""
    texto = (crudo or "").strip().strip('"')
    if not texto:
        raise EntradaNoPermitida("No indicaste ningún archivo.", "ruta-no-permitida")

    if texto.startswith(PREFIJO):
        return _de_una_subida(texto[len(PREFIJO) :].strip(), usuario=usuario)

    ruta = modo.comprobar_ruta(texto)
    return Origen(ruta=ruta, nombre=ruta.name)


def _de_una_subida(identificador: str, *, usuario) -> Origen:
    from .subidas import ArchivoSubido

    # `ValidationError` porque un identificador mal formado lo levanta el propio campo UUID
    # al preparar la consulta, no el `get()`.
    try:
        subida = ArchivoSubido.objects.get(pk=identificador, owner=usuario)
    except (ArchivoSubido.DoesNotExist, ValidationError, ValueError, TypeError) as fallo:
        # **Mismo mensaje para «no existe» y para «no es tuya»**, por lo mismo que las fichas
        # de trabajo dan 404 y no 403: distinguirlos confirmaria que un identificador ajeno
        # es valido.
        raise EntradaNoPermitida(
            "Ese archivo subido ya no está. Vuelve a subirlo.", "origen-no-legible"
        ) from fallo

    ruta = subida.ruta
    if not ruta.exists():
        raise EntradaNoPermitida(
            f"{subida.nombre_original} ya no está en el servidor: caducó o se barrió.",
            "origen-no-legible",
        )
    return Origen(ruta=ruta, nombre=subida.nombre_original, subida=subida)


def resolver_varios(texto: str, *, usuario, maximo: int) -> list[Origen]:
    """Un origen por línea, que es como viaja la lista de «unir» y de «imágenes a PDF».

    El tope cuenta **las dos vías juntas**: si no, alguien sube veinte y pega otras veinte.
    """
    origenes: list[Origen] = []
    for linea in (texto or "").splitlines():
        if not linea.strip():
            continue
        origenes.append(resolver(linea, usuario=usuario))
        if len(origenes) >= maximo:
            break
    return origenes
