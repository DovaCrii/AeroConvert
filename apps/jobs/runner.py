"""Ejecuta un trabajo: huella, inspeccion, conversion, verificacion.

## Las invariantes, y por que cada una

**El original no se toca.** Se abre en solo lectura y nunca se le escribe. Hay una prueba
que compara su `sha256` y su fecha antes y despues de **cada camino de fallo**, no solo del
feliz -- que es donde suelen aparecer los `unlink` de limpieza mal apuntados.

**Escritura atomica.** El motor escribe en `<destino>.parcial`, en el mismo directorio del
destino para que `os.replace()` sea un renombrado dentro del mismo volumen. Solo tras
verificar se renombra. Nunca queda un archivo a medias que parece valido, que es peor que
no tener nada: alguien lo abre, ve la mitad de la ortofoto y cree que la conversion se comio
la otra mitad.

**El codigo de salida no es la prueba de que funciono.** ODA devuelve 0 sin convertir nada;
GDAL devuelve 0 tras dejar un archivo vacio si el controlador fallo al cerrar. Lo que se
comprueba es que el archivo exista **y verifique**.

**El destino se reserva antes de empezar.** Si esta abierto en QGIS, `os.replace()` fallaria
al final, despues de horas. Tocarlo con creacion exclusiva al principio convierte eso en un
fallo inmediato con su motivo.

## El detector de atasco

El presupuesto total de tiempo tiene que ser generoso -- un ECW de 40 GB tarda horas
legitimamente -- y por eso solo sirve de respaldo. El detector util es otro: **si no llega
ni un tic de progreso ni un byte de stderr en `AEROCONVERT_SILENCIO_MAXIMO_S`, el trabajo
esta atascado**, dure lo que dure el presupuesto.
"""

from __future__ import annotations

import os
import queue
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from apps.engines import registry
from apps.engines.base import ParDeFormatos, PlanDeEjecucion, ruta_parcial
from apps.formats import deteccion

from . import motivos as motivos_mod
from .models import (
    CANCELADO,
    CONVERSION,
    EJECUTANDO,
    ENCOLADO,
    ERROR,
    HECHO,
    HUELLA,
    INSPECCION,
    VERIFICACION,
    VERIFICANDO,
    ConversionJob,
    JobEvent,
)

#: Cada cuanto se mira si pidieron cancelar y si el motor sigue vivo.
LATIDO_S = 2.0

#: Cuanto se espera a que el hijo muera por las buenas antes de matarlo.
GRACIA_AL_CANCELAR_S = 10.0

#: Reintentos del renombrado final. El antivirus abre el archivo recien escrito durante un
#: instante, y ese caso si es transitorio -- a diferencia de QGIS teniendolo abierto.
REINTENTOS_DE_RENOMBRADO = 3


class TrabajoFallido(Exception):
    def __init__(self, codigo: str, mensaje: str = "") -> None:
        super().__init__(mensaje or motivos_mod.mensaje(codigo))
        self.codigo = codigo
        self.mensaje = mensaje or motivos_mod.mensaje(codigo)


@dataclass
class Resultado:
    estado: str
    codigo_motivo: str = ""
    mensaje: str = ""


# --- Reclamo ---------------------------------------------------------------


def reclamar(job_id) -> bool:
    """Marca el trabajo como propio. Devuelve `False` si otro llego antes.

    Es un `UPDATE ... WHERE status = 'queued'` en una sola sentencia, no un leer-y-escribir.
    La diferencia importa con dos despachadores -- y `runserver` con el recargador son dos
    procesos, asi que el caso es el normal, no el raro.
    """
    ahora = timezone.now()
    reclamados = ConversionJob.objects.filter(pk=job_id, status=ENCOLADO).update(
        status=EJECUTANDO,
        started_at=ahora,
        heartbeat_at=ahora,
        worker_pid=os.getpid(),
        worker_host=socket.gethostname()[:80],
        attempt_count=F("attempt_count") + 1,
    )
    return reclamados == 1


# --- Ejecucion -------------------------------------------------------------


