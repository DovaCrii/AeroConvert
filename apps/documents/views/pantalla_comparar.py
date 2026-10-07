"""Vistas de documentos: comparar dos PDF. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core import modo as modo_mod
from apps.formats import pdf as lectura_pdf

from .. import cola as cola_mod
from ._comun import _origen_del_formulario


@login_required
def comparar_vista(request):
    """Comparar dos versiones de un PDF y ver dónde cambió cada hoja.

    Dos archivos, **en orden**: el primero es el antes y el segundo el después. La pantalla lo
    dice con esas palabras, porque «A» y «B» no dicen cuál es cuál.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Comparar dos PDF",
        "proposito": "Dónde cambió cada hoja entre la versión de antes y la de después.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST":
        return render(request, "documents/comparar.html", contexto)

    try:
        antes = _origen_del_formulario(request)
        despues = _origen_del_formulario(request, campo="despues", archivo="despues_subida")
        for origen in (antes, despues):
            cabecera = lectura_pdf.leer_cabecera(origen.ruta)
            if cabecera.cifrado:
                raise lectura_pdf.NoEsPdf(
                    f"{origen.nombre} pide contraseña. Quítesela primero en «Proteger o "
                    "desbloquear PDF»."
                )
    except (modo_mod.RutaNoPermitida, lectura_pdf.NoEsPdf) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/comparar.html", contexto)

    return cola_mod.encolar(request, "comparar", [antes, despues], {}, sufijo="_comparacion.pdf")
