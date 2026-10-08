"""Vistas de documentos: PDF a PDF/A. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core import modo as modo_mod

from .. import cola as cola_mod
from .. import pdfa as pdfa_mod
from ..composicion import ComposicionInvalida
from ._comun import _origen_del_formulario


@login_required
def pdf_a_vista(request):
    """PDF a PDF/A-2b, diciendo **antes** qué se comprueba y qué no (sin veraPDF, la
    conformidad)."""
    ghostscript = pdfa_mod.sondar()
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "PDF a PDF/A para archivar",
        "proposito": "Para entregar o guardar un PDF que se lea igual dentro de veinte años.",
        "ghostscript": ghostscript,
        "con_verapdf": bool(pdfa_mod.sondar_verapdf()),
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }
    if request.method != "POST" or not ghostscript:
        return render(request, "documents/pdf_a.html", contexto)
    try:
        origen = _origen_del_formulario(request)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/pdf_a.html", contexto)
    if not origen.nombre.lower().endswith(".pdf"):
        messages.error(request, f"{origen.nombre} no es un PDF.")
        return render(request, "documents/pdf_a.html", contexto)
    return cola_mod.encolar(request, "pdf_a", [origen], {}, sufijo="_pdfa.pdf")
