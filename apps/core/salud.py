"""Si esta instalación está sana, y en qué no.

La sonda anterior devolvía `{"estado": "ok"}` sin mirar nada, lo cual contesta «el proceso
de Python está vivo» — que es justo lo único que systemd ya sabe por su cuenta. Lo que hace
falta saber es lo otro: si la base responde, si el obrero de conversiones sigue ahí, y **si
la carpeta compartida está montada**.

## Por qué la carpeta compartida es la comprobación que importa

Es la que va a fallar de verdad. Un montaje CIFS caído no desaparece: deja un directorio
local vacío en su sitio. La aplicación entonces empieza a decir «ya no hay ningún archivo
en …» sobre rutas que la persona tiene delante en su Explorador, y el mensaje parece culpa
suya. Preguntarlo aquí convierte media hora de desconcierto en una línea.

## Lo que deliberadamente NO se comprueba

**No se sondean GDAL, PDAL ni Office.** Esas sondas lanzan procesos hijos, y una sonda de
salud que un monitor consulta cada diez segundos no puede forkar `gdalinfo`. Lo que hay
instalado ya lo contesta la pantalla de compatibilidad, que es su sitio.

## Grados, y un solo caso de 503

Sin base no hay aplicación que servir: eso es 503. Todo lo demás **degrada con 200**, y no
por suavidad: un 503 cuando el Samba todavía no ha montado dejaría al guion de despliegue
esperando para siempre, convirtiendo un aviso en un despliegue bloqueado.

Y no sale ni una ruta, ni un nombre de máquina, ni una versión de nada: esto se responde sin
haber entrado.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.utils import timezone

#: Cuanto puede llevar el despachador sin dar senales antes de darlo por caido. El latido se
#: escribe cada 40 s, asi que dos minutos son tres latidos perdidos: suficiente para no
#: avisar por un pico de carga, y poco para enterarse antes que la persona que espera.
LATIDO_MAXIMO_S = 120

#: Como se llama el archivo que toca el despachador. Un archivo y no una fila **a proposito**:
#: el obrero es otro proceso, y esto tiene que poder contestarse sin una escritura en SQLite
#: cada cuarenta segundos compitiendo con el progreso de la conversion.
ARCHIVO_DE_LATIDO = ".despachador"


@dataclass
class Salud:
    """El parte, listo para volverse JSON."""

    base: dict = field(default_factory=dict)
    despachador: dict = field(default_factory=dict)
    origenes: dict = field(default_factory=dict)
    disco: dict = field(default_factory=dict)
    estaticos: dict = field(default_factory=dict)

    @property
    def sirve(self) -> bool:
        """`False` solo cuando no hay nada que servir."""
        return bool(self.base.get("ok"))

    @property
    def estado(self) -> str:
        if not self.sirve:
            return "caido"
        todo = (self.despachador, self.origenes, self.disco, self.estaticos)
        return "ok" if all(parte.get("ok") for parte in todo) else "degradado"

    def a_json(self) -> dict:
        return {
            # `estado` primero y con la cadena «ok» intacta: `run.ps1` y el guion de
            # despliegue esperan a verla, y hay una prueba que lo fija.
            "estado": self.estado,
            "modo": settings.MODO,
            "base": self.base,
            "despachador": self.despachador,
            "origenes": self.origenes,
            "disco": self.disco,
            "estaticos": self.estaticos,
        }


def revisar() -> Salud:
    """Mira las cinco cosas. No levanta nunca: un fallo aquí es un dato, no una excepción."""
    return Salud(
        base=_base(),
        despachador=_despachador(),
        origenes=_origenes(),
        disco=_disco(),
        estaticos=_estaticos(),
    )


def _base() -> dict:
    """Que el archivo se lea y que las migraciones esten puestas.

    Se cuenta la cola, que usa el indice `job_cola_idx`: una consulta indexada y ademas una
    cifra que interesa de verdad.
    """
    try:
        from apps.jobs.models import EJECUTANDO, ENCOLADO, ConversionJob

        encolados = ConversionJob.objects.filter(status=ENCOLADO).count()
        corriendo = ConversionJob.objects.filter(status=EJECUTANDO).count()
    except Exception as fallo:
        return {"ok": False, "motivo": type(fallo).__name__}
    return {"ok": True, "encolados": encolados, "ejecutando": corriendo}


def _despachador() -> dict:
    """¿Sigue vivo el obrero de conversiones?

    **Es la pregunta que va a hacer la gente** —«se quedó en encolado»— y la única que el
    proceso web no puede contestar de ninguna otra forma cuando el obrero es otro servicio.
    """
    if not getattr(settings, "CONVERSION_DISPATCHER_ENABLED", False):
        from . import modo

        # **Solo se echa de menos a un obrero donde tiene que haberlo.** En desarrollo y en
        # pruebas esta apagado a proposito -- se usa `procesar_trabajos --una-vez`, que es
        # determinista --, y decir «degradado» ahi seria ruido permanente.
        #
        # La senal no es `DEBUG`: Django lo fuerza a `False` durante las pruebas. Es que la
        # maquina sea un servidor, o sea que haya un nombre de verdad en `ALLOWED_HOSTS`.
        if not modo._es_compartida():
            return {"ok": True, "apagado": True}

        # Corre fuera: lo que hay es el latido.
        try:
            from apps.jobs import retencion

            latido = retencion.carpeta_de_trabajo() / ARCHIVO_DE_LATIDO
            if not latido.exists():
                return {"ok": False, "motivo": "sin-latido"}
            edad = timezone.now().timestamp() - latido.stat().st_mtime
        except OSError as fallo:
            return {"ok": False, "motivo": type(fallo).__name__}
        return {"ok": edad < LATIDO_MAXIMO_S, "ultimo_latido_s": int(edad)}

    # Corre aqui dentro: se pregunta al hilo.
    try:
        from apps.jobs import despachador

        return {"ok": despachador.vivo(), "dentro_del_web": True}
    except Exception as fallo:  # pragma: no cover
        return {"ok": False, "motivo": type(fallo).__name__}


def _origenes() -> dict:
    """Que las carpetas de las que se leen archivos sigan ahí."""
    from . import modo

    raices = modo.raices_permitidas()
    if not raices:
        return {"ok": True, "raices": 0, "legibles": 0}

    legibles = 0
    for raiz in raices:
        try:
            if raiz.is_dir():
                legibles += 1
        except OSError:  # pragma: no cover -- un montaje colgado
            continue
    return {"ok": legibles == len(raices), "raices": len(raices), "legibles": legibles}


def _disco() -> dict:
    """Un servidor sin disco no devuelve un error: deja de funcionar entero."""
    try:
        from apps.jobs import retencion

        carpeta = retencion.carpeta_de_trabajo()
        uso = shutil.disk_usage(carpeta)
    except OSError as fallo:
        return {"ok": False, "motivo": type(fallo).__name__}

    libre_gb = uso.free / 1_000_000_000
    return {"ok": libre_gb > 1.0, "libre_gb": round(libre_gb, 1)}


def _estaticos() -> dict:
    """Que el manifiesto esté, porque sin él **todas** las páginas dan 500.

    Es el fallo de `apps/core/test_arranque.py` convertido en algo que se pregunta en vez de
    descubrirse. Y no se comprueba en `dev`, donde el almacén no lleva manifiesto.
    """
    almacen = settings.STORAGES.get("staticfiles", {}).get("BACKEND", "")
    if "Manifest" not in almacen and "AlmacenDeEstaticos" not in almacen:
        return {"ok": True, "manifiesto": "no-aplica"}
    existe = (Path(settings.STATIC_ROOT) / "staticfiles.json").exists()
    return {"ok": existe, "manifiesto": existe}
