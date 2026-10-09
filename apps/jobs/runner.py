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

## Dónde vive cada pieza (F11.8)

- `fallos.py`: `TrabajoFallido`.
- `exigencias.py`: lo que se exige antes de convertir (memoria, crudo entero, CRS, metros).
- `salidas.py`: destino libre, reserva, espacio, borrado y renombrado atómico.
- `procesos.py`: el proceso hijo, su avance, el plazo, el atasco y matar el árbol.
- Este módulo: `reclamar`, `ejecutar` y las dos ramas (geoespacial y documentos). Re-exporta lo
  demás, de modo que `from apps.jobs import runner; runner._borrar(...)` sigue valiendo.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path

from django.db.models import F
from django.utils import timezone

from apps.engines import registry
from apps.engines.base import ParDeFormatos, ruta_parcial
from apps.formats import deteccion

from . import motivos as motivos_mod
from .exigencias import (  # noqa: F401 - re-exportadas: las importan pruebas y otros paquetes
    _crs_declarado_del_trabajo,
    _exigir_crs,
    _exigir_crudo_entero,
    _exigir_memoria,
    _exigir_metros,
)
from .fallos import TrabajoFallido
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
from .procesos import (  # noqa: F401 - re-exportadas: las importan pruebas y otros paquetes
    GRACIA_AL_CANCELAR_S,
    LATIDO_S,
    _correr_en_grupo,
    _lanzar,
    _leer_salida,
    _matar,
    _opciones_de_grupo,
    _pasos_posteriores,
    _senalar_arbol,
    _ultima_linea_util,
)
from .salidas import (  # noqa: F401 - re-exportadas: las importan pruebas y otros paquetes
    MAXIMO_VERSIONES,
    REINTENTOS_DE_RENOMBRADO,
    _borrar,
    _clave_de_ruta,
    _con_version,
    _destino_libre,
    _exigir_espacio,
    _exigir_espacio_de_la_salida,
    _limpiar_restos,
    _renombrar,
    _renombrar_con_acompanantes,
    _reservar_destino,
)

#: Lo que sigue **no se movió de sitio** para quien importa `apps.jobs.runner` (F11.8): el corredor
#: se partió en `fallos`, `exigencias`, `salidas` y `procesos`, y este módulo conserva la
#: orquestación (`reclamar`, `ejecutar`) más las dos ramas (`_ejecutar`, `_ejecutar_documento`).


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
    if job.herramienta:
        _soltar_subidas(job)
        # En cualquier final, también si falló antes de llegar a tomarla.
        from apps.documents import secretos

        secretos.olvidar(job)
    return resultado


def _soltar_subidas(job: ConversionJob) -> None:
    """Devuelve las subidas al barrido, **con margen para reintentar**.

    `cola.encolar` las reclamó (sin caducidad) para que no se las llevara el barrido mientras
    el trabajo esperaba. Al terminar, bien o mal, vuelven a caducar a las horas de siempre
    contadas desde ahora: si falló por algo transitorio, reintentar sigue encontrando el
    archivo sin volver a subirlo.
    """
    from datetime import timedelta

    from apps.core.subidas import HORAS_DE_VIDA

    caduca = timezone.now() + timedelta(hours=HORAS_DE_VIDA)
    for entrada in job.entradas.select_related("subida").exclude(subida=None):
        entrada.subida.expires_at = caduca
        entrada.subida.save(update_fields=["expires_at", "updated_at"])


