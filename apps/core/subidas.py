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
    _exigir_cuota(usuario, archivo.size)
    subida.archivo.save(subida.nombre_original, archivo, save=False)
    subida.save()
    return subida


def _exigir_cuota(usuario, bytes_nuevos: int) -> None:
    """Que una persona no llene el disco con subidas.

    El tope de `TOPE_MB` es **por archivo**: nada impedía subir veinte de 2 GB seguidos, y cada
    uno vive un día como mínimo (hallazgo A-05 de la auditoría de seguridad). Se suma lo que esa
    persona tiene ahora en el servidor, esté sin usar o reclamado por un trabajo en curso, y se
    rechaza **antes de escribir** si lo nuevo no cabe. `CUOTA_DE_SUBIDAS_MB` en 0 la apaga.
    """
    from django.conf import settings
    from django.core.exceptions import ValidationError
    from django.db.models import Sum

    cuota = int(getattr(settings, "CUOTA_DE_SUBIDAS_MB", 0)) * 1_048_576
    if not cuota:
        return

    ocupado = (
        ArchivoSubido.objects.filter(owner=usuario).aggregate(total=Sum("size_bytes"))["total"] or 0
    )
    if ocupado + bytes_nuevos > cuota:
        raise ValidationError(
            f"Ya tiene {ocupado // 1_048_576} MB subidos que siguen en el servidor, y este "
            f"archivo suma {bytes_nuevos // 1_048_576} MB: el máximo por persona son "
            f"{settings.CUOTA_DE_SUBIDAS_MB} MB. Se borran solos al terminar su trabajo o a "
            f"las {HORAS_DE_VIDA} horas; mientras tanto, déjelos en la carpeta compartida."
        )


def guardar_varios(archivos, *, usuario) -> list[ArchivoSubido]:
    """Las que lleguen de un `<input multiple>`, en orden."""
    return [guardar(archivo, usuario=usuario) for archivo in archivos]
