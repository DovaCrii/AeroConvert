"""El historial de las sondas: «el día que GDAL desapareció».

La matriz de capacidades se calcula **en vivo** cada vez que alguien la mira, así que dice cómo
está el equipo ahora y nada de cómo estaba ayer. Cuando una conversión que funcionaba deja de
funcionar, la pregunta es *desde cuándo* y *qué cambió*: sin un historial hay que adivinarlo.

Se guarda **una fila por cambio, no una por mirada**: la primera vez que se ve un motor y cada vez
que cambia su disponibilidad, su motivo o su versión. Las miradas que no cambian nada no escriben.
"""

from django.db import models
from django.utils import timezone


class RegistroDeSonda(models.Model):
    motor = models.CharField(max_length=60, db_index=True)
    disponible = models.BooleanField()
    codigo_motivo = models.CharField(max_length=60, blank=True)
    mensaje = models.TextField(blank=True)
    version = models.CharField(max_length=120, blank=True)
    visto_en = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ("-visto_en", "-id")
        indexes = [models.Index(fields=["motor", "-visto_en"])]

    def __str__(self) -> str:
        estado = "disponible" if self.disponible else f"apagado ({self.codigo_motivo})"
        return f"{self.motor}: {estado}"
