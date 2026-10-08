"""Vistas de documentos: un plano DXF a una lámina. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core import modo as modo_mod

from .. import cola as cola_mod
from .. import dxf_lamina as lamina_mod
from ..composicion import ComposicionInvalida
from ._comun import _origen_del_formulario


@login_required
def dxf_lamina_vista(request):
    """Un plano DXF dibujado en una lámina PDF o SVG."""
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "Documentos",
        "titulo_pagina": "Plano DXF a PDF",
        "proposito": "Un plano DXF en una lámina de A4 a A0, centrada y con margen.",
        "papeles": lamina_mod.ETIQUETAS_PAPEL,
        "formatos": lamina_mod.FORMATOS,
        "papel": "a3",
        "formato": "pdf",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST":
        return render(request, "documents/dxf_lamina.html", contexto)

    contexto["papel"] = request.POST.get("papel") or "a3"
    contexto["formato"] = request.POST.get("formato") or "pdf"

    try:
        origen = _origen_del_formulario(request)
        if contexto["papel"] not in lamina_mod.PAPELES_MM:
            raise ComposicionInvalida("Ese papel no es de los que se ofrecen.")
        if contexto["formato"] not in lamina_mod.FORMATOS:
            raise ComposicionInvalida("Ese formato no es de los que se ofrecen.")
        if Path(origen.nombre).suffix.lower() == ".dwg":
            raise ComposicionInvalida(
                f"{origen.nombre} es un DWG: páselo antes a DXF desde «Convertir»."
            )
        if Path(origen.nombre).suffix.lower() != ".dxf":
            raise ComposicionInvalida(f"{origen.nombre} no es un DXF.")
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/dxf_lamina.html", contexto)

    return cola_mod.encolar(
        request,
        "dxf_lamina",
        [origen],
        {"papel": contexto["papel"], "formato": contexto["formato"]},
        sufijo=f".{contexto['formato']}",
    )
