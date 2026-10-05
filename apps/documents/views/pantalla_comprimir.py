"""Vistas de documentos: comprimir. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core import modo as modo_mod

from .. import cola as cola_mod
from .. import comprimir as comprimir_mod
from .. import ocr as ocr_mod
from ..composicion import ComposicionInvalida

# **Reexportado**: el índice, las pruebas y `acciones.py` lo leen de aquí desde siempre. Los
# datos viven en `herramientas.py` para que el modelo y el proceso hijo puedan leerlos sin
# importar las vistas.
from ._comun import _mirar_pdf, _origen_del_formulario, _ppp


@login_required
def comprimir(request):
    """Bajar el peso de un PDF, diciendo cuánto baja **antes** de descargarlo.

    ## Por qué el resultado se enseña y no se entrega directo

    Comprimir es la única herramienta de la casa donde el resultado correcto puede ser «no
    hagas nada»: un PDF que ya venía optimizado puede engordar al recomprimirlo. Entregar eso
    después de que alguien haya pulsado «comprimir» es la peor respuesta posible — parece que
    funcionó, y empeoró el problema que se venía a resolver.

    Así que la vista enseña los dos pesos y el porcentaje, y cuando no vale la pena lo dice
    con el archivo intacto. Eso no es un error: es la respuesta.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Comprimir un PDF",
        "proposito": "Para que un juego de planos entre en un correo sin dejar de leerse.",
        "resoluciones": comprimir_mod.RESOLUCIONES,
        # **No con `_entero`**, que convierte todo lo menor que 1 en el valor por omisión: el 0
        # es «sin tocar las imágenes», la única opción que promete no estropear nada, y
        # llegaba como 200 ppp. Estuvo así desde que entró Comprimir, porque ninguna prueba
        # pasaba por la pantalla.
        "ppp": _ppp(request.POST.get("ppp")),
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST":
        return render(request, "documents/comprimir.html", contexto)

    try:
        origen = _origen_del_formulario(request)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/comprimir.html", contexto)

    # La resolución se comprueba aquí: un campo de ppp que no está en la lista es evadible
    # desde fuera del navegador, y no hace falta esperar a la cola para decirlo.
    if contexto["ppp"] not in comprimir_mod.RESOLUCIONES:
        messages.error(
            request, f"«{contexto['ppp']}» no es una de las resoluciones que se ofrecen."
        )
        return render(request, "documents/comprimir.html", contexto)

    # A la cola, y en el carril pesado: un juego de doscientas láminas escaneadas tarda, y
    # dentro de la petición moría a los 120 s. Si comprimir no vale la pena, lo dice la ficha
    # del trabajo con los dos pesos —ni verde ni rojo— y no se escribe nada.
    return cola_mod.encolar(
        request, "comprimir", [origen], {"ppp": contexto["ppp"]}, sufijo="_ligero.pdf"
    )


@login_required
def ocr_vista(request):
    """Reconocer el texto de un escaneo, **mirando antes si hace falta**.

    ## Por qué va en dos tiempos, como «PDF a Word»

    Lo que hay que decir antes de empezar no se puede decir sin abrir el archivo: un PDF que
    ya trae su capa de texto no necesita nada, y pasarlo por reconocimiento tardaría minutos
    para dejarlo **peor** — el OCR se equivoca y el texto incrustado no.

    Así que el primer paso mira, lo dice, y el segundo hace. Igual que allí, y por la misma
    razón: el consejo que llega después de la conversión ya no es un consejo.
    """
    tesseract = ocr_mod.sondar()
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Reconocer el texto de un escaneo",
        "proposito": "Para poder buscar y copiar dentro de un PDF que solo tiene imágenes.",
        "tesseract": tesseract,
        "idiomas": ocr_mod.IDIOMAS,
        "idioma": request.POST.get("idioma") or "spa",
        "tope_paginas": ocr_mod.TOPE_PAGINAS,
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST" or not tesseract:
        return render(request, "documents/ocr.html", contexto)

    cabecera, origen, error = _mirar_pdf(request)
    if error:
        messages.error(request, error)
        return render(request, "documents/ocr.html", contexto)

    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre
    contexto["ya_tenia_texto"] = ocr_mod.ya_tiene_texto(origen.ruta)
    # **Cuánto va a tardar, antes de pulsar.** Con quinientas páginas son cuarenta minutos, y
    # saberlo después ya no sirve para decidir si partirlo.
    contexto["paginas"] = cabecera.cuantas
    contexto["estimacion"] = ocr_mod.estimacion(cabecera.cuantas)
    contexto["pasa_del_tope"] = cabecera.cuantas > ocr_mod.TOPE_PAGINAS

    if request.POST.get("accion") != "reconocer":
        return render(request, "documents/ocr.html", contexto)

    idioma = contexto["idioma"]
    if idioma not in ocr_mod.IDIOMAS:
        messages.error(request, f"«{idioma}» no es uno de los idiomas que se ofrecen.")
        return render(request, "documents/ocr.html", contexto)
    if not tesseract.tiene(idioma):
        messages.error(
            request,
            f"Tesseract no tiene instalado el idioma «{ocr_mod.IDIOMAS[idioma]}». "
            f"Los que hay: {', '.join(sorted(tesseract.idiomas))}.",
        )
        return render(request, "documents/ocr.html", contexto)
    if contexto["pasa_del_tope"]:
        messages.error(
            request,
            f"{origen.nombre} tiene {cabecera.cuantas} páginas y el tope son "
            f"{ocr_mod.TOPE_PAGINAS}. Pártelo antes con «Dividir PDF».",
        )
        return render(request, "documents/ocr.html", contexto)

    return cola_mod.encolar(
        request,
        "ocr",
        [origen],
        # Las páginas van para el plazo: el corredor da un minuto a cada una.
        {"idioma": idioma, "paginas": cabecera.cuantas},
        sufijo="_con_texto.pdf",
    )
