"""Cuanto sobrevive lo que se escribe, y cuanto disco se deja gastar.

## Lo que no se puede evitar

GDAL necesita **un archivo de verdad, con acceso aleatorio**, tanto de entrada como de
salida. No hay forma de convertir un GeoTIFF «al vuelo» desde el flujo HTTP: el formato
exige saltar por dentro del archivo -- leer la cabecera, ir al indice de teselas, volver.
`/vsistdin/` existe pero solo sirve para formatos secuenciales, que no son estos.

Asi que **algo toca disco siempre**. Lo que si se puede garantizar es que no sobreviva a la
peticion, y eso es lo que hace este modulo.

## Y lo que de verdad protege el disco

No es la politica de borrado: es el **presupuesto**. Borrar al terminar no impide que tres
conversiones simultaneas de 40 GB llenen el volumen a la vez. Lo que lo impide es medir
antes de arrancar y hacer esperar al trabajo que no cabe.

Un servidor que se queda sin disco no devuelve un error: deja de funcionar entero, y
normalmente se lleva la base de datos por delante.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

#: Nada sobrevive a la descarga. Es la politica para un servicio compartido.
EFIMERA = "efimera"
#: Se guarda unas horas y se barre. Util para un equipo pequeno que rehace entregas.
TEMPORAL = "temporal"
#: No se barre nunca. Es lo correcto en modo taller: la salida vive junto al original, en
#: el disco de quien la pidio, y borrarla seria borrarle su entregable.
PERMANENTE = "permanente"

POLITICAS = (EFIMERA, TEMPORAL, PERMANENTE)

#: Marcas de los archivos de trabajo que nunca deberian sobrevivir a un trabajo. Si el
#: proceso muere a media conversion, quedan huerfanos y hay que ir a buscarlos.
#:
#: Se buscan **dentro** del nombre y no como sufijo final, porque `ruta_parcial()` conserva
#: la extension: el archivo se llama `nube.parcial.copc.laz`, no `nube.copc.laz.parcial`.
#: Buscar por sufijo dejaria de encontrarlos, y se acumularian hasta llenar el disco.
MARCAS_DE_TRABAJO = (".parcial.", ".parcial", ".prueba", ".enuso")


def politica() -> str:
    """La politica configurada, con el valor por omision que corresponde al modo.

    En taller es `permanente` a proposito: la salida se escribe junto al original, en el
    disco de la persona. Barrerla seria borrarle su entregable.
    """
    configurada = (getattr(settings, "RETENCION", "") or "").strip().lower()
    if configurada in POLITICAS:
        return configurada
    return PERMANENTE if settings.MODO == settings.MODO_TALLER else EFIMERA


def carpeta_de_trabajo() -> Path:
    """Donde viven las salidas mientras esperan a ser descargadas.

    Una carpeta propia y no el directorio temporal del sistema: asi el presupuesto se puede
    medir, el barrido sabe donde mirar, y un despliegue puede ponerla en otro volumen que
    no sea el del sistema.
    """
    ruta = Path(getattr(settings, "CARPETA_DE_TRABAJO", "") or (settings.BASE_DIR / "trabajo"))
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def caducidad_para(politica_actual: str | None = None):
    """Cuando caduca una salida recien hecha. `None` = no caduca."""
    actual = politica_actual or politica()
    if actual == PERMANENTE:
        return None
    if actual == EFIMERA:
        minutos = getattr(settings, "EFIMERA_MINUTOS", 30)
        return timezone.now() + timedelta(minutes=minutos)
    horas = getattr(settings, "RETENCION_HORAS", 24)
    return timezone.now() + timedelta(hours=horas)


# --- El presupuesto ---------------------------------------------------------


@dataclass(frozen=True)
class Presupuesto:
    """Cuanto disco hay, cuanto se esta usando y cuanto haria falta."""

    usado_bytes: int
    tope_bytes: int
    libre_en_disco_bytes: int
    necesario_bytes: int

    @property
    def cabe(self) -> bool:
        # Las dos condiciones son distintas y hacen falta las dos: el tope protege al resto
        # del servidor de nosotros, y el disco libre nos protege a nosotros del resto.
        return (
            self.usado_bytes + self.necesario_bytes <= self.tope_bytes
            and self.necesario_bytes < self.libre_en_disco_bytes
        )

    @property
    def motivo(self) -> str:
        if self.usado_bytes + self.necesario_bytes > self.tope_bytes:
            return (
                f"La carpeta de trabajo ya usa {self.usado_bytes / 1e9:.1f} GB y este trabajo "
                f"necesita {self.necesario_bytes / 1e9:.1f} GB mas, con un tope de "
                f"{self.tope_bytes / 1e9:.1f} GB."
            )
        return (
            f"Quedan {self.libre_en_disco_bytes / 1e9:.1f} GB en el disco y este trabajo "
            f"necesita {self.necesario_bytes / 1e9:.1f} GB."
        )


def usado_bytes() -> int:
    """Cuanto ocupa ahora mismo la carpeta de trabajo."""
    total = 0
    for hijo in carpeta_de_trabajo().rglob("*"):
        try:
            if hijo.is_file():
                total += hijo.stat().st_size
        except OSError:
            continue
    return total


def presupuesto_para(bytes_de_entrada: int) -> Presupuesto:
    """Si cabe un trabajo de ese tamano.

    Se pide **el doble** de la entrada: la salida sin perdida puede quedar del mismo orden,
    y durante un instante conviven el parcial y el definitivo. Es conservador a proposito
    -- equivocarse por arriba hace esperar a alguien, equivocarse por abajo tumba el
    servidor.
    """
    carpeta = carpeta_de_trabajo()
    tope_gb = getattr(settings, "PRESUPUESTO_GB", 20)
    try:
        libre = shutil.disk_usage(carpeta).free
    except OSError:
        libre = 0
    return Presupuesto(
        usado_bytes=usado_bytes(),
        tope_bytes=int(tope_gb * 1_000_000_000),
        libre_en_disco_bytes=libre,
        necesario_bytes=max(0, bytes_de_entrada) * 2,
    )


# --- El barrido -------------------------------------------------------------


@dataclass
class Barrido:
    salidas_caducadas: int = 0
    entradas_borradas: int = 0
    huerfanos: int = 0
    bytes_liberados: int = 0

    def __str__(self) -> str:
        return (
            f"{self.salidas_caducadas} salidas caducadas, "
            f"{self.entradas_borradas} entradas, "
            f"{self.huerfanos} huerfanos, "
            f"{self.bytes_liberados / 1e6:.1f} MB liberados"
        )


def barrer() -> Barrido:
    """Borra lo que ya no tiene por que estar.

    Tres cosas distintas, y cada una por su motivo:

    1. **Salidas caducadas.** Lo que la politica dice que ya no vive.
    2. **Entradas subidas de trabajos terminados.** Estas se borran *siempre*, incluso con
       politica permanente: quien las subio ya las tiene, y guardarlas duplica el archivo
       del cliente en nuestro servidor sin que nadie lo haya pedido.
    3. **Huerfanos.** Un `.parcial` que sobrevivio a un proceso muerto. Nadie los reclama
       nunca, asi que sin barrido se acumulan hasta llenar el disco.
    """
    from .models import TERMINALES, ConversionJob

    resultado = Barrido()
    ahora = timezone.now()

    for job in ConversionJob.objects.filter(
        expires_at__lt=ahora, output_path__gt="", status__in=TERMINALES
    ):
        resultado.bytes_liberados += _borrar_archivo(Path(job.output_path))
        ConversionJob.objects.filter(pk=job.pk).update(output_path="", expires_at=None)
        resultado.salidas_caducadas += 1

    for job in ConversionJob.objects.filter(status__in=TERMINALES).exclude(source_upload=""):
        try:
            resultado.bytes_liberados += job.source_upload.size
            job.source_upload.delete(save=False)
        except (OSError, ValueError):
            pass
        ConversionJob.objects.filter(pk=job.pk).update(source_upload="")
        resultado.entradas_borradas += 1

    resultado.huerfanos, huerfanos_bytes = _barrer_huerfanos()
    resultado.bytes_liberados += huerfanos_bytes
    return resultado


def _en_curso() -> frozenset[str]:
    """Los archivos de trabajo que **ahora mismo** esta escribiendo alguien.

    Se pregunta a la base en vez de mirar la hora. Antes la unica salvaguarda era exigir que
    el archivo tuviera mas de una hora, y el propio comentario admitia la debilidad: el
    nombre no dice de quien es. Con `SEGUNDOS_POR_GB = 900`, una ortofoto de 5 GB pasa de la
    hora sin despeinarse, asi que el barrido le borraba el parcial a un trabajo sano **y la
    conversion moria al final**, despues de todo el trabajo. Con varios obreros era peor.

    Son pocas filas: los trabajos en curso se cuentan con los dedos.
    """
    from apps.engines.base import ruta_parcial

    from .models import EJECUTANDO, ConversionJob

    vivos: set[str] = set()
    for ruta in ConversionJob.objects.filter(status=EJECUTANDO).values_list(
        "output_path", flat=True
    ):
        if not ruta:
            continue
        destino = Path(ruta)
        vivos.add(str(destino))
        vivos.add(str(ruta_parcial(destino)))
    return frozenset(vivos)


def _barrer_huerfanos() -> tuple[int, int]:
    """Archivos de trabajo que sobrevivieron a un proceso muerto.

    Dos condiciones, y la primera es la que importa: **que no lo este escribiendo nadie**. La
    hora se conserva como red de seguridad para lo que ya no figura en la base -- un obrero
    que murio sin dejar rastro --, pero ya no es lo unico que separa un huerfano de un
    trabajo en marcha.
    """
    limite = timezone.now().timestamp() - 3600
    vivos = _en_curso()
    contados = 0
    liberados = 0
    for hijo in carpeta_de_trabajo().rglob("*"):
        if not hijo.is_file() or not any(marca in hijo.name for marca in MARCAS_DE_TRABAJO):
            continue
        if str(hijo) in vivos:
            continue
        try:
            if hijo.stat().st_mtime > limite:
                continue
        except OSError:
            continue
        liberados += _borrar_archivo(hijo)
        contados += 1
    return contados, liberados


def _borrar_archivo(ruta: Path) -> int:
    """Borra y devuelve cuantos bytes se liberaron."""
    try:
        tamano = ruta.stat().st_size
    except OSError:
        return 0
    try:
        ruta.unlink()
    except OSError:
        return 0
    return tamano


def consumir(job) -> int:
    """Borra la salida en cuanto se descarga, si la politica es efimera.

    Devuelve los bytes liberados. Se llama **despues** de servir el archivo, no antes: si
    la descarga se corta a la mitad, la persona tiene que poder reintentarla, y para eso el
    archivo tiene que seguir ahi hasta que la respuesta se complete.
    """
    if politica() != EFIMERA or not job.output_path:
        return 0
    liberados = _borrar_archivo(Path(job.output_path))
    type(job).objects.filter(pk=job.pk).update(output_path="", expires_at=None)
    return liberados
