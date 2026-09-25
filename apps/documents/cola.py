"""Cómo una pantalla de documentos manda su trabajo a la cola.

**Una sola puerta para las veinte**, y es a propósito: la regla de dónde va la salida, qué
subidas quedan reclamadas y qué se apunta en la bitácora tiene que ser la misma para todas.
La última vez que cada pantalla decidió eso por su cuenta, cinco escribían el resultado de un
archivo subido dentro de `MEDIA_ROOT/subidas/<id>/` —donde nadie podía descargarlo— y trece
no daban forma ninguna de bajárselo.

## Lo que hace cada pantalla antes de llegar aquí

Su formulario y su «mirar antes»: leer la cabecera, avisar de que es un escaneo, dejar que
Unir ordene las páginas. Eso sigue siendo síncrono y barato. Lo que llega aquí es **solo la
acción final**, que es la que puede tardar.
"""

from __future__ import annotations

from pathlib import Path

from django.shortcuts import redirect

from . import motor as motor_documentos
from .herramientas import nombre_de


def ruta_de_salida(primero, sufijo: str) -> Path:
    """Dónde se escribe el resultado. **La salida va donde estaba la entrada.**

    Si el primer archivo venía de una carpeta —la compartida o el disco de uno—, el resultado
    va **al lado**: quien compone una entrega la quiere junto a sus archivos, y en la unidad
    de red ya la tiene montada.

    Si venía de una subida, no hay «al lado» que valga: va a la carpeta de trabajo y se
    entrega por la descarga del trabajo, que comprueba el dueño.
    """
    nombre = f"{Path(primero.nombre).stem}{sufijo}"
    if primero.es_subida:
        from apps.jobs import retencion

        return retencion.carpeta_de_trabajo() / nombre
    return primero.ruta.with_name(nombre)


def encolar(
    request,
    herramienta: str,
    origenes: list,
    opciones: dict,
    *,
    sufijo: str,
    secreto: str | None = None,
    papeles: list[str] | None = None,
):
    """Crea el trabajo y lleva a su ficha, que ya tiene progreso, recibo y descarga.

    Devuelve la redirección. `origenes` son los `entrada.Origen` que la pantalla ya resolvió
    —con su comprobación de raíces y de dueño hecha—; aquí no se vuelve a resolver nada.

    `secreto` es la contraseña de «Proteger». **Todo va en una transacción**, y por ella:
    sin ella el obrero podría ver el trabajo en el instante entre crearlo y dejar la
    contraseña, cogerlo, y fallar con `falta-la-contrasena` un trabajo recién pedido. Si
    guardarla falla, el trabajo no llega a existir.

    `papeles` dice qué es cada entrada cuando no son intercambiables —la hoja y la plantilla
    de «Excel a catálogo»—, en el mismo orden que `origenes`.
    """
    from django.db import transaction

    if not motor_documentos.va_por_la_cola(herramienta):
        raise ValueError(f"«{herramienta}» todavía no pasa por la cola.")

    with transaction.atomic():
        job = _crear(request, herramienta, origenes, opciones, sufijo, papeles or [])
        if secreto is not None:
            from . import secretos

            secretos.guardar(job, secreto)
    return redirect("jobs:ficha", pk=job.pk)


def _crear(request, herramienta: str, origenes: list, opciones: dict, sufijo: str, papeles):
    from apps.jobs.models import ConversionJob, EntradaDeTrabajo

    primero = origenes[0]
    job = ConversionJob.objects.create(
        owner=request.user,
        herramienta=herramienta,
        # El primero se refleja aquí para que el historial, que lee este campo, siga
        # funcionando. La lista completa, con su huella, va en `EntradaDeTrabajo`.
        source_path=str(primero.ruta),
        source_name=primero.nombre,
        source_format_code=Path(primero.nombre).suffix.lower().lstrip("."),
        target_format_code=f"doc:{herramienta}",
        options=dict(opciones),
        output_path=str(ruta_de_salida(primero, sufijo)),
    )

    for orden, origen in enumerate(origenes):
        EntradaDeTrabajo.objects.create(
            job=job,
            orden=orden,
            papel=papeles[orden] if orden < len(papeles) else "",
            ruta=str(origen.ruta),
            nombre=origen.nombre,
            subida=origen.subida,
        )
        _reclamar_subida(origen)

    job.registrar(f"Encolado: {nombre_de(herramienta)}, con {len(origenes)} archivo(s).")
    return job


def _reclamar_subida(origen) -> None:
    """Que el barrido no se lleve una subida **mientras un trabajo la necesita**.

    El modelo lo prometía en su docstring y ningún código lo hacía: una subida encolada seguía
    caducando 24 h después de subirse, estuviera o no el trabajo en marcha. La suelta el
    corredor al terminar, con margen para reintentar.
    """
    subida = getattr(origen, "subida", None)
    if subida is None:
        return
    subida.expires_at = None
    subida.save(update_fields=["expires_at", "updated_at"])
