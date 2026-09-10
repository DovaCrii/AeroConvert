"""El trabajo de conversion y su bitacora.

## Por que la fila nace `encolado` y solo se voltea al final

Un proceso que muere sin levantar excepcion -- GDAL agotando la memoria, por ejemplo -- no
deja escrito que fallo. Si la fila se marcara `hecho` al arrancar, ese trabajo quedaria como
un exito falso para siempre. Naciendo `encolado` y volteando a `hecho` solo tras verificar,
un trabajo muerto queda en `ejecutando` sin `finished_at`, que es **detectable**. Con
`heartbeat_at` ademas es accionable: el despachador lo encuentra y lo voltea a `error`.

Es la leccion de `AeroControl/apps/core/jobs.py`, aqui con el latido que le faltaba.

## Y por que reintentar crea una fila nueva

Un contador que se incrementa borra la historia: se pierde con que motor fallo, con que
version, y cuanto tardo en fallar. Una fila nueva con `retry_of` conserva las dos.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import AppendOnlyQuerySet, BaseModel

# --- Estados ---------------------------------------------------------------

BORRADOR = "draft"
ENCOLADO = "queued"
EJECUTANDO = "running"
VERIFICANDO = "verifying"
HECHO = "done"
ERROR = "error"
CANCELADO = "cancelled"
CADUCADO = "expired"

ESTADOS = [
    (BORRADOR, _("Draft")),
    (ENCOLADO, _("Queued")),
    (EJECUTANDO, _("Running")),
    (VERIFICANDO, _("Verifying")),
    (HECHO, _("Done")),
    (ERROR, _("Error")),
    (CANCELADO, _("Cancelled")),
    (CADUCADO, _("Expired")),
]

#: Estados de los que ya no se sale. La interfaz deja de sondear en cuanto llega a uno.
TERMINALES = frozenset({HECHO, ERROR, CANCELADO, CADUCADO})

# --- Etapas ----------------------------------------------------------------
# Se nombran porque un porcentaje solo no dice nada: «43 %» durante diez minutos parece un
# cuelgue, y «calculando la huella, 43 %» no.

HUELLA = "huella"
INSPECCION = "inspeccion"
CONVERSION = "conversion"
VERIFICACION = "verificacion"

ETAPAS = [
    (HUELLA, _("Fingerprint")),
    (INSPECCION, _("Inspection")),
    (CONVERSION, _("Conversion")),
    (VERIFICACION, _("Verification")),
]

#: Cuanto pesa cada etapa en la barra. La huella no es despreciable: sobre un archivo de
#: 40 GB son minutos de leer el disco entero.
PESO_DE_ETAPA = {HUELLA: 0.10, INSPECCION: 0.02, CONVERSION: 0.83, VERIFICACION: 0.05}


class ConversionJob(BaseModel):
    """Una conversion pedida, con todo lo que hace falta para reconstruir que paso."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="trabajos"
    )

    # --- Origen ------------------------------------------------------------
    #: Modo taller: ruta absoluta elegida por la persona. **El archivo no se copia ni se
    #: mueve nunca.**
    source_path = models.CharField(max_length=1000, blank=True)
    #: Modo nube unicamente.
    source_upload = models.FileField(upload_to="entradas/%Y/%m/", blank=True)
    source_name = models.CharField(max_length=255)
    source_size_bytes = models.BigIntegerField(default=0)
    #: **Del original**, no de la salida. Es la prueba de que entregable se convirtio, y no
    #: cambia aunque cambie la version del conversor.
    source_sha256 = models.CharField(max_length=64, blank=True)
    source_format_code = models.CharField(max_length=40, blank=True)
    #: `firma` / `gdal` / `extension` / `desconocido`. Se guarda porque un formato supuesto
    #: por la extension y uno reconocido por su contenido no merecen la misma confianza.
    source_format_confidence = models.CharField(max_length=16, blank=True)

    # --- Sistema de referencia ---------------------------------------------
    source_crs_authority = models.CharField(max_length=16, blank=True)
    source_crs_code = models.CharField(max_length=16, blank=True)
    source_crs_wkt = models.TextField(blank=True)
    #: `incrustado` / `sidecar-prj` / `declarado` / `desconocido`. Que lo declarara una
    #: persona es justo el dato que hace falta el dia que algo aparezca en otro pais.
    source_crs_origin = models.CharField(max_length=16, blank=True)
    target_crs_authority = models.CharField(max_length=16, blank=True)
    target_crs_code = models.CharField(max_length=16, blank=True)

    # --- Destino -----------------------------------------------------------
    target_format_code = models.CharField(max_length=40)
    target_profile_id = models.CharField(max_length=40, blank=True)
    engine_id = models.CharField(max_length=60, blank=True)
    #: Se congela al arrancar. Un «ayer funcionaba» se diagnostica con esto.
    engine_version = models.CharField(max_length=200, blank=True)
    options = models.JSONField(default=dict, blank=True)

    # --- Estado ------------------------------------------------------------
    status = models.CharField(max_length=16, choices=ESTADOS, default=ENCOLADO, db_index=True)
    #: Codigo estable, **nunca traducido**. Ver `apps/jobs/motivos.py`.
    reason_code = models.CharField(max_length=40, blank=True)
    #: El mensaje para la persona. Este si se traduce.
    reason_detail = models.TextField(blank=True)

    progress_percent = models.PositiveSmallIntegerField(default=0)
    progress_stage = models.CharField(max_length=24, choices=ETAPAS, blank=True)
    progress_updated_at = models.DateTimeField(null=True, blank=True)
    #: Sin esto, un obrero muerto deja el trabajo en `ejecutando` para siempre.
    heartbeat_at = models.DateTimeField(null=True, blank=True)

    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    retry_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reintentos"
    )

    queued_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cancel_requested_at = models.DateTimeField(null=True, blank=True)

    worker_pid = models.PositiveIntegerField(null=True, blank=True)
    worker_host = models.CharField(max_length=80, blank=True)

    # --- Salida ------------------------------------------------------------
    output_path = models.CharField(max_length=1000, blank=True)
    output_size_bytes = models.BigIntegerField(default=0)
    output_sha256 = models.CharField(max_length=64, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verification = models.JSONField(default=dict, blank=True)
    #: Solo en modo nube: barrido de retencion.
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # El despachador consulta exactamente esto cada dos segundos.
            models.Index(fields=["status", "queued_at"], name="job_cola_idx"),
        ]
        permissions = [
            ("cancelar_conversionjob", "Puede cancelar un trabajo de conversion"),
            ("reencolar_conversionjob", "Puede reencolar un trabajo"),
        ]

    def __str__(self) -> str:
        return f"{self.source_name} -> {self.target_format_code} [{self.status}]"

    # --- Consultas de estado ------------------------------------------------

    @property
    def es_terminal(self) -> bool:
        return self.status in TERMINALES

    @property
    def nombre_del_destino(self) -> str:
        """«GeoTIFF clásico» y no `geotiff`.

        `target_format_code` es la clave interna, en minúscula y sin espacios porque tiene
        que ser estable. Enseñarla tal cual en el historial obliga a quien lee a traducir
        `gpkg` o `xyz_nube` mentalmente, y a `landxml` le quita las mayúsculas que sí tiene.
        El nombre bonito ya existe en el catálogo, traducido incluido.
        """
        from apps.formats import catalogo

        formato = catalogo.FORMATOS.get(self.target_format_code)
        return str(formato.nombre) if formato else self.target_format_code

    @property
    def cancelacion_pedida(self) -> bool:
        return self.cancel_requested_at is not None

    @property
    def duracion_s(self) -> float | None:
        if not self.started_at:
            return None
        fin = self.finished_at or timezone.now()
        return (fin - self.started_at).total_seconds()

    @property
    def reduccion(self) -> float | None:
        """Cuanto encogio, en tanto por uno. `None` si aun no hay salida."""
        if not (self.source_size_bytes and self.output_size_bytes):
            return None
        return 1 - (self.output_size_bytes / self.source_size_bytes)

    @property
    def reduccion_pct(self) -> int | None:
        """Lo mismo en porcentaje, listo para la plantilla.

        Existe para que el recibo no tenga que encadenar filtros para multiplicar por cien:
        una cifra que el cliente va a leer no se calcula con `floatformat`.
        """
        reduccion = self.reduccion
        return None if reduccion is None else int(round(reduccion * 100))

    @property
    def intervalo_de_sondeo_s(self) -> int:
        """Cada cuanto pregunta el navegador.

        Escala con el tiempo transcurrido: un trabajo de tres horas no puede generar 10.800
        peticiones. Al principio se sondea rapido porque es cuando la persona esta mirando.
        """
        transcurrido = self.duracion_s or 0
        if transcurrido < 30:
            return 1
        if transcurrido < 300:
            return 2
        return 5

    @property
    def es_reintentable(self) -> bool:
        from . import motivos

        return (
            self.status == ERROR
            and motivos.es_reintentable(self.reason_code)
            and self.attempt_count < self.max_attempts
        )

    # --- Transiciones -------------------------------------------------------

    def marcar_progreso(self, etapa: str, fraccion: float) -> None:
        """Actualiza la barra. `fraccion` es 0..1 **dentro de la etapa**, no del total.

        Se guardan solo los campos que cambian: esta fila se escribe cada pocos segundos
        mientras el navegador la lee, y un `save()` entero multiplicaria las escrituras.
        """
        completadas = 0.0
        for nombre, peso in PESO_DE_ETAPA.items():
            if nombre == etapa:
                break
            completadas += peso
        total = completadas + PESO_DE_ETAPA.get(etapa, 0.0) * max(0.0, min(1.0, fraccion))

        ahora = timezone.now()
        self.progress_stage = etapa
        self.progress_percent = int(round(total * 100))
        self.progress_updated_at = ahora
        self.heartbeat_at = ahora
        self.save(
            update_fields=[
                "progress_stage",
                "progress_percent",
                "progress_updated_at",
                "heartbeat_at",
                "updated_at",
            ]
        )

    def registrar(self, mensaje: str, *, nivel: str = "info", etapa: str = "", **carga) -> JobEvent:
        return JobEvent.anexar(self, mensaje, nivel=nivel, etapa=etapa, **carga)


