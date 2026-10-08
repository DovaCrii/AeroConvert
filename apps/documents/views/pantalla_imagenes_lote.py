"""Vistas de documentos: convertir imágenes por lote. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import render

from apps.core import modo as modo_mod
from apps.core import subidas as subidas_mod

from .. import cola as cola_mod
from .. import imagenes_lote as lote_mod
from ._comun import _origenes_pedidos


def _entero(texto, por_omision: int) -> int:
    try:
        return int(str(texto).strip())
    except (TypeError, ValueError):
        return por_omision


@login_required
def imagenes_lote_vista(request):
    """Cambiar de formato, achicar, girar, recortar y comprimir varias imágenes de una vez."""
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Convertir imágenes",
        "proposito": "Varias fotos a la vez: formato, tamaño, giro, recorte y compresión.",
        "rutas_texto": "",
        "salidas": lote_mod.ETIQUETAS_DE_SALIDA,
        "lados": lote_mod.LADOS,
        "giros": lote_mod.GIROS,
        "recortes": lote_mod.RECORTES,
        "calidades": lote_mod.CALIDADES,
        "formato": "jpg",
        "lado_max": 2048,
        "giro": "exif",
        "recorte": "",
        "calidad": 85,
        "leidas": ", ".join(sorted(e.lstrip(".") for e in lote_mod.extensiones_admitidas())),
    }

    if request.method != "POST":
        return render(request, "documents/imagenes_lote.html", contexto)

    contexto["formato"] = request.POST.get("formato") or "jpg"
    contexto["lado_max"] = _entero(request.POST.get("lado_max"), 2048)
    contexto["giro"] = request.POST.get("giro") or "exif"
    contexto["recorte"] = request.POST.get("recorte") or ""
    contexto["calidad"] = _entero(request.POST.get("calidad"), 85)
    texto = request.POST.get("archivos_texto", "")

    llegadas = request.FILES.getlist("archivos")
    if llegadas:
        try:
            nuevas = subidas_mod.guardar_varios(llegadas, usuario=request.user)
        except ValidationError as fallo:
            messages.error(request, "; ".join(fallo.messages))
            return render(request, "documents/imagenes_lote.html", contexto)
        texto = "\n".join(filter(None, [texto.strip(), *(s.token for s in nuevas)]))

    try:
        origenes = _origenes_pedidos(texto, request.user)
    except modo_mod.RutaNoPermitida as fallo:
        contexto["rutas_texto"] = texto
        messages.error(request, str(fallo))
        return render(request, "documents/imagenes_lote.html", contexto)
    contexto["rutas_texto"] = "\n".join(o.token for o in origenes)

    problema = ""
    if not origenes:
        problema = "No indicó ninguna imagen."
    elif len(origenes) > lote_mod.MAXIMO_IMAGENES:
        problema = f"El máximo son {lote_mod.MAXIMO_IMAGENES} imágenes por lote."
    elif contexto["formato"] not in lote_mod.SALIDAS:
        problema = f"«{contexto['formato']}» no es un formato de salida de los que se hacen."
    elif contexto["lado_max"] not in lote_mod.LADOS:
        problema = "Ese tamaño no es de los que se ofrecen."
    elif contexto["giro"] not in lote_mod.GIROS:
        problema = "Ese giro no es de los que se ofrecen."
    elif contexto["recorte"] not in lote_mod.RECORTES:
        problema = "Esa proporción no es de las que se ofrecen."
    elif contexto["calidad"] not in lote_mod.CALIDADES:
        problema = "Esa calidad no es de las que se ofrecen."
    else:
        # La extensión se mira aquí, gratis: abrir cada imagen lo hace el hijo.
        problema = next((m for o in origenes if (m := lote_mod.motivo_si_no_se_lee(o.nombre))), "")
    if problema:
        messages.error(request, problema)
        return render(request, "documents/imagenes_lote.html", contexto)

    return cola_mod.encolar(
        request,
        "imagenes_lote",
        origenes,
        {
            "formato": contexto["formato"],
            "lado_max": contexto["lado_max"],
            "giro": contexto["giro"],
            "recorte": contexto["recorte"],
            "calidad": contexto["calidad"],
        },
        sufijo="_imagenes.zip",
    )
