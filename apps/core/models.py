"""Modelo base, bitacora de solo-anexar, y los archivos que suben por el navegador.

`AuditEvent` copia el patron de AeroControl: una tabla que **no se puede actualizar ni
borrar** desde el ORM. Una bitacora que se puede editar no es una bitacora.
"""

import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
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


def donde_guardar(instancia, nombre: str) -> str:
    """`subidas/<id>/<nombre original>`.

    **Una carpeta por archivo** y no todos juntos: el nombre lo elige quien sube, y dos
    personas suben `plano.pdf` el mismo dia. Con todos en la misma carpeta, Django renombra
    el segundo con un sufijo aleatorio y el nombre que la persona reconoce se pierde.
    """
    return f"subidas/{instancia.pk}/{Path(nombre).name}"


class ArchivoSubido(BaseModel):
    """Un archivo que llegó por el navegador, y **es de quien lo subió**.

    ## Para qué, si ya hay una carpeta compartida

    Para lo pequeño. Los planos y las nubes llegan por el recurso de red, que es reanudable y
    no pasa por HTTP; pero obligar a montar una unidad de red para juntar dos PDF que están
    en el escritorio es fricción sin motivo, y juntar PDF es lo que más se hace.

    ## Y es privado, al revés que la carpeta compartida

    Que el equipo vea entera la carpeta de la obra es deliberado. Subir un archivo del propio
    equipo no lo es: la persona eligió algo suyo. Por eso `entrada.resolver()` comprueba el
    dueño, y por eso no hay ninguna URL pública que sirva `MEDIA_ROOT`.

    ## Viven poco

    Una subida es material de trabajo: se convierte o se compone y deja de hacer falta.
    Caduca sola y se la lleva el barrido que ya existe.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subidas"
    )
    archivo = models.FileField(upload_to=donde_guardar)
    #: El nombre que la persona reconoce, aparte porque el del sistema de archivos puede
    #: haberse saneado.
    nombre_original = models.CharField(max_length=255)
    size_bytes = models.BigIntegerField(default=0)
    #: Cuando se la lleva el barrido. Se pone a `None` en cuanto un trabajo la reclama: a
    #: partir de ahi la borra el barrido de entradas al terminar ese trabajo, no el del
    #: tiempo. Dos reglas, una por estado, sin solaparse.
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "archivo subido"
        verbose_name_plural = "archivos subidos"

    def __str__(self) -> str:
        return self.nombre_original

    @property
    def token(self) -> str:
        """Lo que viaja en el formulario. **Nunca la ruta de `MEDIA_ROOT`.**"""
        return f"subida:{self.pk}"

    @property
    def ruta(self) -> Path:
        """Dónde está de verdad, para dársela a pypdf o a GDAL."""
        return Path(self.archivo.path)

    def clean(self):
        """El tope de tamaño, en el único sitio que no se puede evadir.

        nginx y el manejador de subida dan un mensaje que se entiende, pero los dos se saltan
        entrando por la API o por el panel de administración. Este no.
        """
        super().clean()
        tope = int(getattr(settings, "TOPE_MB", 0)) * 1_048_576
        if tope and self.size_bytes > tope:
            raise ValidationError(
                f"{self.nombre_original} pesa {self.size_bytes / 1_048_576:.0f} MB y el tope "
                f"de este servidor son {settings.TOPE_MB} MB. Déjalo en la carpeta compartida "
                "y pega su ruta: para archivos grandes es además mucho más rápido."
            )
