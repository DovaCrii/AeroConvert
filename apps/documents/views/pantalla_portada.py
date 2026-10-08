"""Vistas de documentos: la portada de J.E.J. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core.entrada import Origen

from .. import cola as cola_mod
from .. import portadas as portadas_mod
from ..composicion import ComposicionInvalida


def _para_nombre(texto: str) -> str:
    """Algo seguro para el nombre del archivo: letras, números y guiones."""
    limpio = re.sub(r"[^0-9A-Za-z]+", "-", texto).strip("-")
    return limpio[:40] or "portada"


@login_required
def portada_vista(request):
    """Generar una portada de la empresa desde una plantilla Word.

    Sin las plantillas la pantalla **sigue existiendo y dice por qué no puede** (regla 4): no se
    sustituye por una portada inventada. Entrega un `.docx`; el PDF se pide después desde la
    ficha, con «Office a PDF».
    """
    disponible = portadas_mod.sondar()
    tipo_id = request.POST.get("tipo") or request.GET.get("tipo") or "documento"
    if tipo_id not in portadas_mod.TIPOS:
        tipo_id = "documento"
    tipo = portadas_mod.TIPOS[tipo_id]

    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "Texto y tablas",
        "titulo_pagina": "Portada de J.E.J.",
        "proposito": "La portada de la empresa, con el código, el título y el autor ya puestos.",
        "tipos": portadas_mod.TIPOS,
        "tipo": tipo,
        "disponible": disponible,
        "valores": {id_: (request.POST.get(id_) or "") for id_, _, _ in tipo.campos},
    }
    contexto["campos"] = [
        (id_, etiqueta, ejemplo, contexto["valores"][id_]) for id_, etiqueta, ejemplo in tipo.campos
    ]

    if request.method != "POST" or not disponible.tiene(tipo_id):
        if request.method == "POST":
            messages.error(request, f"Falta la plantilla «{tipo.archivo}» en este servidor.")
        return render(request, "documents/portada.html", contexto)

    try:
        limpios = portadas_mod.validar(tipo_id, contexto["valores"])
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/portada.html", contexto)

    plantilla = portadas_mod.carpeta() / tipo.archivo
    primero = tipo.campos[0][0]
    return cola_mod.encolar(
        request,
        "portada",
        [Origen(ruta=plantilla, nombre=tipo.archivo)],
        {"tipo": tipo_id, "valores": limpios},
        sufijo=f"_{_para_nombre(limpios[primero])}.docx",
        salida_en_trabajo=True,
    )