def _ejecutar(job: ConversionJob) -> Resultado:
    # **Los documentos van por su propia rama**, y tienen que ir: la de abajo re-detecta el
    # formato, exige sistema de referencia y pregunta a la matriz. Con un documento, un `.csv`
    # acababa leído como libreta de puntos y rechazado por `crs-ausente`.
    if job.herramienta:
        return _ejecutar_documento(job)

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
    _exigir_memoria(job, inspeccion)
    _exigir_crudo_entero(job, inspeccion)

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

    # **Antes de pedir el plan**, porque el motor lee `job.output_path` para construir su
    # argv: si el nombre se decidiera despues, el motor escribiria en el viejo.
    job.output_path = str(_destino_libre(job, Path(job.output_path)))
    job.save(update_fields=["output_path", "updated_at"])

    plan = motor.plan(job)
    destino = Path(plan.ruta_de_salida)
    # Y el parcial sale del destino, asi que un destino unico da un parcial unico sin tocar
    # `ruta_parcial()`, que se llama desde catorce sitios y cuyo propio docstring avisa de
    # lo que pasa cuando el runner y los motores se desincronizan.
    parcial = ruta_parcial(destino)

    _reservar_destino(destino)
    _exigir_espacio(destino, job.source_size_bytes)
    _exigir_espacio_de_la_salida(job, inspeccion, destino)

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

    # **El original se comprueba antes de entregar nada**, no después: si el motor (o quien
    # fuera) lo tocó, la salida no se renombra. Es la regla cinco: lo que cambió el original no
    # se entrega como si fuera una conversión de él.
    cambio = _cambio_del_original(
        origen, origen.name, huella_antes, job.source_size_bytes, job.source_sha256
    )
    if cambio:
        _borrar(parcial)
        _limpiar_restos(parcial)
        raise TrabajoFallido("original-modificado", cambio)

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
    # Lo que el motor vio y no era motivo para fallar, pero conviene leer: queda en la
    # bitácora además de en el recibo, porque el recibo se borra con la salida y la bitácora no.
    for aviso in veredicto.detalles.get("avisos") or ():
        job.registrar(str(aviso), nivel=JobEvent.AVISO, etapa=VERIFICACION)
    job.marcar_progreso(VERIFICACION, 1.0)

    return Resultado(HECHO, "", "Convertido y verificado.")


def _ejecutar_documento(job: ConversionJob) -> Resultado:
    """Una herramienta de documentos: las mismas invariantes, sin lo geoespacial.

    Lo que **se conserva** de la rama de arriba, y es lo que importa: el destino se reserva
    antes de empezar, la salida se escribe en un parcial, el código de salida no basta, la
    verificación la hace un lector distinto del que escribió, y el original no se toca —
    comprobado **en cada entrada**, no solo en la primera.

    Lo que **no** se hace: re-detectar el formato, exigir sistema de referencia, preguntar a
    la matriz. Nada de eso significa algo para «numerar las páginas de un PDF».
    """
    from apps.documents import motor as documentos

    entradas = _entradas_del_documento(job)

    # --- 1. Huella de cada entrada ------------------------------------------
    _huellar_entradas(job, entradas)

    # --- 2. Que esta máquina pueda --------------------------------------------
    plan, destino, parcial = _preparar_documento(job, documentos)

    # --- 3. Ejecutar ------------------------------------------------------------
    job.marcar_progreso(CONVERSION, 0.0)
    try:
        informe = _correr_el_hijo_del_documento(job, documentos, plan, parcial)

        # **Sin archivo solo vale si el hijo lo ha declarado.** La ausencia sola es
        # `sin-salida`, como siempre: la excepción a la regla número uno exige un motivo.
        if not parcial.exists():
            return _cerrar_sin_archivo(job, plan, informe, entradas)

        # --- 4. Verificar ---------------------------------------------------------
        veredicto = _verificar_y_colocar_el_documento(
            job, documentos, plan, informe, parcial, destino, entradas
        )
    finally:
        documentos.borrar_auxiliares(job)
        _limpiar_restos(parcial)

    return _cerrar_documento(job, destino, informe, veredicto, entradas)


def _entradas_del_documento(job: ConversionJob) -> list:
    """Las entradas del trabajo, comprobando que **todas** siguen donde estaban."""
    entradas = list(job.entradas.all())
    if not entradas:
        # Un trabajo encolado por la API o por una prueba puede no traerlas: la única entrada
        # es entonces `source_path`, sin fila que guardar.
        from .models import EntradaDeTrabajo

        entradas = [EntradaDeTrabajo(orden=0, ruta=job.source_path, nombre=job.source_name)]

    for entrada in entradas:
        if not Path(entrada.ruta).exists():
            raise TrabajoFallido(
                "origen-no-legible", f"Ya no hay ningún archivo en {entrada.ruta}."
            )
    return entradas


