"""Vistas de documentos: reparar un PDF y página web a PDF.

Ver `apps/documents/views/__init__.py`.
"""

from __future__ import annotations

from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core import modo as modo_mod

from .. import cola as cola_mod
from .. import html_a_pdf as html_a_pdf_mod
from ..composicion import ComposicionInvalida
from ._comun import _origen_del_formulario


@login_required
def reparar_vista(request):
    """Recuperar un PDF que no abre.

    **No mira el documento antes**: las demás pantallas leen la cabecera y se niegan si no se
    puede, y justo ese es el archivo que aquí se quiere arreglar. El único aviso previo es el de
    que no sea de otro tipo; lo que pasa de ahí lo dice el trabajo.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Reparar un PDF dañado",
        "proposito": "Recupera las páginas que se puedan leer de un PDF que no abre.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST":
        return render(request, "documents/reparar.html", contexto)

    try:
        origen = _origen_del_formulario(request)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/reparar.html", contexto)

    if Path(origen.nombre).suffix.lower() != ".pdf":
        messages.error(request, f"{origen.nombre} no es un PDF (.pdf).")
        return render(request, "documents/reparar.html", contexto)

    return cola_mod.encolar(request, "reparar", [origen], {}, sufijo="_reparado.pdf")


@login_required
def html_a_pdf_vista(request):
    """Una página web guardada, a PDF (texto, títulos y tablas)."""
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "Texto y tablas",
        "titulo_pagina": "Página web a PDF",
        "proposito": "El texto y las tablas de una página guardada, en un PDF.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST":
        return render(request, "documents/html_a_pdf.html", contexto)

    try:
        origen = _origen_del_formulario(request)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/html_a_pdf.html", contexto)

    if Path(origen.nombre).suffix.lower() not in html_a_pdf_mod.EXTENSIONES:
        messages.error(
            request,
            "Este archivo no es una página web. Se admite "
            + ", ".join(sorted(html_a_pdf_mod.EXTENSIONES))
            + ".",
        )
        return render(request, "documents/html_a_pdf.html", contexto)

    return cola_mod.encolar(request, "html_a_pdf", [origen], {}, sufijo=".pdf")
