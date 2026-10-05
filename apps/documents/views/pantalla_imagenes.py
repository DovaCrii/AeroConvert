"""Vistas de documentos: imagenes. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import render

from apps.core import modo as modo_mod
from apps.core import subidas as subidas_mod

from .. import a_imagenes as a_imagenes_mod
from .. import cola as cola_mod
from .. import dividir as dividir_mod
from ..composicion import ComposicionInvalida

# **Reexportado**: el índice, las pruebas y `acciones.py` lo leen de aquí desde siempre. Los
# datos viven en `herramientas.py` para que el modelo y el proceso hijo puedan leerlos sin
# importar las vistas.
from ._comun import _mirar_pdf, _origenes_pedidos


@login_required
def imagenes_vista(request):
    """Fotos o escaneos a un solo PDF."""
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Imágenes a PDF",
        "proposito": "Fotos o escaneos en un solo documento.",
        "rutas_texto": "",
        "tamano": "a4",
        "extensiones": ", ".join(sorted(dividir_mod.IMAGENES)),
    }

    if request.method != "POST":
        return render(request, "documents/imagenes.html", contexto)

    texto = request.POST.get("archivos_texto", "")
    contexto["tamano"] = request.POST.get("tamano") or "a4"

    llegadas = request.FILES.getlist("archivos")
    if llegadas:
        try:
            nuevas = subidas_mod.guardar_varios(llegadas, usuario=request.user)
        except ValidationError as fallo:
            messages.error(request, "; ".join(fallo.messages))
            return render(request, "documents/imagenes.html", contexto)
        texto = "\n".join(filter(None, [texto.strip(), *(s.token for s in nuevas)]))

    try:
        origenes = _origenes_pedidos(texto, request.user)
    except modo_mod.RutaNoPermitida as fallo:
        contexto["rutas_texto"] = texto
        messages.error(request, str(fallo))
        return render(request, "documents/imagenes.html", contexto)

    # Los identificadores, no las rutas: ver `_contexto` de unir.
    contexto["rutas_texto"] = "\n".join(o.token for o in origenes)

    if not origenes:
        messages.error(request, "No indicaste ninguna imagen.")
        return render(request, "documents/imagenes.html", contexto)

    if contexto["tamano"] not in ("a4", "imagen"):
        messages.error(request, f"«{contexto['tamano']}» no es un tamaño de página conocido.")
        return render(request, "documents/imagenes.html", contexto)

    # La extensión se mira aquí, que es gratis y deja el formulario como estaba. Abrir cada
    # imagen —lo caro— lo hace el hijo, que es donde puede tardar.
    ajenas = [
        o.nombre for o in origenes if Path(o.nombre).suffix.lower() not in dividir_mod.IMAGENES
    ]
    if ajenas:
        messages.error(
            request,
            f"{', '.join(ajenas)} no es una imagen de las que se admiten "
            f"({contexto['extensiones']}).",
        )
        return render(request, "documents/imagenes.html", contexto)

    return cola_mod.encolar(
        request, "imagenes", origenes, {"tamano": contexto["tamano"]}, sufijo="_imagenes.pdf"
    )


@login_required
def a_imagenes_vista(request):
    """Sacar páginas como JPG o PNG.

    Mismo camino de dos pasos que dividir —mirar y después hacer—, y por la misma razón:
    para escribir «3-7» hay que saber cuántas páginas hay.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "PDF a imágenes",
        "proposito": "Una lámina como imagen, para meterla donde un PDF no se pega.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
        "formato": "png",
        "ppp": a_imagenes_mod.RESOLUCIONES,
        "ppp_elegido": 150,
        "rangos": "",
    }

    if request.method != "POST":
        return render(request, "documents/a_imagenes.html", contexto)

    contexto["formato"] = request.POST.get("formato") or "png"
    contexto["rangos"] = (request.POST.get("rangos") or "").strip()
    try:
        contexto["ppp_elegido"] = int(request.POST.get("ppp") or 150)
    except ValueError:
        contexto["ppp_elegido"] = 150

    cabecera, origen, error = _mirar_pdf(request)
    if error:
        messages.error(request, error)
        return render(request, "documents/a_imagenes.html", contexto)

    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre
    contexto["cabecera"] = cabecera

    if request.POST.get("accion") != "convertir":
        return render(request, "documents/a_imagenes.html", contexto)

    # Lo que se puede comprobar aquí se comprueba aquí: descubrirlo en la cola manda a la
    # persona a una ficha roja y de vuelta a esta pantalla, con el formulario vacío.
    if contexto["formato"] not in a_imagenes_mod.FORMATOS:
        messages.error(request, f"«{contexto['formato']}» no es un formato de los que se hacen.")
        return render(request, "documents/a_imagenes.html", contexto)
    if contexto["ppp_elegido"] not in a_imagenes_mod.RESOLUCIONES:
        messages.error(request, f"«{contexto['ppp_elegido']}» no es una de las resoluciones.")
        return render(request, "documents/a_imagenes.html", contexto)

    try:
        trozos = (
            dividir_mod.analizar_rangos(contexto["rangos"], cabecera.cuantas)
            if contexto["rangos"]
            else dividir_mod.una_por_pagina(cabecera.cuantas)
        )
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/a_imagenes.html", contexto)

    # Los rangos se solapan sin problema —«1-3, 2» es pedir la 2 dos veces—, así que se
    # cuentan páginas, no trozos.
    paginas = sorted({n for t in trozos for n in range(t.desde, t.hasta + 1)})
    formato = contexto["formato"]
    sufijo = f"_{paginas[0]}.{formato}" if len(paginas) == 1 else f"_imagenes_{formato}.zip"
    return cola_mod.encolar(
        request,
        "a_imagenes",
        [origen],
        {"paginas": paginas, "formato": formato, "ppp": contexto["ppp_elegido"]},
        sufijo=sufijo,
    )