def ejecutar(job: ConversionJob) -> Resultado:
    """Corre el trabajo entero. No levanta: devuelve el resultado y lo deja escrito."""
    try:
        resultado = _ejecutar(job)
    except TrabajoFallido as fallo:
        # Cancelar no es fallar. Lo pidio una persona, y mezclarlo con los errores haria que
        # el historial no distinguiera «esto se rompio» de «cambie de idea» -- que es
        # justamente lo que hay que poder distinguir al revisar por que no hay entregable.
        estado = CANCELADO if fallo.codigo == "cancelado-por-el-usuario" else ERROR
        resultado = Resultado(estado, fallo.codigo, fallo.mensaje)
    except Exception as inesperado:  # noqa: BLE001 - un fallo no previsto tambien se registra
        resultado = Resultado(
            ERROR, "error-del-motor", f"{type(inesperado).__name__}: {inesperado}"
        )

    job.refresh_from_db()
    job.status = resultado.estado
    job.reason_code = resultado.codigo_motivo
    job.reason_detail = resultado.mensaje
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "reason_code", "reason_detail", "finished_at", "updated_at"])

    if resultado.estado == HECHO:
        nivel = JobEvent.INFO
    elif resultado.estado == CANCELADO:
        nivel = JobEvent.AVISO
    else:
        nivel = JobEvent.ERROR
    job.registrar(
        resultado.mensaje or "Terminado.",
        nivel=nivel,
        reason_code=resultado.codigo_motivo,
    )
    return resultado


def _ejecutar(job: ConversionJob) -> Resultado:
    origen = Path(job.source_path)
    if not origen.exists():
        raise TrabajoFallido("origen-no-legible", f"Ya no hay ningún archivo en {origen}.")

    huella_antes = origen.stat().st_mtime_ns

    # --- 1. Huella -------------------------------------------------------
    job.marcar_progreso(HUELLA, 0.0)
    job.source_sha256 = deteccion.huella(origen, progreso=lambda f: job.marcar_progreso(HUELLA, f))
    job.source_size_bytes = origen.stat().st_size
    job.save(update_fields=["source_sha256", "source_size_bytes", "updated_at"])

    # --- 2. Inspeccion ---------------------------------------------------
    job.marcar_progreso(INSPECCION, 0.0)
    try:
        inspeccion = deteccion.inspeccionar(origen)
    except deteccion.OrigenIlegible as fallo:
        raise TrabajoFallido(fallo.codigo, str(fallo)) from fallo

    job.source_format_code = inspeccion.codigo_formato
    job.source_format_confidence = inspeccion.confianza
    if inspeccion.crs.conocido:
        job.source_crs_authority = inspeccion.crs.autoridad
        job.source_crs_code = inspeccion.crs.codigo
        job.source_crs_origin = inspeccion.crs.origen
    job.save(
        update_fields=[
            "source_format_code",
            "source_format_confidence",
            "source_crs_authority",
            "source_crs_code",
            "source_crs_origin",
            "updated_at",
        ]
    )
    for aviso in inspeccion.avisos:
        job.registrar(aviso, nivel=JobEvent.AVISO, etapa=INSPECCION)

    _exigir_crs(job, inspeccion)
    _exigir_metros(job, inspeccion)

    # --- 3. Conversion ---------------------------------------------------
    par = ParDeFormatos(job.source_format_code, job.target_format_code)
    motor = registry.motor_para(par)
    if motor is None:
        celda = registry.celda(par)
        raise TrabajoFallido(celda.codigo_motivo or "sin-motor", celda.mensaje)

    disponible = motor.disponibilidad()
    job.engine_id = motor.id
    job.engine_version = disponible.version[:200]
    job.save(update_fields=["engine_id", "engine_version", "updated_at"])

    plan = motor.plan(job)
    destino = Path(plan.ruta_de_salida)
    parcial = ruta_parcial(destino)

    _reservar_destino(destino)
    _exigir_espacio(destino, job.source_size_bytes)

    job.marcar_progreso(CONVERSION, 0.0)
    _lanzar(job, plan, parcial)

    # --- 4. Verificacion --------------------------------------------------
    job.status = VERIFICANDO
    job.save(update_fields=["status", "updated_at"])
    job.marcar_progreso(VERIFICACION, 0.0)

    veredicto = motor.verificar(job, parcial)
    if not veredicto.correcta:
        _borrar(parcial)
        raise TrabajoFallido(veredicto.codigo_motivo or "salida-invalida", veredicto.motivo)

    _renombrar_con_acompanantes(job, parcial, destino)
    _limpiar_restos(parcial)

    from . import retencion

    job.output_path = str(destino)
    job.output_size_bytes = destino.stat().st_size
    job.verified_at = timezone.now()
    job.verification = veredicto.detalles
    job.expires_at = retencion.caducidad_para()
    job.save(
        update_fields=[
            "output_path",
            "output_size_bytes",
            "verified_at",
            "verification",
            "expires_at",
            "updated_at",
        ]
    )
    job.marcar_progreso(VERIFICACION, 1.0)

    # El original tiene que estar exactamente como estaba. No es una comprobacion de
    # cortesia: es la unica forma de detectar un motor que escribio donde no debia.
    if origen.stat().st_mtime_ns != huella_antes:
        job.registrar(
            "El archivo de origen cambio durante la conversión. Revisa el motor.",
            nivel=JobEvent.ERROR,
        )

    return Resultado(HECHO, "", "Convertido y verificado.")


