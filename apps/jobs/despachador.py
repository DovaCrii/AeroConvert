"""El despachador: un hilo que reclama trabajos y lanza el motor en un proceso hijo.

## Por que no hay Celery, ni django-q, ni un broker

**Un hilo que convierta** queda descartado porque GDAL sin memoria mata el proceso, y ese
proceso seria el servidor. Ademas un hilo de Python no se puede cancelar.

**`django-q2` o `huey`** exigen un segundo proceso que alguien tiene que arrancar, lo que
contradice «un `.ps1` levanta el servidor y abre el navegador». Y su valor -- varios
obreros, agenda, colas distribuidas -- es justo lo que este caso no necesita: una maquina,
un disco, un trabajo pesado a la vez.

**Hilo despachador + `subprocess`** es lo que queda, y basta: si el hijo muere, el padre lee
el codigo de salida; `terminate()` cancela de verdad; y no hay infraestructura que montar.

## Las cuatro guardas, y ninguna sobra

1. **`runserver` arranca dos procesos.** Sin la guarda de `RUN_MAIN`, dos despachadores
   compiten por el mismo trabajo y el archivo se escribe dos veces.
2. **Reclamar es un `UPDATE` atomico**, no leer-y-escribir. Correcto con dos despachadores,
   con dos obreros de gunicorn, y con alguien corriendo el comando a mano.
3. **Apagado en las pruebas.** `CONVERSION_DISPATCHER_ENABLED` es `False` por omision, y las
   pruebas usan `procesar_trabajos --una-vez`, que corre el mismo bucle de forma
   determinista. Una prueba que arranca un hilo es una prueba que falla los martes.
4. **Latido.** Un trabajo `ejecutando` cuyo obrero ya no existe se voltea a `error` con
   `interrumpido` en el barrido siguiente. Sin esto se queda ahi para siempre.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from .models import EJECUTANDO, ENCOLADO, ERROR, ConversionJob

registro = logging.getLogger(__name__)

#: Cada cuanto mira la cola.
INTERVALO_S = 2.0

#: Cuantos latidos perdidos hacen falta para dar por muerto a un obrero. Tres, y no uno,
#: porque un proceso ocupado escribiendo un tramo grande puede tardar en latir.
LATIDOS_PERDIDOS = 3

_hilo: threading.Thread | None = None
_parar = threading.Event()


def procesar_una_vez() -> int:
    """Un ciclo: recoge muertos y ejecuta el siguiente trabajo. Devuelve cuantos ejecuto.

    Es la funcion que usan las pruebas y el comando de gestion. El hilo no hace otra cosa
    que llamarla en bucle, asi que lo que se prueba es exactamente lo que corre.
    """
    recoger_muertos()

    simultaneos = getattr(settings, "TRABAJOS_SIMULTANEOS", 1)
    corriendo = ConversionJob.objects.filter(status=EJECUTANDO).count()
    if corriendo >= simultaneos:
        return 0

    siguiente = ConversionJob.objects.filter(status=ENCOLADO).order_by("queued_at").first()
    if siguiente is None:
        return 0

    from . import runner

    if not runner.reclamar(siguiente.pk):
        # Otro llego antes. No es un error: es el caso normal con dos despachadores.
        return 0

    siguiente.refresh_from_db()
    registro.info("Ejecutando %s", siguiente.pk)
    runner.ejecutar(siguiente)
    return 1


def recoger_muertos() -> int:
    """Voltea a `error` los trabajos cuyo obrero ya no esta.

    Un trabajo atascado en `ejecutando` sin nadie detras es la unica forma de fallo que no
    se reporta sola, asi que hay que ir a buscarla.
    """
    limite = timezone.now() - timedelta(seconds=INTERVALO_S * LATIDOS_PERDIDOS * 10)
    sospechosos = ConversionJob.objects.filter(status=EJECUTANDO, heartbeat_at__lt=limite)

    recogidos = 0
    for job in sospechosos:
        if job.worker_pid and _vive(job.worker_pid):
            continue
        job.status = ERROR
        job.reason_code = "interrumpido"
        job.reason_detail = (
            "El proceso que lo ejecutaba desaparecio. Suele ser que la maquina se apago o "
            "que el motor se quedo sin memoria."
        )
        job.finished_at = timezone.now()
        job.save(
            update_fields=["status", "reason_code", "reason_detail", "finished_at", "updated_at"]
        )
        job.registrar(job.reason_detail, nivel="error", reason_code="interrumpido")
        recogidos += 1
    return recogidos


def _vive(pid: int) -> bool:
    """Si ese proceso sigue existiendo.

    En Windows no hay senal 0, asi que se pregunta al sistema. Un `False` de mas voltearia
    un trabajo vivo a error, asi que ante la duda se devuelve `True`.
    """
    if os.name == "nt":
        try:
            import ctypes

            SYNCHRONIZE = 0x00100000
            manejador = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if manejador:
                ctypes.windll.kernel32.CloseHandle(manejador)
                return True
            return False
        except Exception:  # noqa: BLE001
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _bucle() -> None:
    while not _parar.is_set():
        try:
            # El hilo vive fuera del ciclo de peticion, asi que nadie cierra sus conexiones
            # por el. Sin esto, SQLite acaba con conexiones colgadas.
            close_old_connections()
            if procesar_una_vez() == 0:
                time.sleep(INTERVALO_S)
        except Exception:  # noqa: BLE001 - el hilo no se puede morir por un trabajo malo
            registro.exception("Fallo del despachador")
            time.sleep(INTERVALO_S)


def arrancar() -> bool:
    """Arranca el hilo si toca. Devuelve `True` si lo arranco."""
    global _hilo

    if not getattr(settings, "CONVERSION_DISPATCHER_ENABLED", False):
        return False

    # `runserver` con el recargador son DOS procesos: el vigilante y el que sirve. Solo el
    # segundo tiene RUN_MAIN. Sin esta guarda habria dos despachadores.
    if os.environ.get("RUN_MAIN") == "false":
        return False

    if _hilo is not None and _hilo.is_alive():
        return False

    _parar.clear()
    _hilo = threading.Thread(target=_bucle, name="aeroconvert-despachador", daemon=True)
    _hilo.start()
    registro.info("Despachador arrancado")
    return True


def detener(timeout: float = 5.0) -> None:
    _parar.set()
    if _hilo is not None:
        _hilo.join(timeout=timeout)
