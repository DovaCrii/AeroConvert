"""El proceso hijo del motor: lanzarlo, seguir su avance, vigilar el plazo y matarlo con su árbol.

x Es la regla uno en la práctica: aquí se mira
el código de salida **y además** que exista el parcial; un `0` sin archivo es `sin-salida`.

El detector de atasco (`SILENCIO_MAXIMO_S`) es lo útil; el plazo del plan es solo el respaldo.
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from django.conf import settings

from apps.engines.base import PlanDeEjecucion

from .fallos import TrabajoFallido
from .models import CONVERSION, ConversionJob, JobEvent
from .salidas import _borrar

#: Cada cuanto se mira si pidieron cancelar y si el motor sigue vivo.
LATIDO_S = 2.0

#: Cuanto se espera a que el hijo muera por las buenas antes de matarlo.
GRACIA_AL_CANCELAR_S = 10.0


def _lanzar(job: ConversionJob, plan: PlanDeEjecucion, parcial: Path) -> None:
    """Corre el motor en un proceso hijo y sigue su progreso."""
    entorno = os.environ.copy()
    entorno.update(plan.env)

    job.registrar(
        "Lanzando el motor.",
        etapa=CONVERSION,
        # El argv completo queda en la bitacora. Es lo primero que se mira cuando la salida
        # no es la esperada, y lo que hace diagnosticable un argumento mal puesto.
        argv=list(plan.argv),
    )

    proceso = _abrir_proceso(plan, entorno)

    # **`worker_pid` se queda con el del obrero**, el de `reclamar()`. Aquí se pisaba con el del
    # motor, y en cuanto el motor terminaba y el obrero seguía con los pasos posteriores o la
    # verificación, `recoger_muertos` veía un PID muerto y un latido viejo y marcaba como
    # «interrumpido» un trabajo vivo (B-07 de la auditoría). Cancelar no lo necesita: es
    # cooperativo y se pide por la base.

    cola_de_salida = _vigilar_al_hijo(job, plan, proceso, parcial)

    codigo = proceso.wait()
    texto = "\n".join(cola_de_salida)

    _exigir_codigo_de_salida(job, parcial, codigo, texto)
    _exigir_la_salida_escrita(job, plan, parcial, entorno, texto)


def _abrir_proceso(plan: PlanDeEjecucion, entorno: dict) -> subprocess.Popen:
    """Arranca el hijo, cabeza de su propio grupo. Sin ejecutable: `motor-no-disponible`."""
    try:
        # El argv lo construye el motor a partir de rutas validadas y literales del codigo;
        # va como lista y con `shell=False`, asi que no hay interpretacion de
        # metacaracteres. La justificacion va aqui y no tras el `nosec` porque bandit lee
        # todo lo que sigue al `nosec` como identificadores de prueba.
        return subprocess.Popen(  # nosec B603
            list(plan.argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(plan.cwd) if plan.cwd else None,
            env=entorno,
            # **En binario y sin buffer, a proposito.** Ver `_leer_salida`: GDAL escribe el
            # avance en una sola linea que va creciendo, sin salto, y en modo texto no
            # llegaria nada hasta que la linea terminase.
            bufsize=0,
            shell=False,
            # Cabeza de su propio grupo, para poder matarlo **con sus descendientes**: ODA, Wine,
            # Office y `xvfb-run` lanzan nietos que sobrevivían a la cancelación y al plazo (B-08).
            **_opciones_de_grupo(),
        )
    except FileNotFoundError as fallo:
        raise TrabajoFallido(
            "motor-no-disponible", f"No se pudo ejecutar {plan.argv[0]}."
        ) from fallo
    except OSError as fallo:
        raise TrabajoFallido("error-del-motor", f"No se pudo lanzar el motor: {fallo}") from fallo


def _vigilar_al_hijo(
    job: ConversionJob, plan: PlanDeEjecucion, proceso: subprocess.Popen, parcial: Path
) -> list[str]:
    """Sigue al hijo hasta que acaba: progreso, cancelación, atasco y plazo.

    Devuelve el final de su salida (doscientas líneas como mucho). Si hay que cortarlo —lo
    pidió la persona, se atascó o pasó del plazo— lo mata con su árbol, borra el parcial y
    levanta el motivo.
    """
    lineas: queue.Queue[str | None] = queue.Queue()
    lector = threading.Thread(target=_leer_salida, args=(proceso, lineas), daemon=True)
    lector.start()

    cola_de_salida: list[str] = []
    empezo = time.monotonic()
    ultimo_signo = empezo
    silencio_maximo = getattr(settings, "SILENCIO_MAXIMO_S", 600)

    while True:
        try:
            linea = lineas.get(timeout=LATIDO_S)
        except queue.Empty:
            linea = ""
        else:
            if linea is None:
                break
            ultimo_signo = time.monotonic()
            cola_de_salida.append(linea)
            # Solo se guarda el final: el principio de la salida de GDAL no dice nada que
            # el argv no diga ya.
            if len(cola_de_salida) > 200:
                del cola_de_salida[:-200]
            if plan.analizador_de_progreso:
                avance = plan.analizador_de_progreso(linea)
                if avance is not None:
                    # Un número, como siempre; o `(fracción, etiqueta)` si la herramienta dice
                    # qué está haciendo.
                    fraccion, etiqueta = avance if isinstance(avance, tuple) else (avance, None)
                    job.marcar_progreso(CONVERSION, fraccion, etiqueta)

        ahora = time.monotonic()

        job.refresh_from_db(fields=["cancel_requested_at"])
        if job.cancelacion_pedida:
            _matar(proceso)
            _borrar(parcial)
            raise TrabajoFallido("cancelado-por-el-usuario", "Cancelado.")

        if proceso.poll() is not None and lineas.empty():
            break

        # El detector de atasco solo vale para motores que hablan. Con una herramienta muda
        # -- PDAL lo es -- el silencio es su estado normal, y matar por silencio mataria
        # trabajos sanos. Para esos queda el presupuesto total, que es peor detector pero es
        # el unico honesto.
        if plan.emite_progreso and ahora - ultimo_signo > silencio_maximo:
            _matar(proceso)
            _borrar(parcial)
            raise TrabajoFallido(
                "sin-avance",
                f"El motor lleva {silencio_maximo // 60} minutos sin dar senales de vida.",
            )

        if ahora - empezo > plan.timeout_s:
            _matar(proceso)
            _borrar(parcial)
            raise TrabajoFallido(
                "tardo-demasiado",
                f"La conversión paso de {plan.timeout_s // 60} minutos y se corto.",
            )

    return cola_de_salida


def _exigir_codigo_de_salida(job: ConversionJob, parcial: Path, codigo: int, texto: str) -> None:
    """Un código distinto de cero es `error-del-motor`, con la última línea útil de su salida."""
    if codigo == 0:
        return
    _borrar(parcial)
    job.registrar(
        f"El motor terminó con código {codigo}.",
        nivel=JobEvent.ERROR,
        etapa=CONVERSION,
        stderr_cola=texto,
        codigo_de_salida=codigo,
    )
    raise TrabajoFallido("error-del-motor", _ultima_linea_util(texto) or f"Código {codigo}.")


def _exigir_la_salida_escrita(
    job: ConversionJob, plan: PlanDeEjecucion, parcial: Path, entorno: dict, texto: str
) -> None:
    """Código 0 no basta: tiene que existir el parcial. Y corre los pasos posteriores."""
    # Codigo 0 no basta. Es la regla numero uno del proyecto.
    #
    # Se comprueba aqui salvo que el plan diga que la salida la escribe un paso posterior:
    # hay conversiones que no las hace una sola herramienta, y en esas el principal deja un
    # intermedio y no el parcial. La comprobacion no se salta, se mueve abajo.
    # `salida_opcional` no la salta: la aplaza. Quien la declara —solo los documentos— exige
    # después que el hijo haya dicho por qué no hay archivo. Ver `_ejecutar_documento`.
    if plan.salida_opcional:
        job.marcar_progreso(CONVERSION, 1.0)
        return

    if not plan.salida_en_posteriores and not parcial.exists():
        job.registrar(
            "El motor termino con código 0 pero no escribio ningún archivo.",
            nivel=JobEvent.ERROR,
            etapa=CONVERSION,
            stderr_cola=texto,
        )
        raise TrabajoFallido("sin-salida", "El motor termino sin escribir ningún archivo.")

    _pasos_posteriores(job, plan, parcial, entorno)

    if plan.salida_en_posteriores and not parcial.exists():
        job.registrar(
            "Los pasos posteriores terminaron sin escribir ningún archivo.",
            nivel=JobEvent.ERROR,
            etapa=CONVERSION,
            stderr_cola=texto,
        )
        raise TrabajoFallido("sin-salida", "El motor termino sin escribir ningún archivo.")

    job.marcar_progreso(CONVERSION, 1.0)


def _pasos_posteriores(job, plan: PlanDeEjecucion, parcial: Path, entorno: dict) -> None:
    """Los comandos que van despues del principal, como `gdaladdo` para las piramides.

    Un fallo aqui **detiene el trabajo y borra el parcial**. Entregar la salida sin sus
    piramides seria entregar algo distinto de lo que se pidio, y en silencio: el archivo
    abriria, solo que cada zoom leeria la imagen entera.
    """
    for indice, comando in enumerate(plan.posteriores, start=1):
        job.registrar(
            f"Paso posterior {indice} de {len(plan.posteriores)}.",
            etapa=CONVERSION,
            argv=list(comando),
        )
        try:
            resultado = _correr_en_grupo(
                list(comando),
                cwd=str(plan.cwd) if plan.cwd else None,
                entorno=entorno,
                timeout_s=plan.timeout_s,
            )
        except subprocess.TimeoutExpired as agotado:
            _borrar(parcial)
            raise TrabajoFallido("tardo-demasiado", f"El paso {indice} se corto.") from agotado
        except OSError as fallo:
            _borrar(parcial)
            raise TrabajoFallido(
                "error-del-motor", f"No se pudo lanzar el paso {indice}."
            ) from fallo

        if resultado.returncode != 0:
            salida = (resultado.stdout or "") + (resultado.stderr or "")
            _borrar(parcial)
            job.registrar(
                f"El paso posterior {indice} termino con código {resultado.returncode}.",
                nivel=JobEvent.ERROR,
                etapa=CONVERSION,
                stderr_cola=salida,
            )
            raise TrabajoFallido("error-del-motor", _ultima_linea_util(salida) or "Paso fallido.")


def _leer_salida(proceso, lineas: queue.Queue) -> None:
    """Lee la salida del hijo, en su propio hilo.

    ## Por que no se lee por lineas

    Porque **GDAL no escribe lineas mientras convierte**. Escribe
    `0...10...20...30...` en una sola linea que va creciendo, y el salto solo llega al
    final. Leyendo con `for linea in stdout` no aparece nada hasta que la conversion
    termina, y entonces:

    - la barra se queda quieta toda la conversion, y
    - **el detector de atasco deja de recibir senales**, asi que un raster que tarde mas
      que el umbral de silencio se mata solo.

    Asi que se lee por trozos con `os.read`, que devuelve en cuanto hay algo, y se corta
    tanto por salto de linea como por retorno de carro -- y ademas se emite lo que haya
    acumulado en cuanto termina en punto, que es como GDAL marca cada avance.

    Va en un hilo aparte porque leer una tuberia bloquea, y el bucle principal tiene que
    poder mirar la cancelacion y el reloj cada dos segundos.
    """
    try:
        if proceso.stdout is None:
            return
        descriptor = proceso.stdout.fileno()
        acumulado = b""
        while True:
            trozo = os.read(descriptor, 4096)
            if not trozo:
                break
            acumulado += trozo
            while True:
                corte = max(acumulado.rfind(b"\n"), acumulado.rfind(b"\r"))
                if corte == -1:
                    break
                for cruda in acumulado[:corte].replace(b"\r", b"\n").split(b"\n"):
                    if cruda.strip():
                        lineas.put(cruda.decode("utf-8", "replace"))
                acumulado = acumulado[corte + 1 :]
                break
            # Lo que queda sin cerrar tambien vale si ya trae un avance: es el caso normal
            # mientras GDAL trabaja.
            if acumulado.endswith(b".") and acumulado.strip():
                lineas.put(acumulado.decode("utf-8", "replace"))
        if acumulado.strip():
            lineas.put(acumulado.decode("utf-8", "replace"))
    except (OSError, ValueError):
        pass
    finally:
        lineas.put(None)


def _opciones_de_grupo() -> dict:
    """Para que el hijo sea cabeza de su propio grupo de procesos y se pueda matar entero."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _senalar_arbol(proceso, *, a_la_fuerza: bool) -> None:
    """Termina al proceso **y a todo lo que lanzó**.

    Matar solo al hijo directo dejaba huérfanos a los nietos: ODA File Converter, `wine`,
    `Xvfb`, Word, Excel y PowerPoint (servidores COM fuera de proceso) seguían vivos, con el
    archivo bloqueado y la memoria ocupada, mientras el despachador arrancaba el siguiente
    trabajo (B-08 de la auditoría). En POSIX se señala el grupo; en Windows, `taskkill /T`.
    Si por lo que sea no se puede, se cae a lo de antes: al menos el hijo.
    """
    try:
        if os.name == "nt":
            comando = ["taskkill", "/PID", str(proceso.pid), "/T"]
            if a_la_fuerza:
                comando.append("/F")
            subprocess.run(comando, capture_output=True, check=False, timeout=15)  # nosec B603 B607
        else:
            import signal

            os.killpg(proceso.pid, signal.SIGKILL if a_la_fuerza else signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        (proceso.kill if a_la_fuerza else proceso.terminate)()


def _matar(proceso) -> None:
    """Cancelacion cooperativa: primero por las buenas, luego por las malas, y con el árbol."""
    _senalar_arbol(proceso, a_la_fuerza=False)
    try:
        proceso.wait(timeout=GRACIA_AL_CANCELAR_S)
    except subprocess.TimeoutExpired:
        _senalar_arbol(proceso, a_la_fuerza=True)
        proceso.wait(timeout=5)


def _correr_en_grupo(comando: list[str], *, cwd, entorno: dict, timeout_s: int):
    """`subprocess.run` que, al agotarse el plazo, mata al grupo entero y no solo al hijo.

    `run(timeout=...)` mata únicamente al proceso directo y deja a sus descendientes: es el
    mismo agujero de `_matar`, en los pasos posteriores.
    """
    proceso = subprocess.Popen(  # nosec B603
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        # Sin esto, en Windows se decodifica con la página de códigos local y «pirámides» sale
        # «pirÃ¡mides». Los hijos escriben UTF-8; un byte inválido no tumba el paso.
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=entorno,
        shell=False,
        **_opciones_de_grupo(),
    )
    try:
        salida, errores = proceso.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _senalar_arbol(proceso, a_la_fuerza=True)
        proceso.communicate()
        raise
    return subprocess.CompletedProcess(comando, proceso.returncode, salida, errores)


def _ultima_linea_util(texto: str) -> str:
    """La ultima linea que parezca un error. GDAL las prefija con `ERROR`."""
    for linea in reversed(texto.splitlines()):
        limpia = linea.strip()
        if limpia and ("ERROR" in limpia.upper() or "FAIL" in limpia.upper()):
            return limpia[:500]
    ultimas = [x.strip() for x in texto.splitlines() if x.strip()]
    return ultimas[-1][:500] if ultimas else ""