def _exigir_crs(job: ConversionJob, inspeccion) -> None:
    """La regla heredada: si falta el CRS, se para y se pregunta. No se adivina.

    Con la distincion que la hace usable: **solo se detiene si hace falta de verdad** --
    cuando el trabajo reproyecta o cuando el destino exige el CRS incrustado. Convertir un
    raster sin georreferencia a otro sin georreferencia es legitimo, y negarlo convertiria
    la herramienta en un estorbo.
    """
    if inspeccion.crs.conocido:
        return

    from apps.formats import catalogo
    from apps.formats import crs as crs_mod

    # **Lo declarado a mano cuenta, y hay formatos donde es la única vía.**
    #
    # Una libreta de puntos no lleva sistema de referencia dentro **nunca**: es texto con
    # tres números por línea. Si lo único que vale fuera el CRS incrustado, esta rama
    # rechazaría todas las libretas del mundo y la mitad de la fase vectorial no existiría.
    #
    # Se acepta con dos condiciones, y las dos importan: que lo haya declarado una persona
    # -- `validar_declarado()` lo marca así y comprueba el código contra pyproj -- y que
    # quede escrito en la bitácora. Esa anotación es la traza del día en que alguien puso la
    # obra en otro país, y sin ella «lo declaró alguien» no se puede sostener.
    if job.source_crs_code and job.source_crs_origin == crs_mod.DECLARADO:
        job.registrar(
            f"El archivo no declara sistema de referencia. Se usa el declarado a mano: "
            f"{job.source_crs_authority or 'EPSG'}:{job.source_crs_code}.",
            nivel=JobEvent.AVISO,
            etapa=INSPECCION,
        )
        return

    reproyecta = bool(job.target_crs_code)

    destino = catalogo.FORMATOS.get(job.target_format_code)
    origen = catalogo.FORMATOS.get(job.source_format_code)
    lo_exige = bool(destino and destino.lleva_crs_incrustado and destino.familia == catalogo.RASTER)

    # **En nubes de puntos no hay excepción.** En ráster se admite convertir sin
    # georreferencia -- un TIFF suelto a un COG suelto es legítimo y negarlo convertiría la
    # herramienta en un estorbo. En nubes no: una nube sin CRS no se puede cruzar con nada,
    # y el dato se pierde para siempre si nadie lo apunta al entregarla. Es la regla escrita
    # en `AeroBim/docs/NUBES_DE_PUNTOS.md`.
    es_nube = bool(
        (destino and destino.familia == catalogo.NUBE)
        or (origen and origen.familia == catalogo.NUBE)
    )

    # **En una libreta de puntos tampoco hay excepción, y por un motivo distinto.**
    #
    # Un ráster sin georreferencia sigue siendo una imagen: tiene píxeles, se ve, y pasarla a
    # otro formato sin georreferencia no pierde nada. Una libreta de puntos **no es nada más
    # que coordenadas**. Sin sistema de referencia, esos tres números no dicen dónde está el
    # punto, y la salida es una capa que afirma estar en algún sitio sin estarlo. Además, a
    # KML no se podría ni llegar: exige EPSG:4326 y reproyectar necesita saber de dónde.
    es_libreta = bool(origen and origen.codigo == "puntos")

    if reproyecta or lo_exige or es_nube or es_libreta:
        if es_nube:
            detalle = (
                "Una nube sin sistema de referencia no se puede cruzar con nada, y el dato "
                "se pierde para siempre si nadie lo apunta al entregarla."
            )
        elif es_libreta:
            detalle = (
                "Una libreta de puntos no es más que coordenadas: sin declarar el EPSG, "
                "esos números no dicen dónde está nada. Míralo en el .prj del "
                "levantamiento o pregúntaselo a quien lo midió."
            )
        else:
            detalle = "Declara el EPSG: adivinarlo es peor que no tenerlo."
        raise TrabajoFallido(
            "crs-ausente",
            f"El archivo no declara sistema de referencia y esta conversión lo necesita. {detalle}",
        )

    job.registrar(
        "El archivo no declara sistema de referencia. Se convierte igual porque el destino "
        "tampoco lo exige, pero la salida tampoco lo tendra.",
        nivel=JobEvent.AVISO,
        etapa=INSPECCION,
    )


