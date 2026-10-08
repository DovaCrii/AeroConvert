"""Vistas de documentos: la traza de un video de dron. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core import modo as modo_mod

from .. import cola as cola_mod
from .. import telemetria as telemetria_mod
from ..composicion import ComposicionInvalida
from ._comun import _origen_del_formulario


def _intervalo(texto) -> int:
    if texto is None or str(texto).strip() == "":
        return 1  # el que viene elegido
    try:
        return int(str(texto).strip())
    except ValueError:
        return -1


def _desfase(texto: str) -> float | None:
    limpio = (texto or "").strip().replace(",", ".")
    if not limpio:
        return None
    return float(limpio)


@login_required
def telemetria_vista(request):
    """El `.SRT` de un DJI a una traza GPX o KML."""
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "Imagen, video y planta",
        "titulo_pagina": "Traza de un video de dron",
        "proposito": "Por dónde voló el dron, a partir del .SRT que graba junto al video.",
        "formatos": telemetria_mod.FORMATOS,
        "intervalos": telemetria_mod.INTERVALOS_S,
        "formato": "gpx",
        "cada_s": 1,
        "desfase": "",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST":
        return render(request, "documents/telemetria.html", contexto)

    contexto["formato"] = request.POST.get("formato") or "gpx"
    contexto["cada_s"] = _intervalo(request.POST.get("cada_s"))
    contexto["desfase"] = (request.POST.get("desfase") or "").strip()

    try:
        origen = _origen_del_formulario(request)
        desfase = _desfase(contexto["desfase"])
        if contexto["formato"] not in telemetria_mod.FORMATOS:
            raise ComposicionInvalida(f"«{contexto['formato']}» no es un formato de los que hay.")
        if contexto["cada_s"] not in telemetria_mod.INTERVALOS_S:
            raise ComposicionInvalida("Ese intervalo no es de los que se ofrecen.")
        if desfase is not None and not -14 <= desfase <= 14:
            raise ComposicionInvalida("La diferencia con UTC va de −14 a +14 horas.")
        if Path(origen.nombre).suffix.lower() != ".srt":
            raise ComposicionInvalida(f"{origen.nombre} no es un .SRT.")
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/telemetria.html", contexto)
    except ValueError:
        messages.error(request, "La diferencia con UTC es un número de horas, por ejemplo −4.")
        return render(request, "documents/telemetria.html", contexto)

    return cola_mod.encolar(
        request,
        "telemetria",
        [origen],
        {"formato": contexto["formato"], "cada_s": contexto["cada_s"], "desfase_h": desfase},
        sufijo=f".{contexto['formato']}",
    )
