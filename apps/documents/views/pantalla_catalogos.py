"""Vistas de documentos: catalogos. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core import modo as modo_mod

from .. import catalogos as catalogos_mod
from .. import cola as cola_mod
from ..composicion import ComposicionInvalida

# **Reexportado**: el índice, las pruebas y `acciones.py` lo leen de aquí desde siempre. Los
# datos viven en `herramientas.py` para que el modelo y el proceso hijo puedan leerlos sin
# importar las vistas.
from ._comun import _origen_del_formulario


@login_required
def catalogo_a_excel(request):
    """Un catálogo de tubería a una hoja de cálculo, una hoja por tabla.

    **Esta va primero de las dos**, y no por orden alfabético: nadie escribe cincuenta y dos
    columnas desde cero. El camino real es sacar el catálogo que ya se tiene, cambiar lo que
    haga falta, y volver a meterlo con la otra.
    """
    access = catalogos_mod.sondar()
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "Catálogos de tubería",
        "titulo_pagina": "Catálogo Plant 3D a Excel",
        "proposito": "Para poder editarlo sin abrir Access, y volver a meterlo después.",
        "access": access,
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST" or not access:
        return render(request, "documents/catalogo_a_excel.html", contexto)

    try:
        origen = _origen_del_formulario(request)
        # Se abre aquí antes de encolar: un archivo que no es un catálogo se dice con el
        # formulario delante, no en una ficha roja. Las tablas salen en el recibo.
        catalogos_mod.esquema(origen.ruta)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/catalogo_a_excel.html", contexto)

    return cola_mod.encolar(request, "catalogo_excel", [origen], {}, sufijo=".xlsx")


@login_required
def excel_a_catalogo(request):
    """La hoja de cálculo de vuelta al catálogo, **sobre el catálogo original**.

    Dos archivos, y el segundo no es un extra: es el que pone el esquema. Ver el docstring de
    `catalogos.desde_excel`, donde está por qué se copia la plantilla en vez de crear una base
    nueva.
    """
    access = catalogos_mod.sondar()
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "Catálogos de tubería",
        "titulo_pagina": "Excel a catálogo Plant 3D",
        "proposito": "El camino de vuelta. Hacen falta los dos: la hoja editada y el catálogo.",
        "access": access,
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST" or not access:
        return render(request, "documents/excel_a_catalogo.html", contexto)

    from apps.jobs.models import EntradaDeTrabajo

    try:
        hoja = _origen_del_formulario(request)
        plantilla = _origen_del_formulario(request, campo="plantilla", archivo="plantilla_subida")
        # La plantilla se abre aquí: si no es un catálogo, se dice antes de encolar.
        catalogos_mod.esquema(plantilla.ruta)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/excel_a_catalogo.html", contexto)

    return cola_mod.encolar(
        request,
        "excel_catalogo",
        [hoja, plantilla],
        {},
        sufijo=".mdb",
        papeles=[EntradaDeTrabajo.HOJA, EntradaDeTrabajo.PLANTILLA],
    )
