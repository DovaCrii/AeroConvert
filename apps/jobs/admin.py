"""El panel de administración de los trabajos.

Sin esto, quien administre la instalación **no ve nada**: ni un trabajo, ni su bitácora, ni
por qué falló. La única lista que existía filtra por dueño, así que ni siquiera entrando como
administrador se ven los trabajos de los demás.

## El recibo es un recibo, y por eso es de solo lectura

`ConversionJob` **es** el recibo, y conservarlo es una promesa de la aplicación: sobrevive al
archivo. Un panel que dejara editarlo convertiría la auditoría en una ficha editable, y el
`sha256` del original dejaría de significar nada.

Así que aquí no se edita: se **actúa**. Cancelar, recoger y reencolar son acciones, y hacen
exactamente lo mismo que los botones de la aplicación.
"""

from django.contrib import admin, messages
from django.utils import timezone

from .models import TERMINALES, ConversionJob, JobEvent


class BitacoraEnLinea(admin.TabularInline):
    model = JobEvent
    extra = 0
    # **Obligatorio, no cosmetico.** `JobEvent.objects` es un `AppendOnlyQuerySet` que
    # levanta `NotImplementedError` en `delete()` y en `update()`. Una casilla de borrado
    # aqui produciria un 500 opaco.
    can_delete = False
    fields = ("created_at", "level", "stage", "reason_code", "message")
    readonly_fields = fields
    ordering = ("sequence",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ConversionJob)
class ConversionJobAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "source_name",
        "target_format_code",
        "status",
        "progress_percent",
        "owner",
        "engine_id",
        "duracion_legible",
    )
    list_filter = ("status", "target_format_code", "engine_id", "reason_code", "created_at")
    search_fields = ("source_name", "source_path", "output_path", "source_sha256", "id")
    date_hierarchy = "created_at"
    # Sin esto, una consulta por fila solo para pintar el dueno.
    list_select_related = ("owner",)
    autocomplete_fields = ()
    inlines = [BitacoraEnLinea]

    fieldsets = (
        (
            "Origen",
            {
                "fields": (
                    "owner",
                    "source_name",
                    "source_path",
                    "source_size_bytes",
                    "source_sha256",
                    "source_format_code",
                    "source_format_confidence",
                )
            },
        ),
        (
            "Sistema de referencia",
            {
                "fields": (
                    "source_crs_authority",
                    "source_crs_code",
                    "source_crs_origin",
                    "target_crs_authority",
                    "target_crs_code",
                )
            },
        ),
        ("Destino", {"fields": ("target_format_code", "target_profile_id", "options")}),
        (
            "Estado",
            {
                "fields": (
                    "status",
                    "reason_code",
                    "reason_detail",
                    "progress_percent",
                    "progress_stage",
                    "queued_at",
                    "started_at",
                    "finished_at",
                    "cancel_requested_at",
                )
            },
        ),
        (
            "Obrero",
            {
                "fields": (
                    "engine_id",
                    "engine_version",
                    "worker_pid",
                    "worker_host",
                    "heartbeat_at",
                    "attempt_count",
                    "retry_of",
                )
            },
        ),
        (
            "Salida",
            {
                "fields": (
                    "output_path",
                    "output_size_bytes",
                    "output_sha256",
                    "verified_at",
                    "verification",
                    "expires_at",
                )
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        """Todos. Ver el docstring del módulo."""
        return [campo.name for campo in ConversionJob._meta.fields]

    def has_add_permission(self, request):
        """Un trabajo nace de la pantalla de convertir, siempre."""
        return False

    def has_delete_permission(self, request, obj=None):
        """El recibo sobrevive al archivo. Esa es la promesa."""
        return False

    @admin.display(description="Duración")
    def duracion_legible(self, obj):
        segundos = obj.duracion_s
        if not segundos:
            return "—"
        return f"{segundos:.0f} s" if segundos < 90 else f"{segundos / 60:.1f} min"

    actions = ("pedir_cancelacion", "recoger_interrumpidos")

    @admin.action(description="Pedir la cancelación")
    def pedir_cancelacion(self, request, queryset):
        """No mata nada: el runner mira este campo en cada latido, igual que con el botón."""
        cuantos = queryset.exclude(status__in=TERMINALES).update(cancel_requested_at=timezone.now())
        self.message_user(request, f"Cancelación pedida para {cuantos} trabajo(s).")

    @admin.action(description="Recoger los que perdieron su obrero")
    def recoger_interrumpidos(self, request, queryset):
        """El `manage.py procesar_trabajos --recoger` sin entrar por SSH."""
        from . import despachador

        recogidos = despachador.recoger_muertos()
        self.message_user(request, f"Recogidos {recogidos} trabajos interrumpidos.", messages.INFO)


@admin.register(JobEvent)
class JobEventAdmin(admin.ModelAdmin):
    """Registrada aparte para poder buscar un `reason_code` en toda la instalación."""

    list_display = ("created_at", "job", "level", "stage", "reason_code", "resumen")
    list_filter = ("level", "reason_code", "created_at")
    search_fields = ("message", "reason_code")
    date_hierarchy = "created_at"
    list_select_related = ("job",)

    def get_readonly_fields(self, request, obj=None):
        return [campo.name for campo in JobEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        """Es de solo añadir de verdad: `delete()` levanta."""
        return False

    @admin.display(description="Mensaje")
    def resumen(self, obj):
        texto = obj.message or ""
        return texto if len(texto) <= 80 else texto[:77] + "…"
