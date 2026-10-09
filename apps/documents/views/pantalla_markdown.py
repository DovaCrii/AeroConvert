"""Vistas de documentos: markdown. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core import modo as modo_mod

from .. import a_markdown as a_markdown_mod
from .. import cola as cola_mod
from ..composicion import ComposicionInvalida

# **Reexportado**: el índice, las pruebas y `acciones.py` lo leen de aquí desde siempre. Los
# datos viven en `herramientas.py` para que el modelo y el proceso hijo puedan leerlos sin
# importar las vistas.
from ._comun import _origen_del_formulario

#: Lo que `Hacer un libro EPUB` acepta: lo que ya se sabe pasar a Markdown, y el Markdown mismo.
#: El EPUB no está: de un EPUB a otro no hay nada que hacer.
EXTENSIONES_DE_EPUB = frozenset(
    {".pdf", ".docx", ".html", ".htm", ".md", ".markdown", ".txt", ".xlsx", ".csv"}
)

#: Lo que `Markdown a PDF` acepta como entrada. Lo demás se rechaza antes de encolar.
EXTENSIONES_DE_MARKDOWN = frozenset({".md", ".markdown", ".txt"})


@login_required
def a_markdown(request):
    """Sacar el contenido de un archivo y dejarlo en Markdown.

    **Una pantalla para los seis orígenes.** Excel, CSV, Word, PDF, EPUB y una página guardada
    hacen todos lo mismo desde fuera —eliges el archivo y recibes un `.md`— y lo que cambia es
    lo que pasa por dentro, que lo decide la extensión. Seis pantallas idénticas salvo por el
    título serían seis sitios donde arreglar el mismo fallo.

    El catálogo sí tiene seis entradas, con `?de=xlsx` y compañía: quien busca escribe «excel
    a markdown», no «a markdown». Es el mismo reparto que los destinos geoespaciales.
    """
    pedido = (request.GET.get("de") or "").strip().lstrip(".").lower()
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "Texto y tablas",
        "titulo_pagina": "Sacar el contenido a Markdown",
        "proposito": (
            "Para pegarlo en un correo, en una ficha o en un tablero sin perder la tabla ni "
            "los títulos."
        ),
        "origenes": a_markdown_mod.ORIGENES,
        "de": pedido if f".{pedido}" in a_markdown_mod.ORIGENES else "",
        "no_sobrevive": a_markdown_mod.NO_SOBREVIVE_DE_WORD,
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST":
        return render(request, "documents/a_markdown.html", contexto)

    try:
        origen = _origen_del_formulario(request)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/a_markdown.html", contexto)

    # Lo que se sabe sin abrir el archivo, aquí: de una extensión que no se lee no hace falta
    # esperar a la cola para enterarse. Un escaneo sin texto, en cambio, solo se sabe
    # abriéndolo — y eso ya no es un error sino un desenlace del trabajo.
    herramienta = a_markdown_mod.HERRAMIENTA_POR_EXTENSION.get(Path(origen.nombre).suffix.lower())
    if herramienta is None:
        conocidas = ", ".join(sorted(a_markdown_mod.ORIGENES))
        messages.error(
            request,
            f"De «{Path(origen.nombre).suffix or origen.nombre}» no se saca Markdown. "
            f"Se puede con: {conocidas}.",
        )
        return render(request, "documents/a_markdown.html", contexto)

    return cola_mod.encolar(request, herramienta, [origen], {}, sufijo=".md")


@login_required
def de_markdown(request):
    """Markdown a PDF: el camino de vuelta."""
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "Texto y tablas",
        "titulo_pagina": "Markdown a PDF",
        "proposito": "Para entregar lo que se redactó en Markdown.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST":
        return render(request, "documents/de_markdown.html", contexto)

    try:
        origen = _origen_del_formulario(request)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/de_markdown.html", contexto)

    # Sin esto, un `.pdf` como entrada daba un destino igual al propio archivo y el trabajo
    # lo sobrescribía «verificado»: la salida es `<nombre>.pdf` al lado de la entrada.
    if Path(origen.ruta).suffix.lower() not in EXTENSIONES_DE_MARKDOWN:
        messages.error(
            request,
            "Este archivo no es Markdown ni texto. Se admite "
            + ", ".join(sorted(EXTENSIONES_DE_MARKDOWN))
            + ".",
        )
        return render(request, "documents/de_markdown.html", contexto)

    return cola_mod.encolar(request, "md_a_pdf", [origen], {}, sufijo=".pdf")


@login_required
def a_epub(request):
    """Hacer un libro EPUB de un PDF, un Word, una página web o un Markdown."""
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "Texto y tablas",
        "titulo_pagina": "Hacer un libro EPUB",
        "proposito": "Para leer un informe o un manual en el teléfono o en un lector de libros.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
        "acepta": ",".join(sorted(EXTENSIONES_DE_EPUB)),
    }

    if request.method != "POST":
        return render(request, "documents/a_epub.html", contexto)

    try:
        origen = _origen_del_formulario(request)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/a_epub.html", contexto)

    if Path(origen.nombre).suffix.lower() not in EXTENSIONES_DE_EPUB:
        messages.error(
            request,
            f"De «{Path(origen.nombre).suffix or origen.nombre}» no se hace un libro. Se admite "
            + ", ".join(sorted(EXTENSIONES_DE_EPUB))
            + ".",
        )
        return render(request, "documents/a_epub.html", contexto)

    opciones = {
        "titulo": (request.POST.get("titulo") or "").strip()[:200],
        "autor": (request.POST.get("autor") or "").strip()[:200],
    }
    return cola_mod.encolar(request, "a_epub", [origen], opciones, sufijo=".epub")
