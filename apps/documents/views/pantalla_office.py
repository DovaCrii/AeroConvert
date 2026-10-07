"""Vistas de documentos: office. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core import modo as modo_mod

from .. import cola as cola_mod
from .. import office as office_mod
from ..composicion import ComposicionInvalida

# **Reexportado**: el índice, las pruebas y `acciones.py` lo leen de aquí desde siempre. Los
# datos viven en `herramientas.py` para que el modelo y el proceso hijo puedan leerlos sin
# importar las vistas.
from ._comun import _origen_del_formulario


@login_required
def office_vista(request):
    """Word, Excel o PowerPoint a PDF, con el Office instalado.

    De un solo paso, a diferencia de las demás: no hay nada que previsualizar de un `.docx`
    sin abrirlo, y abrirlo ya es la conversión.
    """
    office = office_mod.sondar()
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Word, Excel o PowerPoint a PDF",
        "proposito": (
            "Lo convierte el Office del equipo, así que el PDF sale idéntico al original."
        ),
        "office": office,
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
        "ajustar_ancho": True,
    }

    if request.method != "POST" or not office:
        return render(request, "documents/office.html", contexto)

    contexto["ajustar_ancho"] = request.POST.get("ajustar_ancho") == "si"

    try:
        origen = _origen_del_formulario(request)
    except modo_mod.RutaNoPermitida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/office.html", contexto)

    contexto["ruta_texto"] = origen.token
    contexto["nombre_origen"] = origen.nombre

    # Por la extensión del nombre que se reconoce, que es el que trae la del original.
    try:
        programa = office_mod.programa_de(origen.nombre)
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/office.html", contexto)
    if not office.tiene(programa):
        messages.error(request, f"{office_mod.NOMBRES[programa]} no está instalado en este equipo.")
        return render(request, "documents/office.html", contexto)

    return cola_mod.encolar(
        request,
        "office",
        [origen],
        {"ajustar_ancho": contexto["ajustar_ancho"]},
        sufijo=".pdf",
    )


@login_required
def a_word_vista(request):
    """PDF a Word, y **con el aviso delante**.

    De dos pasos a propósito, porque lo que hay que decir antes de convertir no se puede
    decir sin mirar el archivo: un PDF escaneado no tiene texto dentro, así que lo que vuelve
    son las mismas fotos pegadas en un documento de Word. Y eso Word lo hace sin quejarse,
    devolviendo medio mega y un código de salida cero.
    """
    office = office_mod.sondar()
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "PDF a Word",
        "proposito": "Para poder editarlo. Mire antes lo que va a recibir de verdad.",
        "office": office,
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST" or not office.tiene("word"):
        return render(request, "documents/a_word.html", contexto)

    try:
        origen = _origen_del_formulario(request)
        ruta = origen.ruta
        que_trae = office_mod.mirar_pdf(ruta)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/a_word.html", contexto)

    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre
    contexto["que_trae"] = que_trae

    if request.POST.get("accion") != "convertir":
        return render(request, "documents/a_word.html", contexto)

    return cola_mod.encolar(request, "a_word", [origen], {}, sufijo=".docx")
