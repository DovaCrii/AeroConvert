"""Vistas de documentos: paginas. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .. import cola as cola_mod
from .. import marcas as marcas_mod
from ..composicion import ComposicionInvalida

# **Reexportado**: el índice, las pruebas y `acciones.py` lo leen de aquí desde siempre. Los
# datos viven en `herramientas.py` para que el modelo y el proceso hijo puedan leerlos sin
# importar las vistas.
from ._comun import _entero, _mirar_pdf


@login_required
def numerar_vista(request):
    """Poner el número de página.

    Es lo que casi siempre hace falta **justo después de unir**: una entrega hecha de cinco
    PDF no tiene numeración, porque cada uno traía la suya.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Numerar las páginas",
        "proposito": "Pone el número en cada hoja, respetando el tamaño y el giro de cada una.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
        "posiciones": marcas_mod.POSICIONES,
        "formatos": marcas_mod.FORMATOS,
        "posicion": "pie-derecha",
        "formato": "{n} / {total}",
        "desde": 1,
        "empezar_en": 1,
    }

    if request.method != "POST":
        return render(request, "documents/numerar.html", contexto)

    contexto["posicion"] = request.POST.get("posicion") or "pie-derecha"
    contexto["formato"] = request.POST.get("formato") or "{n} / {total}"
    contexto["desde"] = _entero(request.POST.get("desde"), 1)
    contexto["empezar_en"] = _entero(request.POST.get("empezar_en"), 1)

    cabecera, origen, error = _mirar_pdf(request)
    if error:
        messages.error(request, error)
        return render(request, "documents/numerar.html", contexto)

    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre
    contexto["cabecera"] = cabecera

    if request.POST.get("accion") != "numerar":
        return render(request, "documents/numerar.html", contexto)

    # **Lo que se puede decir sin abrir el documento, aquí y al instante.** Una página de
    # inicio imposible no tiene que esperar a la cola para fallar.
    try:
        marcas_mod.comprobar_numeracion(
            contexto["posicion"],
            contexto["formato"],
            contexto["desde"],
            len(cabecera.paginas),
            origen.nombre,
        )
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/numerar.html", contexto)

    # Y lo que puede tardar, a la cola: con progreso, recibo, historial y **descarga**, que
    # para un archivo subido no existía.
    return cola_mod.encolar(
        request,
        "numerar",
        [origen],
        {
            "posicion": contexto["posicion"],
            "formato": contexto["formato"],
            "desde": contexto["desde"],
            "empezar_en": contexto["empezar_en"],
        },
        sufijo="_numerado.pdf",
    )


@login_required
def marca_vista(request):
    """Estampar un texto cruzando cada página.

    Un plano que se emite para revisión tiene que ir marcado: uno sin marca que circula por
    correo acaba en obra como si estuviera aprobado.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Marca de agua",
        "proposito": "Estampa un texto en todas las páginas, sin tapar lo que hay debajo.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
        "opacidades": marcas_mod.OPACIDADES,
        "sugerencias": ("BORRADOR", "CONFIDENCIAL", "NO VÁLIDO PARA CONSTRUCCIÓN", "COPIA"),
        "texto": "",
        "opacidad": "normal",
        "diagonal": True,
        "maximo": marcas_mod.MAXIMO_TEXTO,
    }

    if request.method != "POST":
        return render(request, "documents/marca.html", contexto)

    contexto["texto"] = (request.POST.get("texto") or "").strip()
    contexto["opacidad"] = request.POST.get("opacidad") or "normal"
    contexto["diagonal"] = request.POST.get("orientacion") != "horizontal"

    cabecera, origen, error = _mirar_pdf(request)
    if error:
        messages.error(request, error)
        return render(request, "documents/marca.html", contexto)

    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre
    contexto["cabecera"] = cabecera

    if request.POST.get("accion") != "marcar":
        return render(request, "documents/marca.html", contexto)

    try:
        texto = marcas_mod.comprobar_marca(contexto["texto"], contexto["opacidad"])
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/marca.html", contexto)

    return cola_mod.encolar(
        request,
        "marca",
        [origen],
        {
            "texto": texto,
            "opacidad": contexto["opacidad"],
            "orientacion": "diagonal" if contexto["diagonal"] else "horizontal",
        },
        sufijo="_marcado.pdf",
    )