class JobEvent(BaseModel):
    """La bitacora. **De solo anexar**: una bitacora que se puede editar no es una bitacora."""

    INFO = "info"
    AVISO = "warn"
    ERROR = "error"
    NIVELES = [(INFO, _("Info")), (AVISO, _("Warning")), (ERROR, _("Error"))]

    #: Tope de la cola de stderr que se guarda. GDAL con `CPL_DEBUG=ON` escupe megabytes, y
    #: una fila de base de datos no es un archivo de registro.
    MAXIMO_STDERR = 16 * 1024

    job = models.ForeignKey(ConversionJob, on_delete=models.CASCADE, related_name="eventos")
    sequence = models.PositiveBigIntegerField()
    level = models.CharField(max_length=8, choices=NIVELES, default=INFO)
    stage = models.CharField(max_length=24, blank=True)
    message = models.TextField()
    reason_code = models.CharField(max_length=40, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ["sequence"]
        unique_together = [("job", "sequence")]

    def __str__(self) -> str:
        return f"[{self.level}] {self.message[:60]}"

    @classmethod
    def anexar(
        cls, job: ConversionJob, mensaje: str, *, nivel: str = INFO, etapa: str = "", **carga
    ):
        stderr = carga.get("stderr_cola")
        if isinstance(stderr, str) and len(stderr) > cls.MAXIMO_STDERR:
            carga["stderr_cola"] = stderr[-cls.MAXIMO_STDERR :]
            carga["stderr_recortado"] = True

        siguiente = (
            cls.objects.filter(job=job).aggregate(models.Max("sequence"))["sequence__max"] or 0
        ) + 1
        return cls.objects.create(
            job=job,
            sequence=siguiente,
            level=nivel,
            stage=etapa,
            message=mensaje,
            reason_code=carga.pop("reason_code", ""),
            payload=carga,
        )
