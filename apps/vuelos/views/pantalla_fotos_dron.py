"""Vistas de documentos: fotos de dron. Ver `apps/vuelos/views/__init__.py`."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import render

from apps.core import modo as modo_mod
from apps.core import subidas as subidas_mod
from apps.documents import cola as cola_mod
from apps.documents.views._comun import _origenes_pedidos
from apps.vuelos import fotos_dron as fotos_mod


@login_required
def fotos_dron_vista(request):
    """Quitar o conservar la posición de las fotos de un vuelo, sacarla a un archivo y renombrar."""
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Limpiar fotos de dron",
        "proposito": "La posición de las fotos: quitarla, sacarla a un mapa y renombrar.",
        "rutas_texto": "",
        "gps_opciones": fotos_mod.GPS,
        "nombres_opciones": fotos_mod.NOMBRES,
        "posiciones_opciones": fotos_mod.POSICIONES,
        "gps": "conservar",
        "nombres": "igual",
        "posiciones": "",
    }

    if request.method != "POST":
        return render(request, "vuelos/fotos_dron.html", contexto)

    contexto["gps"] = request.POST.get("gps") or "conservar"
    contexto["nombres"] = request.POST.get("nombres") or "igual"
    contexto["posiciones"] = request.POST.get("posiciones") or ""
    texto = request.POST.get("archivos_texto", "")

    llegadas = request.FILES.getlist("archivos")
    if llegadas:
        try:
            nuevas = subidas_mod.guardar_varios(llegadas, usuario=request.user)
        except ValidationError as fallo:
            messages.error(request, "; ".join(fallo.messages))
            return render(request, "vuelos/fotos_dron.html", contexto)
        texto = "\n".join(filter(None, [texto.strip(), *(s.token for s in nuevas)]))

    try:
        origenes = _origenes_pedidos(texto, request.user)
    except modo_mod.RutaNoPermitida as fallo:
        contexto["rutas_texto"] = texto
        messages.error(request, str(fallo))
        return render(request, "vuelos/fotos_dron.html", contexto)
    contexto["rutas_texto"] = "\n".join(o.token for o in origenes)

    problema = ""
    if not origenes:
        problema = "No indicó ninguna foto."
    elif len(origenes) > fotos_mod.MAXIMO_FOTOS:
        problema = f"El máximo son {fotos_mod.MAXIMO_FOTOS} fotos por vez."
    elif contexto["gps"] not in fotos_mod.GPS:
        problema = "Esa opción de posición no es de las que se ofrecen."
    elif contexto["nombres"] not in fotos_mod.NOMBRES:
        problema = "Esa forma de nombrar no es de las que se ofrecen."
    elif contexto["posiciones"] not in fotos_mod.POSICIONES:
        problema = "Ese formato de posiciones no es de los que se ofrecen."
    else:
        problema = next((m for o in origenes if (m := fotos_mod.motivo_si_no_se_lee(o.nombre))), "")
    if problema:
        messages.error(request, problema)
        return render(request, "vuelos/fotos_dron.html", contexto)

    return cola_mod.encolar(
        request,
        "fotos_dron",
        origenes,
        {
            "gps": contexto["gps"],
            "nombres": contexto["nombres"],
            "posiciones": contexto["posiciones"],
        },
        sufijo="_fotos.zip",
    )