def _huellar_entradas(job: ConversionJob, entradas: list) -> None:
    """`sha256`, tamaño y `mtime` de cada entrada: contra esto se comprueba que no se tocaron."""
    job.marcar_progreso(HUELLA, 0.0)
    total = len(entradas)
    for indice, entrada in enumerate(entradas):
        ruta = Path(entrada.ruta)
        estado = ruta.stat()
        entrada.mtime_ns = estado.st_mtime_ns
        entrada.bytes = estado.st_size
        entrada.sha256 = deteccion.huella(
            ruta,
            progreso=lambda f, i=indice: job.marcar_progreso(HUELLA, (i + f) / total),
        )
        if not entrada._state.adding:
            entrada.save(update_fields=["mtime_ns", "bytes", "sha256", "updated_at"])

    job.source_sha256 = entradas[0].sha256
    job.source_size_bytes = sum(e.bytes for e in entradas)
    job.save(update_fields=["source_sha256", "source_size_bytes", "updated_at"])


def _preparar_documento(job: ConversionJob, documentos) -> tuple:
    """Disponibilidad, destino libre, plan, reserva y espacio: `(plan, destino, parcial)`."""
    job.marcar_progreso(INSPECCION, 0.0)
    disponible = documentos.disponibilidad(job.herramienta, job.options)
    if not disponible.disponible:
        raise TrabajoFallido(disponible.codigo_motivo or "sin-motor", disponible.mensaje)

    job.engine_id = "documentos"
    job.engine_version = disponible.version[:200]
    job.output_path = str(_destino_libre(job, Path(job.output_path)))
    job.save(update_fields=["engine_id", "engine_version", "output_path", "updated_at"])

    from apps.documents import secretos

    try:
        plan = documentos.plan(job)
    except secretos.SinSecreto as falta:
        raise TrabajoFallido("falta-la-contrasena", str(falta)) from falta
    destino = Path(plan.ruta_de_salida)
    parcial = ruta_parcial(destino)

    _reservar_destino(destino)
    estimados = int((job.options or {}).get("bytes_estimados") or 0)
    _exigir_espacio(destino, max(job.source_size_bytes, estimados))
    return plan, destino, parcial


def _correr_el_hijo_del_documento(job: ConversionJob, documentos, plan, parcial: Path) -> dict:
    """Lanza el hijo y devuelve su informe. Si el informe trae un motivo, el trabajo falla."""
    try:
        _lanzar(job, plan, parcial)
    except TrabajoFallido as fallo:
        # **El hijo sabe mejor que nadie por qué falló.** `_lanzar` solo ve un código de
        # salida distinto de cero y lo llama `error-del-motor`; el informe trae el motivo
        # de verdad —`contrasena-incorrecta`, `documento-invalido`— con su mensaje.
        informe = documentos.leer_informe(job)
        if fallo.codigo == "error-del-motor" and informe.get("codigo"):
            raise TrabajoFallido(
                informe["codigo"], informe.get("mensaje") or fallo.mensaje
            ) from fallo
        raise

    informe = documentos.leer_informe(job)
    if informe.get("codigo"):
        _borrar(parcial)
        raise TrabajoFallido(informe["codigo"], informe.get("mensaje", ""))
    return informe


def _cerrar_sin_archivo(job: ConversionJob, plan, informe: dict, entradas: list) -> Resultado:
    """El hijo no escribió nada: solo es un éxito si lo **declaró** con un desenlace conocido."""
    desenlace = informe.get("desenlace", "")
    if not (plan.salida_opcional and desenlace in motivos_mod.DESENLACES):
        job.registrar(
            "La herramienta terminó sin escribir ningún archivo y sin decir por qué.",
            nivel=JobEvent.ERROR,
            etapa=CONVERSION,
        )
        raise TrabajoFallido("sin-salida", "La herramienta terminó sin escribir nada.")

    # También un «hecho» sin archivo es una afirmación sobre el original: si cambió, no vale.
    _comprobar_originales(job, entradas)

    job.desenlace = desenlace
    job.verification = informe.get("detalles") or {}
    job.output_path = ""
    job.verified_at = timezone.now()
    job.save(
        update_fields=[
            "desenlace",
            "verification",
            "output_path",
            "verified_at",
            "updated_at",
        ]
    )
    job.marcar_progreso(VERIFICACION, 1.0)
    return Resultado(HECHO, "", motivos_mod.DESENLACES[desenlace].mensaje)