def _exigir_metros(job: ConversionJob, inspeccion) -> None:
    """Un destino que necesita metros no se llena de grados en silencio.

    Es el mismo fallo que el del KML, en la dirección contraria y con la misma cara de
    éxito. Un KMZ viene siempre en EPSG:4326; convertirlo a DXF sin reproyectar escribe
    coordenadas como `-69,046` y `-24,244`, así que el dibujo entero mide **dos milésimas
    de unidad**. Se comprobó: abre en Civil 3D, no se ve nada, y el recibo dice «hecho».

    Se para **antes** de convertir y no al verificar porque un DXF no guarda sistema de
    referencia: mirando la salida no hay forma de saber en qué unidades está. El dato solo
    existe aquí, en el origen.
    """
    from apps.formats import catalogo

    destino = catalogo.FORMATOS.get(job.target_format_code)
    if destino is None or not destino.exige_metros:
        return

    origen_crs = inspeccion.crs if inspeccion.crs.conocido else _crs_declarado_del_trabajo(job)
    if not origen_crs.es_geografico:
        return

    # El destino puede venir del trabajo o de la opción del motor. Se miran las dos porque
    # el formulario experto llega por `options` y la API por `target_crs_code`.
    if job.target_crs_code or (job.options or {}).get("crs_destino"):
        return

    formato = destino.nombre
    raise TrabajoFallido(
        "crs-en-grados",
        f"El origen está en {origen_crs}, que son grados, y un {formato} guarda números sin "
        "sistema de referencia: el dibujo saldría midiendo milésimas de unidad. Declara a "
        "qué sistema proyectado hay que llevarlo — para esta zona suele ser un UTM en metros.",
    )


def _crs_declarado_del_trabajo(job: ConversionJob):
    from apps.formats import crs as crs_mod

    if not job.source_crs_code:
        return crs_mod.SIN_CRS
    return crs_mod.Crs(
        autoridad=job.source_crs_authority or "EPSG",
        codigo=job.source_crs_code,
        origen=job.source_crs_origin or crs_mod.DECLARADO,
    )


