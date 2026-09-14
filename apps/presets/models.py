"""Preajustes: una conversión guardada con nombre propio.

## Por qué un modelo y no más perfiles en código

Los **perfiles de destino** (`apps/targets/perfiles.py`) son código porque son
conocimiento del dominio: que Civil 3D no lea BigTIFF no depende de la oficina que use la
aplicación. Un **preajuste** sí: «Entrega cliente BHP» es de esta oficina y de este
contrato, y quien lo crea es quien convierte, no quien programa.

De ahí la diferencia de trato: los perfiles se prueban, los preajustes se guardan.

## Y por qué el sembrado va por `slug`

Para que correrlo dos veces no duplique nada. Un `get_or_create` por nombre visible se
rompe en cuanto alguien renombra el preajuste; por `slug` es estable, y el nombre queda
libre para cambiarse.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.core.models import BaseModel


class ConversionPreset(BaseModel):
    """Un destino y sus opciones, con un nombre que alguien reconoce."""

    slug = models.SlugField(max_length=80, unique=True)
    nombre = models.CharField(max_length=120)
    descripcion = models.CharField(max_length=250, blank=True)

    target_format_code = models.CharField(max_length=40)
    #: Cuando viene de un perfil, se recuerda de cuál: así se puede decir «como Civil 3D,
    #: pero con la compresión cambiada» en vez de presentarlo como algo sin relación.
    target_profile_id = models.CharField(max_length=40, blank=True)
    options = models.JSONField(default=dict, blank=True)
    target_crs_code = models.CharField(max_length=16, blank=True)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="preajustes",
    )
    #: Los que trae la aplicación. Se pueden copiar pero no borrar: son el punto de partida
    #: de todos los demás, y perderlos dejaría a alguien sin referencia.
    de_fabrica = models.BooleanField(default=False)
    veces_usado = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-de_fabrica", "-veces_usado", "nombre"]
        permissions = [("compartir_conversionpreset", "Puede compartir un preajuste")]

    def __str__(self) -> str:
        return self.nombre

    @classmethod
    def visibles_para(cls, usuario):
        """Los de fábrica, más los de quien pregunta. **Y nada más.**

        Está aquí y no repetido en cada vista a propósito: la regla se olvidó en tres sitios
        —la lista, el desplegable de la pantalla de convertir y el borrado— y en uno de ellos
        dejaba que cualquiera borrase el preajuste de otro. Una regla escrita cuatro veces es
        una regla que alguien va a escribir mal.
        """
        return cls.objects.filter(models.Q(de_fabrica=True) | models.Q(owner=usuario))

    @classmethod
    def propios_de(cls, usuario):
        """Solo los suyos: los de fábrica no son de nadie."""
        return cls.objects.filter(de_fabrica=False, owner=usuario)

    @property
    def editable(self) -> bool:
        return not self.de_fabrica

    @property
    def nombre_destino(self) -> str:
        """El nombre del formato de destino, resuelto aquí y no en la plantilla.

        Encadenar filtros para buscar en un diccionario es la forma de que una plantilla se
        vuelva ilegible y encima devuelva lo que no era.
        """
        from apps.formats import catalogo

        formato = catalogo.FORMATOS.get(self.target_format_code)
        return formato.nombre if formato else self.target_format_code

    def usar(self) -> None:
        """Suma un uso, sin tocar el resto de la fila."""
        type(self).objects.filter(pk=self.pk).update(veces_usado=models.F("veces_usado") + 1)


#: Los preajustes que trae la aplicación, derivados de los perfiles de destino.
#:
#: Se derivan y no se copian a mano justo por lo que pasó con las claves de las opciones: si
#: mañana el perfil de Civil 3D cambia su compresión, el preajuste de fábrica la hereda sin
#: que nadie tenga que acordarse.
def de_fabrica_deseados() -> list[dict]:
    from apps.targets import perfiles as perfiles_mod

    deseados = []
    for perfil in perfiles_mod.PERFILES.values():
        deseados.append(
            {
                "slug": slugify(f"perfil-{perfil.id}"),
                "nombre": perfil.nombre,
                "descripcion": perfil.descripcion,
                "target_format_code": perfil.formato_destino,
                "target_profile_id": perfil.id,
                "options": dict(perfil.opciones),
            }
        )
    return deseados


def sembrar() -> tuple[int, int]:
    """Crea o actualiza los preajustes de fábrica. Devuelve (creados, actualizados).

    Es idempotente: correrlo dos veces no duplica. Y **actualiza** los de fábrica en vez de
    dejarlos como estaban, porque su verdad vive en el perfil del que salen -- si el perfil
    corrige una opción, el preajuste tiene que corregirse también.
    """
    creados = 0
    actualizados = 0
    for deseado in de_fabrica_deseados():
        slug = deseado.pop("slug")
        objeto, creado = ConversionPreset.objects.update_or_create(
            slug=slug, defaults={**deseado, "de_fabrica": True}
        )
        if creado:
            creados += 1
        else:
            actualizados += 1
    return creados, actualizados
