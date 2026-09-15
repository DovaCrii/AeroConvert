"""Identidad del panel, y lo que sube y baja la gente.

El encabezado es cinco líneas y la que importa: quien entra tiene que saber **en qué
instalación está** antes de tocar nada.
"""

from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import ArchivoSubido, Resultado

admin.site.site_header = "AeroConvert — administración"
admin.site.site_title = "AeroConvert"
admin.site.index_title = "Trabajos, bitácora y preajustes"

Usuario = get_user_model()


class AltaDeCuenta(forms.ModelForm):
    """El alta que pide el correo, porque es con lo que se entra.

    El formulario de fábrica pide nombre de usuario y contraseña **y nada más**: el correo se
    rellena después, en una segunda pantalla que nadie visita. Con el correo como puerta, una
    cuenta sin correo es una cuenta con la que no se puede entrar — creada, guardada, y
    silenciosamente inútil hasta que alguien lo descubre intentándolo.
    """

    correo = forms.EmailField(
        label="Correo",
        help_text="Es con lo que entra esta persona, y por donde se le puede escribir.",
    )

    class Meta:
        model = Usuario
        fields = ()

    def clean_correo(self):
        correo = self.cleaned_data["correo"].strip()
        # **Uno por cuenta.** `auth.User` no lo declara único, así que si no se mira aquí se
        # pueden crear dos con el mismo — y entonces ninguna de las dos entra, porque el
        # backend se niega a elegir. Ver `apps/core/autenticacion.py`.
        if Usuario._default_manager.filter(email__iexact=correo).exists():
            raise forms.ValidationError("Ya hay una cuenta con ese correo.")
        return correo


class CuentaAdmin(UserAdmin):
    """El panel de cuentas, con el correo delante.

    Es la pantalla por la que se da de alta al equipo, así que lo que se ve en la lista es lo
    que hace falta para responder «¿quién tiene acceso y con qué correo?».
    """

    list_display = ("email", "username", "first_name", "last_name", "is_staff", "is_active")
    list_filter = ("is_staff", "is_active")
    search_fields = ("email", "username", "first_name", "last_name")
    ordering = ("email",)

    add_form = AltaDeCuenta
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "correo", "usable_password", "password1", "password2"),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        """El correo del formulario al campo del modelo.

        Va por un campo propio (`correo`) y no por el `email` del modelo porque ese es
        opcional, y lo que hace falta es que **no** lo sea al crear. Exigirlo así no obliga a
        tocar `auth.User`, que es una migración que no se paga con la base ya en producción.
        """
        if not change and "correo" in form.cleaned_data:
            obj.email = form.cleaned_data["correo"]
        super().save_model(request, obj, form, change)


admin.site.unregister(Usuario)
admin.site.register(Usuario, CuentaAdmin)


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