def _reservar_destino(destino: Path) -> None:
    """Comprueba **antes de empezar** que se podra escribir ahi.

    Lo caro no es que falle: es que falle al final. Un destino abierto en QGIS hace fallar
    el renombrado tras horas de conversion.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    testigo = destino.with_name(destino.name + ".prueba")
    try:
        with open(testigo, "xb"):
            pass
    except FileExistsError:
        _borrar(testigo)
    except PermissionError as fallo:
        raise TrabajoFallido(
            "salida-bloqueada",
            f"No se puede escribir en {destino.parent}: sin permiso o carpeta bloqueada.",
        ) from fallo
    except OSError as fallo:
        raise TrabajoFallido(
            "salida-bloqueada", f"No se puede escribir en {destino.parent}: {fallo}"
        ) from fallo
    else:
        _borrar(testigo)

    if not destino.exists():
        return

    # **Abrir el archivo no sirve para saber si esta bloqueado.** En Windows, Python abre
    # con FILE_SHARE_READ|FILE_SHARE_WRITE, asi que `open(destino, "ab")` funciona aunque
    # QGIS lo tenga abierto -- y la comprobacion daba siempre verde mientras el fallo real
    # aparecia al final, en `os.replace()`, tras horas de conversion. Que es exactamente lo
    # que esta funcion existe para evitar.
    #
    # Lo que si lo detecta es intentar **la misma operacion** que se hara al final:
    # renombrar. Un archivo con un manejador abierto no se puede renombrar, asi que se
    # renombra y se deja como estaba. Cuesta dos llamadas al sistema.
    testigo = destino.with_name(destino.name + ".enuso")
    _borrar(testigo)
    try:
        os.replace(destino, testigo)
    except OSError as fallo:
        raise TrabajoFallido(
            "salida-bloqueada",
            f"{destino.name} esta abierto en otro programa. Cierralo y reintenta.",
        ) from fallo

    try:
        os.replace(testigo, destino)
    except OSError as fallo:  # pragma: no cover - solo si algo se lo lleva entremedias
        raise TrabajoFallido(
            "salida-bloqueada",
            f"No se pudo devolver {destino.name} a su sitio: {fallo}. Quedo como {testigo.name}.",
        ) from fallo


def _exigir_espacio(destino: Path, bytes_origen: int) -> None:
    """Que quepa la salida. Llenar el disco de la estacion de trabajo la tumba entera."""
    try:
        libre = shutil.disk_usage(destino.parent).free
    except OSError:
        return
    # Se pide el tamano del origen como estimacion. Es conservador para una conversion con
    # perdida y ajustado para una sin perdida, que es cuando de verdad importa.
    if libre < bytes_origen:
        raise TrabajoFallido(
            "sin-espacio",
            f"Quedan {libre / 1e9:.1f} GB libres y la salida puede necesitar "
            f"{bytes_origen / 1e9:.1f} GB.",
        )


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

    try:
        # El argv lo construye el motor a partir de rutas validadas y literales del codigo;
        # va como lista y con `shell=False`, asi que no hay interpretacion de
        # metacaracteres. La justificacion va aqui y no tras el `nosec` porque bandit lee
        # todo lo que sigue al `nosec` como identificadores de prueba.
        proceso = subprocess.Popen(  # nosec B603
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
        )
    except FileNotFoundError as fallo:
        raise TrabajoFallido(
            "motor-no-disponible", f"No se pudo ejecutar {plan.argv[0]}."
        ) from fallo
    except OSError as fallo:
        raise TrabajoFallido("error-del-motor", f"No se pudo lanzar el motor: {fallo}") from fallo

    job.worker_pid = proceso.pid
    job.save(update_fields=["worker_pid", "updated_at"])

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
                fraccion = plan.analizador_de_progreso(linea)
                if fraccion is not None:
                    job.marcar_progreso(CONVERSION, fraccion)

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

    codigo = proceso.wait()
    texto = "\n".join(cola_de_salida)

    if codigo != 0:
        _borrar(parcial)
        job.registrar(
            f"El motor terminó con código {codigo}.",
            nivel=JobEvent.ERROR,
            etapa=CONVERSION,
            stderr_cola=texto,
            codigo_de_salida=codigo,
        )
        raise TrabajoFallido("error-del-motor", _ultima_linea_util(texto) or f"Código {codigo}.")

    # Codigo 0 no basta. Es la regla numero uno del proyecto.
    #
    # Se comprueba aqui salvo que el plan diga que la salida la escribe un paso posterior:
    # hay conversiones que no las hace una sola herramienta, y en esas el principal deja un
    # intermedio y no el parcial. La comprobacion no se salta, se mueve abajo.
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
            resultado = subprocess.run(  # nosec B603
                list(comando),
                capture_output=True,
                text=True,
                cwd=str(plan.cwd) if plan.cwd else None,
                env=entorno,
                timeout=plan.timeout_s,
                check=False,
                shell=False,
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


def _matar(proceso) -> None:
    """Cancelacion cooperativa: primero por las buenas, luego por las malas."""
    proceso.terminate()
    try:
        proceso.wait(timeout=GRACIA_AL_CANCELAR_S)
    except subprocess.TimeoutExpired:
        proceso.kill()
        proceso.wait(timeout=5)


def _limpiar_restos(parcial: Path) -> None:
    """Borra los acompanantes que GDAL colgo del nombre del parcial.

    GDAL escribe un `.aux.xml` junto a lo que crea, y como lo crea con el nombre del
    parcial, ese acompanante se queda huerfano en cuanto el archivo se renombra: nadie lo
    reclama y nadie lo borra. Son unos pocos kilobytes cada uno, pero se acumulan uno por
    conversion y **contradicen lo que se promete** -- que el entregable es un solo archivo
    que se basta a si mismo.

    Se borra por prefijo. El destino nunca coincide: `entrega.jp2` no empieza por
    `entrega.jp2.parcial`.
    """
    try:
        for resto in parcial.parent.glob(parcial.name + ".*"):
            _borrar(resto)
    except OSError:
        pass


def _borrar(ruta: Path) -> None:
    try:
        ruta.unlink(missing_ok=True)
    except OSError:
        # Que no se pueda borrar el parcial es feo, no grave: el trabajo ya fallo y el
        # motivo real es el que se esta reportando.
        pass


def _renombrar_con_acompanantes(job: ConversionJob, parcial: Path, destino: Path) -> None:
    """Renombra la salida **y los archivos que la acompañan**.

    Un Shapefile no es un archivo: son cinco. `salida.shp` sin su `.shx` y su `.dbf` al lado
    **no abre en ninguna parte** -- `ogrinfo` responde «Unable to open salida.shx». Y no
    fallaba de forma visible: la verificacion corre sobre el parcial, cuando los hermanos
    todavia se llaman `salida.parcial.shx`, asi que pasaba; el renombrado movia solo el
    `.shp` y los dejaba huerfanos. El recibo decia «verificado» sobre un entregable
    inservible, que es el peor fallo que puede tener esto.

    Cuales acompañan lo dice el catalogo, no una lista escrita aqui: es el mismo dato que ya
    usa la ficha para avisar de que falta un `.prj`.
    """
    from apps.formats import catalogo

    _renombrar(parcial, destino)

    formato = catalogo.FORMATOS.get(job.target_format_code)
    if formato is None or not formato.acompanantes:
        return

    for extension in sorted(formato.acompanantes):
        hermano = parcial.with_suffix(extension)
        if not hermano.exists():
            continue
        try:
            _renombrar(hermano, destino.with_suffix(extension))
        except TrabajoFallido:
            # Un acompañante que no se puede mover deja el entregable incompleto, y eso hay
            # que decirlo: el archivo principal ya esta en su sitio y parece correcto.
            job.registrar(
                f"No se pudo colocar {destino.with_suffix(extension).name} junto a la "
                "salida. El archivo puede no abrir sin el.",
                nivel=JobEvent.ERROR,
            )


def _renombrar(parcial: Path, destino: Path) -> None:
    """`os.replace()` con reintentos, por el antivirus.

    Se reintenta tres veces con espera creciente. No es esconder un fallo: el caso del
    antivirus mirando el archivo recien escrito dura decimas de segundo, mientras que un
    destino abierto en QGIS falla las tres veces y acaba dando su motivo.
    """
    ultimo = None
    for intento in range(REINTENTOS_DE_RENOMBRADO):
        try:
            os.replace(parcial, destino)
            return
        except PermissionError as fallo:
            ultimo = fallo
            time.sleep(0.5 * (intento + 1))
        except OSError as fallo:
            ultimo = fallo
            break
    _borrar(parcial)
    raise TrabajoFallido(
        "salida-bloqueada",
        f"No se pudo escribir {destino.name}: {ultimo}. "
        "Suele ser que este abierto en otro programa.",
    )


def _ultima_linea_util(texto: str) -> str:
    """La ultima linea que parezca un error. GDAL las prefija con `ERROR`."""
    for linea in reversed(texto.splitlines()):
        limpia = linea.strip()
        if limpia and ("ERROR" in limpia.upper() or "FAIL" in limpia.upper()):
            return limpia[:500]
    ultimas = [x.strip() for x in texto.splitlines() if x.strip()]
    return ultimas[-1][:500] if ultimas else ""
