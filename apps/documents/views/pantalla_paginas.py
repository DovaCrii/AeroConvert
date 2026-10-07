"""Vistas de documentos: paginas. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.core import modo as modo_mod

from .. import cola as cola_mod
from .. import firma_visible as firma_visible_mod
from .. import formularios as formularios_mod
from .. import marcas as marcas_mod
from ..composicion import ComposicionInvalida

# **Reexportado**: el índice, las pruebas y `acciones.py` lo leen de aquí desde siempre. Los
# datos viven en `herramientas.py` para que el modelo y el proceso hijo puedan leerlos sin
# importar las vistas.
from ._comun import _entero, _mirar_pdf, _origen_del_formulario


@login_required
def formularios_vista(request):
    """Rellenar los campos de un formulario PDF, y aplanarlo si se pide.

    Dos pasos como las demás: primero se mira qué campos tiene (si es que tiene), y después se
    rellena. Los campos que no son de texto ni casillas se enseñan, no se editan.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Rellenar un formulario PDF",
        "proposito": "Escribe en sus campos y, si se pide, lo aplana para entregarlo.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST":
        return render(request, "documents/formularios.html", contexto)

    cabecera, origen, error = _mirar_pdf(request)
    if error:
        messages.error(request, error)
        return render(request, "documents/formularios.html", contexto)

    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre
    contexto["cabecera"] = cabecera
    try:
        campos = formularios_mod.listar(origen.ruta)
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/formularios.html", contexto)

    if not campos:
        messages.error(request, f"{origen.nombre} no tiene campos de formulario que rellenar.")
        return render(request, "documents/formularios.html", contexto)
    contexto["campos"] = campos
    contexto["aplanar"] = request.POST.get("aplanar") == "si"

    if request.POST.get("accion") != "rellenar":
        return render(request, "documents/formularios.html", contexto)

    # **Solo lo que cambió.** Una casilla desmarcada no llega en el POST, así que su estado se
    # lee de la marca escondida `visto_*` que acompaña a cada campo.
    valores: dict[str, str | bool] = {}
    for campo in campos:
        if not campo.editable or f"visto_{campo.nombre}" not in request.POST:
            continue
        if campo.tipo == formularios_mod.CASILLA:
            nuevo = request.POST.get(f"campo_{campo.nombre}") == "si"
            if nuevo != campo.esta_marcada:
                valores[campo.nombre] = nuevo
        else:
            nuevo = (request.POST.get(f"campo_{campo.nombre}") or "").strip()
            if nuevo != campo.valor:
                valores[campo.nombre] = nuevo

    if not valores and not contexto["aplanar"]:
        messages.error(request, "No cambió ningún campo. Escriba en alguno, o pida aplanarlo.")
        return render(request, "documents/formularios.html", contexto)

    return cola_mod.encolar(
        request,
        "formularios",
        [origen],
        {"valores": valores, "aplanar": contexto["aplanar"]},
        sufijo="_aplanado.pdf" if contexto["aplanar"] else "_relleno.pdf",
    )


@login_required
def firma_visible_vista(request):
    """Poner una firma escaneada, con su fecha, en una página de un PDF.

    Dos pasos: primero se mira el PDF (cuántas páginas tiene), y en el segundo se sube la imagen
    de la firma junto con el resto de las decisiones. **No es una firma digital**, y la pantalla
    lo dice antes que nada.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Poner una firma en un PDF",
        "proposito": "Estampa una firma escaneada donde va. No es una firma digital.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
        "posiciones": firma_visible_mod.POSICIONES,
        "anchos": firma_visible_mod.ANCHOS_MM,
        "posicion": "pie-derecha",
        "ancho_mm": 45,
        "leyenda": "",
        "con_fecha": True,
    }

    if request.method != "POST":
        return render(request, "documents/firma_visible.html", contexto)

    contexto["posicion"] = request.POST.get("posicion") or "pie-derecha"
    contexto["ancho_mm"] = _entero(request.POST.get("ancho_mm"), 45)
    contexto["leyenda"] = (request.POST.get("leyenda") or "").strip()
    contexto["con_fecha"] = (
        request.POST.get("accion") != "firmar" or request.POST.get("con_fecha") == "si"
    )

    cabecera, origen, error = _mirar_pdf(request)
    if error:
        messages.error(request, error)
        return render(request, "documents/firma_visible.html", contexto)

    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre
    contexto["cabecera"] = cabecera
    contexto["pagina"] = _entero(request.POST.get("pagina"), cabecera.cuantas)

    if request.POST.get("accion") != "firmar":
        return render(request, "documents/firma_visible.html", contexto)

    try:
        firma = _origen_del_formulario(request, campo="firma", archivo="firma_subida")
        leyenda = contexto["leyenda"]
        if contexto["con_fecha"]:
            hoy = timezone.localdate().strftime("%d-%m-%Y")
            leyenda = f"{leyenda} · {hoy}" if leyenda else hoy
        leyenda = firma_visible_mod.comprobar(
            contexto["posicion"],
            contexto["ancho_mm"],
            leyenda,
            contexto["pagina"],
            cabecera.cuantas,
            origen.nombre,
        )
        # La imagen se abre aquí: si no lo es, se dice antes de encolar.
        firma_visible_mod.medir_imagen(firma.ruta)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/firma_visible.html", contexto)

    return cola_mod.encolar(
        request,
        "firma_visible",
        [origen, firma],
        {
            "pagina": contexto["pagina"],
            "posicion": contexto["posicion"],
            "ancho_mm": contexto["ancho_mm"],
            "leyenda": leyenda,
        },
        sufijo="_firmado.pdf",
    )


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
        "titulo_pagina": "Poner marca de agua",
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
