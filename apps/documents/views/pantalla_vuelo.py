"""Vistas de documentos: el vuelo de dron. Ver `apps/documents/views/__init__.py`.

Cuatro: la pantalla de entrada (`vuelo_dron_vista`), el visor del resultado (`vuelo_ver`), los datos
que dibuja el visor (`vuelo_datos`) y la miniatura de una foto (`vuelo_miniatura`).

## Quién ve qué

Todas son **de quien pidió el trabajo** (404 para cualquier otra persona, que además no confirma que
exista). La miniatura lee un archivo del disco: el nombre sale **del propio `vuelo.json`** del
trabajo, nunca de la dirección, y la carpeta se vuelve a comprobar contra las raíces permitidas en
cada petición.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from apps.core import modo as modo_mod

from .. import cola as cola_mod
from .. import vuelo_proceso, vuelo_trimble
from ..composicion import ComposicionInvalida
from ._comun import _origen_del_formulario

EXTENSIONES_DE_TRAYECTORIA = (".csv", ".txt")
EXTENSIONES_DE_DISPAROS = (".mrk", ".txt", ".csv")

#: Cuánto mide el lado mayor de una miniatura.
LADO_DE_MINIATURA = 480

#: Una foto de dron de 60 megapíxeles cabe de sobra; más que esto no es una foto de un vuelo.
LIMITE_DE_PIXELES = 150_000_000

ESCALAS = vuelo_trimble.ESCALAS_DE_TIEMPO


def _sistemas_para_declarar() -> dict[str, str]:
    """Los que se pueden declarar a mano: los del marco ITRF (los antiguos no pasan a lat/lon)."""
    return {str(e): vuelo_trimble.CANDIDATOS[e] for e in sorted(vuelo_trimble.USABLES)}


def _hay(request, campo: str, subida: str) -> bool:
    return bool(request.FILES.get(subida) or (request.POST.get(campo) or "").strip())


@login_required
def vuelo_dron_vista(request):
    """Los tres archivos de Trimble y las fotos, y el proceso que los junta."""
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "Vuelos de dron",
        "titulo_pagina": "Corregir un vuelo de dron",
        "proposito": "La posición corregida de cada foto, contrastada con la posición de referencia, a la vista.",
        "escalas": ESCALAS,
        "sistemas": _sistemas_para_declarar(),
        "escala": "GPST",
        "sistema": "medir",
        "aplicar_desfase": True,
        "trayectoria_texto": "",
        "disparos_texto": "",
        "referencia_texto": "",
        "carpeta_texto": "",
    }
    if request.method != "POST":
        return render(request, "documents/vuelo_dron.html", contexto)

    contexto["escala"] = request.POST.get("escala_de_tiempo") or ""
    contexto["sistema"] = request.POST.get("sistema") or "medir"
    contexto["aplicar_desfase"] = request.POST.get("aplicar_desfase") == "on"
    for campo in ("trayectoria", "disparos", "referencia"):
        contexto[f"{campo}_texto"] = (request.POST.get(campo) or "").strip()
    contexto["carpeta_texto"] = (request.POST.get("carpeta_de_fotos") or "").strip()

    try:
        if not _hay(request, "trayectoria", "trayectoria_subida"):
            raise ComposicionInvalida("Falta la trayectoria: el CSV que exportó Trimble.")
        if not _hay(request, "disparos", "disparos_subida"):
            raise ComposicionInvalida("Faltan los disparos de la cámara: el archivo .MRK del dron.")
        trayectoria = _origen_del_formulario(
            request, campo="trayectoria", archivo="trayectoria_subida"
        )
        disparos = _origen_del_formulario(request, campo="disparos", archivo="disparos_subida")
        referencia = (
            _origen_del_formulario(request, campo="referencia", archivo="referencia_subida")
            if _hay(request, "referencia", "referencia_subida")
            else None
        )
        if Path(trayectoria.nombre).suffix.lower() not in EXTENSIONES_DE_TRAYECTORIA:
            raise ComposicionInvalida(f"{trayectoria.nombre} no es un CSV de trayectoria.")
        if Path(disparos.nombre).suffix.lower() not in EXTENSIONES_DE_DISPAROS:
            raise ComposicionInvalida(f"{disparos.nombre} no es un .MRK ni una lista de tiempos.")
        if contexto["escala"] not in ESCALAS:
            raise ComposicionInvalida(
                "Elija la escala de tiempo de la trayectoria: no se supone."
                if not contexto["escala"]
                else "Esa escala de tiempo no es de las que se ofrecen."
            )
        if contexto["sistema"] != "medir" and contexto["sistema"] not in _sistemas_para_declarar():
            raise ComposicionInvalida("Ese sistema no es de los que se ofrecen.")
        carpeta = ""
        if contexto["carpeta_texto"]:
            ruta = modo_mod.comprobar_ruta(contexto["carpeta_texto"])
            if not ruta.is_dir():
                raise ComposicionInvalida("Eso no es una carpeta de fotos.")
            carpeta = str(ruta)

        # El sistema se mide (o se comprueba) **aquí**, con el formulario delante: un sistema que no
        # coincide se dice ahora y no en una ficha roja de la cola.
        posiciones = (
            vuelo_trimble.leer_posiciones_por_foto(referencia.ruta.read_bytes())
            if referencia
            else None
        )
        vuelo_proceso.elegir_sistema(contexto["sistema"], posiciones)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/vuelo_dron.html", contexto)

    from apps.jobs.models import EntradaDeTrabajo

    entradas = [trayectoria, disparos]
    papeles = [EntradaDeTrabajo.TRAYECTORIA, EntradaDeTrabajo.DISPAROS]
    if referencia:
        entradas.append(referencia)
        papeles.append(EntradaDeTrabajo.REFERENCIA)
    return cola_mod.encolar(
        request,
        "vuelo_dron",
        entradas,
        {
            "escala_de_tiempo": contexto["escala"],
            # Lo que se pidió, no lo que salió: el hijo repite la medición (es barata) y así el
            # recibo dice «medido» o «declarado y comprobado», que es lo que pasó.
            "sistema": contexto["sistema"],
            "aplicar_desfase": contexto["aplicar_desfase"],
            "carpeta_de_fotos": carpeta,
        },
        sufijo="_vuelo.zip",
        papeles=papeles,
    )


# --- El visor ---------------------------------------------------------------------------------


def _vuelo_de(request, pk):
    """El trabajo de vuelo **de esta persona** y ya terminado, o 404."""
    from apps.jobs.models import ConversionJob

    job = get_object_or_404(
        ConversionJob, pk=pk, owner=request.user, herramienta="vuelo_dron", status="done"
    )
    if not job.output_path or not Path(job.output_path).is_file():
        raise Http404("El resultado de este vuelo ya no está.")
    return job


def _leer_datos(job) -> dict:
    try:
        with zipfile.ZipFile(job.output_path) as paquete:
            return json.loads(paquete.read("vuelo.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as fallo:
        raise Http404("Este vuelo no trae datos para el visor.") from fallo


@login_required
@require_GET
def vuelo_ver(request, pk):
    job = _vuelo_de(request, pk)
    datos = _leer_datos(job)
    return render(
        request,
        "documents/vuelo_visor.html",
        {
            "seccion": "pdf",
            "etiqueta_seccion": "Vuelos de dron",
            "titulo_pagina": "El vuelo en el mapa",
            "proposito": "El recorrido, los puntos de cada foto y las fotos mismas.",
            "job": job,
            "sistema": datos["sistema"],
            "altura": datos["altura"],
            "fotos": len(datos["fotos"]),
            "con_miniaturas": bool((job.options or {}).get("carpeta_de_fotos")),
        },
    )


@login_required
@require_GET
def vuelo_datos(request, pk):
    respuesta = JsonResponse(
        _leer_datos(_vuelo_de(request, pk)), json_dumps_params={"ensure_ascii": False}
    )
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


@login_required
@require_GET
def vuelo_miniatura(request, pk, n: int):
    """La foto número `n` del vuelo, achicada. El nombre sale del `vuelo.json`, no de la URL."""
    from PIL import Image, UnidentifiedImageError

    job = _vuelo_de(request, pk)
    carpeta_texto = (job.options or {}).get("carpeta_de_fotos") or ""
    if not carpeta_texto:
        raise Http404("Este vuelo no trae carpeta de fotos.")
    fotos = _leer_datos(job)["fotos"]
    if not 1 <= n <= len(fotos) or not fotos[n - 1].get("miniatura"):
        raise Http404("Esa foto no está en la carpeta.")
    # El nombre **real** del archivo en la carpeta (no el del CSV): sin separadores ni «..».
    nombre = fotos[n - 1].get("archivo") or ""
    if not nombre or Path(nombre).name != nombre:
        raise Http404("Nombre de foto no válido.")
    try:
        carpeta = modo_mod.comprobar_ruta(carpeta_texto)  # otra vez: las raíces pudieron cambiar
    except modo_mod.RutaNoPermitida as fallo:
        raise Http404("La carpeta de fotos ya no está permitida.") from fallo
    ruta = carpeta / nombre
    if not ruta.is_file():
        raise Http404("La foto ya no está en la carpeta.")
    # Un enlace simbólico dentro de la carpeta que apunte fuera de las raíces no se sirve.
    real = ruta.resolve()
    if not real.is_relative_to(carpeta.resolve()):
        raise Http404("La foto no está en la carpeta.")
    try:
        modo_mod.comprobar_ruta(str(real))
    except modo_mod.RutaNoPermitida as fallo:
        raise Http404("La foto está fuera de las carpetas permitidas.") from fallo

    try:
        with Image.open(real) as imagen:
            if imagen.width * imagen.height > LIMITE_DE_PIXELES:
                raise Http404("La foto es demasiado grande para una miniatura.")
            imagen.draft("RGB", (LADO_DE_MINIATURA * 2, LADO_DE_MINIATURA * 2))  # JPEG: lee a 1/8
            imagen.thumbnail((LADO_DE_MINIATURA, LADO_DE_MINIATURA))
            salida = io.BytesIO()
            imagen.convert("RGB").save(salida, "JPEG", quality=80)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as fallo:
        raise Http404("La foto no se pudo abrir.") from fallo
    respuesta = HttpResponse(salida.getvalue(), content_type="image/jpeg")
    respuesta["Cache-Control"] = "private, max-age=3600"
    return respuesta
