"""Vistas de documentos: trabajar un video de dron. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core import entrada as entrada_mod
from apps.core import modo as modo_mod

from .. import cola as cola_mod
from .. import video as video_mod
from ..composicion import ComposicionInvalida
from ._comun import _origen_del_formulario


def _numero(texto) -> float | None:
    limpio = str(texto or "").strip().replace(",", ".")
    if not limpio:
        return None
    try:
        return float(limpio)
    except ValueError:
        return None


def _srt_junto_al_video(origen, usuario):
    """El `.SRT` que DJI graba al lado del video, si el video viene de la carpeta compartida."""
    if origen.subida is not None:
        return None
    for sufijo in (".SRT", ".srt"):
        candidato = Path(origen.ruta).with_suffix(sufijo)
        if candidato.is_file():
            try:
                return entrada_mod.resolver(str(candidato), usuario=usuario)
            except modo_mod.RutaNoPermitida:
                return None
    return None


@login_required
def video_vista(request):
    """Fotogramas para fotogrametría, o comprimir, recortar o quitar el audio de un video."""
    ffmpeg = video_mod.sondar()
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "Vuelos de dron",
        "titulo_pagina": "Trabajar un video de dron",
        "proposito": "Fotogramas para fotogrametría, o el video más liviano, recortado o mudo.",
        "ffmpeg": ffmpeg,
        "operaciones": video_mod.OPERACIONES,
        "cada_segundos": video_mod.CADA_SEGUNDOS,
        "cada_metros": video_mod.CADA_METROS,
        "operacion": request.POST.get("operacion") or "fotogramas",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }
    if request.method != "POST" or not ffmpeg:
        return render(request, "documents/video.html", contexto)

    try:
        origen = _origen_del_formulario(request)
        if Path(origen.nombre).suffix.lower() not in video_mod.EXTENSIONES:
            raise ComposicionInvalida(f"{origen.nombre} no es un video (MP4, MOV, MKV o AVI).")
        operacion = contexto["operacion"]
        if operacion not in video_mod.OPERACIONES:
            raise ComposicionInvalida("Esa operación no es de las que se ofrecen.")
        opciones: dict = {"operacion": operacion}
        origenes = [origen]
        if operacion == "fotogramas":
            criterio = request.POST.get("criterio") or "segundos"
            if criterio == "metros":
                cada_m = _numero(request.POST.get("cada_m"))
                if cada_m not in video_mod.CADA_METROS:
                    raise ComposicionInvalida("Esa distancia no es de las que se ofrecen.")
                opciones["cada_m"] = cada_m
            else:
                cada_s = _numero(request.POST.get("cada_s"))
                if cada_s not in video_mod.CADA_SEGUNDOS:
                    raise ComposicionInvalida("Ese intervalo no es de los que se ofrecen.")
                opciones["cada_s"] = cada_s
            srt = None
            if request.FILES.get("srt_subida"):
                srt = _origen_del_formulario(request, campo="srt", archivo="srt_subida")
                if Path(srt.nombre).suffix.lower() != ".srt":
                    raise ComposicionInvalida(f"{srt.nombre} no es un .SRT.")
            else:
                srt = _srt_junto_al_video(origen, request.user)
            if srt is not None:
                origenes.append(srt)
            elif "cada_m" in opciones:
                raise ComposicionInvalida(
                    "Para sacar fotogramas cada tantos metros hace falta el .SRT del dron: súbalo, "
                    "o deje el video en la carpeta compartida junto a él."
                )
        elif operacion == "recortar":
            inicio, fin = _numero(request.POST.get("inicio_s")), _numero(request.POST.get("fin_s"))
            if inicio is None or fin is None or not 0 <= inicio < fin:
                raise ComposicionInvalida(
                    "Para recortar, el inicio tiene que ser menor que el fin."
                )
            opciones.update(inicio_s=inicio, fin_s=fin)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/video.html", contexto)

    sufijo = "_fotogramas.zip" if operacion == "fotogramas" else f"_{operacion}.mp4"
    return cola_mod.encolar(request, "video", origenes, opciones, sufijo=sufijo)
