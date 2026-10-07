"""Vistas de documentos: recortar y cambiar el tamaño. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .. import cola as cola_mod
from .. import tamano as tamano_mod
from ..composicion import ComposicionInvalida
from ._comun import _mirar_pdf


def _decimal(texto, por_omision: float) -> float:
    try:
        return float(str(texto or "").replace(",", ".").strip())
    except ValueError:
        return por_omision


@login_required
def tamano_vista(request):
    """Recortar los márgenes de un PDF o pasarlo a otra hoja.

    Dos pasos como las demás. Los tres modos comparten pantalla porque salen del mismo
    problema —«no entra en mi papel»— y se eligen con un botón de opción cada uno.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Recortar y cambiar el tamaño",
        "proposito": "Quita el blanco que sobra o pasa el juego a otro papel, sin deformarlo.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
        "hojas": tamano_mod.ETIQUETAS,
        "modo": "contenido",
        "margen_mm": 5,
        "hoja": "a4",
        "lados": {"arriba": 0, "derecha": 0, "abajo": 0, "izquierda": 0},
    }

    if request.method != "POST":
        return render(request, "documents/tamano.html", contexto)

    contexto["modo"] = request.POST.get("modo") or "contenido"
    contexto["margen_mm"] = _decimal(request.POST.get("margen_mm"), 5)
    contexto["hoja"] = request.POST.get("hoja") or "a4"
    contexto["lados"] = {
        lado: _decimal(request.POST.get(f"lado_{lado}"), 0)
        for lado in ("arriba", "derecha", "abajo", "izquierda")
    }

    cabecera, origen, error = _mirar_pdf(request)
    if error:
        messages.error(request, error)
        return render(request, "documents/tamano.html", contexto)

    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre
    contexto["cabecera"] = cabecera

    if request.POST.get("accion") != "hacer":
        return render(request, "documents/tamano.html", contexto)

    modo = contexto["modo"]
    # Lo que se puede decir sin abrir el documento se dice aquí, antes de encolar.
    if modo == "contenido":
        if not 0 <= contexto["margen_mm"] <= 50:
            messages.error(request, "El margen va de 0 a 50 mm.")
            return render(request, "documents/tamano.html", contexto)
        opciones = {"modo": "contenido", "margen_mm": contexto["margen_mm"]}
        sufijo = "_recortado.pdf"
    elif modo == "mano":
        lados = contexto["lados"]
        if not any(lados.values()) or any(
            not 0 <= v <= tamano_mod.MAXIMO_RECORTE_MM for v in lados.values()
        ):
            messages.error(
                request,
                f"Escriba cuántos milímetros quita de algún lado (entre 0 y "
                f"{int(tamano_mod.MAXIMO_RECORTE_MM)}).",
            )
            return render(request, "documents/tamano.html", contexto)
        opciones = {"modo": "mano", "lados_mm": lados}
        sufijo = "_recortado.pdf"
    elif modo == "hoja":
        if contexto["hoja"] not in tamano_mod.TAMANOS_MM:
            messages.error(request, f"«{contexto['hoja']}» no es una hoja de las que se ofrecen.")
            return render(request, "documents/tamano.html", contexto)
        opciones = {"modo": "hoja", "hoja": contexto["hoja"]}
        sufijo = f"_{contexto['hoja']}.pdf"
    else:
        messages.error(request, f"«{modo}» no es una de las tres cosas que se hacen aquí.")
        return render(request, "documents/tamano.html", contexto)

    try:
        return cola_mod.encolar(request, "tamano", [origen], opciones, sufijo=sufijo)
    except ComposicionInvalida as fallo:  # pragma: no cover - la cola no levanta esto
        messages.error(request, str(fallo))
        return render(request, "documents/tamano.html", contexto)
