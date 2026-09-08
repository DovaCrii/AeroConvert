"""Modelo base y bitacora de solo-anexar.

`AuditEvent` copia el patron de AeroControl: una tabla que **no se puede actualizar ni
borrar** desde el ORM. Una bitacora que se puede editar no es una bitacora.
"""

import uuid

from django.db import models


class BaseModel(models.Model):
    """Identificador opaco y las dos fechas que siempre se acaban necesitando.

    El identificador es UUID y no un entero autoincremental porque estos objetos aparecen
    en URLs que la gente comparte por correo, y un entero deja adivinar cuantos trabajos ha
    hecho la oficina.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AppendOnlyQuerySet(models.QuerySet):
    """Levanta en `update()` y `delete()`. No es un adorno: es la unica forma de que la
    bitacora signifique algo cuando alguien tenga que reconstruir que paso."""

    def update(self, **kwargs):
        raise NotImplementedError("La bitacora es de solo anexar: no se actualiza.")

    def delete(self):
        raise NotImplementedError("La bitacora es de solo anexar: no se borra.")
