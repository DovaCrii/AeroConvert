"""Identidad del panel, y lo que sube y baja la gente.

El encabezado es cinco líneas y la que importa: quien entra tiene que saber **en qué
instalación está** antes de tocar nada.
"""

from django.contrib import admin

from .models import ArchivoSubido, Resultado

admin.site.site_header = "AeroConvert — administración"
admin.site.site_title = "AeroConvert"
admin.site.index_title = "Trabajos, bitácora y preajustes"


@admin.register(ArchivoSubido)
class ArchivoSubidoAdmin(admin.ModelAdmin):
    """Lo que hay subido ahora mismo, para poder responder «¿por qué crece el disco?».

    Se puede **borrar** —a diferencia del recibo de un trabajo, que es historia— porque una
    subida es material de trabajo y alguien tiene que poder tirar lo que sobra sin esperar a
    que caduque.
    """

    list_display = ("nombre_original", "owner", "tamano", "created_at", "expires_at")
    list_filter = ("owner", "created_at")
    search_fields = ("nombre_original", "id")
    date_hierarchy = "created_at"
    list_select_related = ("owner",)

    def get_readonly_fields(self, request, obj=None):
        return [campo.name for campo in ArchivoSubido._meta.fields]

    def has_add_permission(self, request):
        """Una subida nace de un formulario, no de aquí."""
        return False

    @admin.display(description="Tamaño")
    def tamano(self, obj):
        return f"{obj.size_bytes / 1_048_576:.1f} MB"


@admin.register(Resultado)
class ResultadoAdmin(admin.ModelAdmin):
    """Los enlaces de descarga vivos.

    Borrar una fila **quita el enlace y no el archivo**: en la carpeta compartida el archivo
    es el entregable de la persona. Es la misma regla que sigue el barrido.
    """

    list_display = ("nombre", "herramienta", "owner", "tamano", "created_at", "expires_at")
    list_filter = ("herramienta", "owner", "created_at")
    search_fields = ("nombre", "ruta", "id")
    date_hierarchy = "created_at"
    list_select_related = ("owner",)

    def get_readonly_fields(self, request, obj=None):
        return [campo.name for campo in Resultado._meta.fields]

    def has_add_permission(self, request):
        return False

    @admin.display(description="Tamaño")
    def tamano(self, obj):
        return f"{obj.size_bytes / 1_048_576:.1f} MB"
