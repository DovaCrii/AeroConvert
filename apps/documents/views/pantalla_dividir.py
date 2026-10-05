"""Vistas de documentos: dividir. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from collections import Counter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core import modo as modo_mod
from apps.formats import pdf as lectura_pdf

from .. import cola as cola_mod
from .. import dividir as dividir_mod
from ..composicion import ComposicionInvalida

# **Reexportado**: el índice, las pruebas y `acciones.py` lo leen de aquí desde siempre. Los
# datos viven en `herramientas.py` para que el modelo y el proceso hijo puedan leerlos sin
# importar las vistas.
from ._comun import _origen_del_formulario


@login_required
def dividir_vista(request):
    """Partir un PDF: una parte, o cada hoja por su lado.

    Dos pasos como en unir —mirar y después hacer— porque partir sin ver cuántas páginas
    hay obliga a abrir el documento en otro sitio para saber qué rangos escribir.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Dividir un PDF",
        "proposito": "Saca una parte, o parte uno grande en hojas sueltas.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
        "modo": "rangos",
        "rangos": "",
    }

    if request.method != "POST":
        return render(request, "documents/dividir.html", contexto)

    try:
        origen = _origen_del_formulario(request)
    except modo_mod.RutaNoPermitida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/dividir.html", contexto)

    ruta = origen.ruta
    # **El token, no la ruta.** Para un archivo subido son cosas distintas, y devolver la del
    # servidor dejaría que el POST siguiente la tratara como una ruta del disco.
    contexto["ruta_texto"] = origen.token
    contexto["nombre_origen"] = origen.nombre
    contexto["modo"] = request.POST.get("modo") or "rangos"
    contexto["rangos"] = (request.POST.get("rangos") or "").strip()

    try:
        cabecera = lectura_pdf.leer_cabecera(ruta)
    except lectura_pdf.NoEsPdf as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/dividir.html", contexto)

    if cabecera.cifrado:
        messages.error(request, f"{ruta.name} pide contraseña, así que no se puede partir.")
        return render(request, "documents/dividir.html", contexto)

    contexto["cabecera"] = cabecera
    contexto["ruta"] = origen.token

    if request.POST.get("accion") != "partir":
        return render(request, "documents/dividir.html", contexto)

    try:
        trozos = (
            dividir_mod.una_por_pagina(cabecera.cuantas)
            if contexto["modo"] == "hojas"
            else dividir_mod.analizar_rangos(contexto["rangos"], cabecera.cuantas)
        )
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/dividir.html", contexto)

    # Dos trozos iguales saldrían con el mismo nombre, y el segundo pisaría al primero.
    # Antes pasaba en silencio; dentro de un zip, además, lo dejaría con una pieza de menos.
    veces = Counter(trozos)  # lineal: `trozos.count(t)` dentro del bucle era cuadrático
    repetidos = sorted({t.sufijo.lstrip("_") for t in trozos if veces[t] > 1})
    if repetidos:
        messages.error(
            request,
            f"«{', '.join(repetidos)}» está más de una vez. Cada trozo es un archivo, "
            "y dos iguales saldrían con el mismo nombre.",
        )
        return render(request, "documents/dividir.html", contexto)

    # Un trozo sale suelto, con el nombre que ya tenía; varios, juntos en un zip.
    sufijo = f"{trozos[0].sufijo}.pdf" if len(trozos) == 1 else "_partes.zip"
    return cola_mod.encolar(
        request,
        "dividir",
        [origen],
        {"trozos": [[t.desde, t.hasta] for t in trozos]},
        sufijo=sufijo,
    )