def _verificar_y_colocar_el_documento(
    job: ConversionJob,
    documentos,
    plan,
    informe: dict,
    parcial: Path,
    destino: Path,
    entradas: list,
):
    """Verifica el parcial con un lector distinto del que escribió y lo renombra.

    Antes de renombrar se comprueba que **ningún original cambió**: si cambió, el parcial se borra
    y el trabajo termina en `original-modificado`; nada se entrega.
    """
    job.status = VERIFICANDO
    job.save(update_fields=["status", "updated_at"])
    job.marcar_progreso(VERIFICACION, 0.0)

    veredicto = documentos.verificar(parcial, informe, plan)
    if not veredicto.correcta:
        _borrar(parcial)
        raise TrabajoFallido(veredicto.codigo_motivo or "salida-invalida", veredicto.motivo)

    try:
        _comprobar_originales(job, entradas)
    except TrabajoFallido:
        _borrar(parcial)
        raise

    _renombrar(parcial, destino)
    return veredicto


def _cerrar_documento(
    job: ConversionJob, destino: Path, informe: dict, veredicto, entradas: list
) -> Resultado:
    """Lo que queda escrito en el trabajo tras una salida verificada, y el chequeo de originales."""
    avisos = [str(a) for a in informe.get("avisos") or []]
    for aviso in avisos:
        job.registrar(aviso, nivel=JobEvent.AVISO, etapa=VERIFICACION)

    from . import retencion

    job.output_path = str(destino)
    job.output_size_bytes = destino.stat().st_size
    job.verified_at = timezone.now()
    job.verification = veredicto.detalles
    job.desenlace = "con-avisos" if avisos else ""
    job.expires_at = retencion.caducidad_para()
    job.save(
        update_fields=[
            "output_path",
            "output_size_bytes",
            "verified_at",
            "verification",
            "desenlace",
            "expires_at",
            "updated_at",
        ]
    )
    job.marcar_progreso(VERIFICACION, 1.0)
    return Resultado(HECHO, "", "Hecho y verificado.")


def _cambio_del_original(
    ruta: Path, nombre: str, mtime_ns: int | None, bytes_antes: int, sha256_antes: str
) -> str:
    """Si el original ya no es el que se huelló, el mensaje que lo cuenta; si no, `""`.

    Se compara la fecha de modificación y, si se conocía, el tamaño: es barato incluso con
    40 GB. **Solo cuando algo cambió** se vuelve a calcular el `sha256`, para dejar en la
    bitácora el de antes y el de después. Un original que desapareció no se denuncia aquí: de
    eso se ocupan las comprobaciones de «origen legible».
    """
    if mtime_ns is None:
        return ""
    try:
        estado = ruta.stat()
    except OSError:
        return ""
    cambio_el_tamano = bool(bytes_antes) and estado.st_size != bytes_antes
    if estado.st_mtime_ns == mtime_ns and not cambio_el_tamano:
        return ""
    try:
        sha256_despues = deteccion.huella(ruta)
    except OSError:
        sha256_despues = "ilegible"
    return (
        f"El archivo de origen {nombre} cambió durante el trabajo: fecha de modificación "
        f"{mtime_ns} -> {estado.st_mtime_ns} ns, tamaño {bytes_antes or '?'} -> "
        f"{estado.st_size} bytes, sha256 {sha256_antes or '?'} -> {sha256_despues}. "
        "La salida no se entrega."
    )


def _comprobar_originales(job: ConversionJob, entradas) -> None:
    """El original no se toca, **y se mira en cada entrada**.

    Con un solo `source_path` solo se podía comprobar la primera, y en un «Unir» de veinte
    archivos las diecinueve restantes quedaban sin vigilar. Si alguna cambió, el trabajo
    **falla** con `original-modificado` (el mensaje lleva el antes y el después de cada una y
    queda en la bitácora): antes solo se denunciaba y el trabajo seguía en «hecho».
    """
    cambios = [
        mensaje
        for entrada in entradas
        if (
            mensaje := _cambio_del_original(
                Path(entrada.ruta),
                entrada.nombre,
                entrada.mtime_ns,
                entrada.bytes,
                entrada.sha256,
            )
        )
    ]
    if cambios:
        raise TrabajoFallido("original-modificado", " ".join(cambios))
