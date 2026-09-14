"""Guardar lo que llegó por el formulario.

El modelo vive en `models.py` —que es donde Django los busca— y aquí queda lo que no es
modelo: cuánto viven y cómo se escribe uno.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path

from django.utils import timezone

from .models import ArchivoSubido

#: Cuanto sobrevive una subida que nadie reclamo. Un dia: mas que de sobra para una tarde de
#: trabajo, y poco para que el disco no se llene de cosas que ya no le importan a nadie.
HORAS_DE_VIDA = 24


def guardar(archivo, *, usuario) -> ArchivoSubido:
    """Escribe el archivo y devuelve la fila.

    Levanta `ValidationError` si pasa del tope, y lo hace **antes** de escribir nada: es la
    tercera de las tres comprobaciones de tamaño, y la única inevadible.
    """
    subida = ArchivoSubido(
        pk=uuid.uuid4(),
        owner=usuario,
        nombre_original=Path(archivo.name).name[:255],
        size_bytes=archivo.size,
        expires_at=timezone.now() + timedelta(hours=HORAS_DE_VIDA),
    )
    subida.clean()
    subida.archivo.save(subida.nombre_original, archivo, save=False)
    subida.save()
    return subida


def guardar_varios(archivos, *, usuario) -> list[ArchivoSubido]:
    """Las que lleguen de un `<input multiple>`, en orden."""
    return [guardar(archivo, usuario=usuario) for archivo in archivos]


#: Cuanto se puede volver a bajar un resultado. Tres dias: lo que dura un fin de semana mas
#: el lunes por la manana, que es cuando alguien vuelve a por lo que hizo el viernes.
HORAS_DE_RESULTADO = 72


def anotar_resultado(ruta, *, usuario, herramienta: str):
    """Deja constancia de un archivo recién escrito para poder ofrecerlo de vuelta.

    Devuelve la fila, o `None` si el archivo no está — que no es un fallo digno de tumbar la
    pantalla: el trabajo ya se hizo y la ruta se enseña igual.
    """
    from .models import Resultado

    ruta = Path(ruta)
    try:
        tamano = ruta.stat().st_size
    except OSError:  # pragma: no cover
        return None

    return Resultado.objects.create(
        owner=usuario,
        ruta=str(ruta),
        nombre=ruta.name,
        size_bytes=tamano,
        herramienta=herramienta,
        expires_at=timezone.now() + timedelta(hours=HORAS_DE_RESULTADO),
    )
