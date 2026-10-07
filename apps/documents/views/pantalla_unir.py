"""Vistas de documentos: unir y organizar. Ver `apps/documents/views/__init__.py`.

**Dos pantallas, una sola máquina.** «Organizar páginas» es la receta de «Unir» con un solo
archivo: mismas miniaturas, mismas acciones (subir, bajar, quitar, girar y duplicar), mismo hijo
en la cola. Lo único que cambia es qué dice la pantalla, de dónde se eligen los archivos y cómo
se llama lo que sale. Por eso es un `Modo` y no un segundo módulo que se desfase del primero.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotModified
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.core import entrada as entrada_mod
from apps.core import modo as modo_mod
from apps.core import subidas as subidas_mod
from apps.formats import pdf as lectura_pdf

from .. import cola as cola_mod
from .. import miniaturas
from .. import receta as receta_mod
from ..composicion import GIROS, ComposicionInvalida

# **Reexportado**: el índice, las pruebas y `acciones.py` lo leen de aquí desde siempre. Los
# datos viven en `herramientas.py` para que el modelo y el proceso hijo puedan leerlos sin
# importar las vistas.
from ._comun import _contexto, _origenes_pedidos

#: Las acciones de la receta que cambian una fila. Cada una es una función de `receta.py`.
ACCIONES_DE_FILA = ("subir", "bajar", "quitar", "girar", "duplicar")


@dataclass(frozen=True)
class Modo:
    """Lo que distingue a una pantalla de la otra."""

    herramienta: str
    pantalla: str
    componer: str
    sufijo: str
    titulo: str
    proposito: str
    #: Una sola pieza: organizar trabaja sobre un PDF, y para juntar varios está «Unir».
    un_solo_archivo: bool


UNIR = Modo(
    herramienta="unir",
    pantalla="documents:unir",
    componer="documents:componer",
    sufijo="_unido.pdf",
    titulo="Junta varios PDF en uno",
    proposito="Elige qué páginas entran, en qué orden, y gira las láminas que lo necesiten.",
    un_solo_archivo=False,
)

ORGANIZAR = Modo(
    herramienta="organizar",
    pantalla="documents:organizar",
    componer="documents:componer_organizar",
    sufijo="_organizado.pdf",
    titulo="Organiza las páginas de un PDF",
    proposito="Gira, reordena, quita o repite páginas, viendo cada una antes de generarlo.",
    un_solo_archivo=True,
)


def _pantalla(request, modo: Modo):
    """La pantalla. Llega vacía, o con `?ruta=` desde la ficha de un PDF."""
    ruta_inicial = (request.GET.get("ruta") or "").strip()
    return render(
        request,
        "documents/unir.html",
        _contexto([], [], _extra(modo, {"rutas_texto": ruta_inicial})),
    )


def _extra(modo: Modo, mas: dict | None = None) -> dict:
    extra = {
        "modo": modo.herramienta,
        "url_componer": modo.componer,
        "titulo_pagina": modo.titulo,
        "proposito": modo.proposito,
        "un_solo_archivo": modo.un_solo_archivo,
    }
    extra.update(mas or {})
    return extra


@login_required
def unir(request):
    return _pantalla(request, UNIR)


@login_required
def organizar(request):
    return _pantalla(request, ORGANIZAR)


@login_required
@require_POST
def componer_vista(request):
    return _componer(request, UNIR)


@login_required
@require_POST
def componer_organizar_vista(request):
    return _componer(request, ORGANIZAR)


def _componer(request, modo: Modo):
    """Todas las acciones de la pantalla. Cuál se pidió lo dice `accion`.

    **Los archivos subidos se añaden a la lista de texto y ahí se acaba su particularidad.**
    Desde el segundo POST, la pantalla es exactamente tan sin estado como era: la lista viaja
    entera en el campo, la receta indexa posiciones de esa lista, y `receta.py` no se entera
    de que existen las subidas. Que el módulo cuyo docstring entero trata de la ausencia de
    estado no haya tenido que cambiar es la mejor señal de que la costura está en su sitio.
    """
    texto = request.POST.get("archivos_texto", "")

    # Con `enctype="multipart/form-data"`, **todos** los POST son multipart -- tambien los de
    # subir, bajar y girar --, asi que aqui casi siempre no hay nada y hay que aguantarlo.
    llegados = request.FILES.getlist("archivos")
    if llegados:
        try:
            nuevas = subidas_mod.guardar_varios(llegados, usuario=request.user)
        except ValidationError as fallo:
            messages.error(request, "; ".join(fallo.messages))
            return redirect(modo.pantalla)
        texto = "\n".join(filter(None, [texto.strip(), *(s.token for s in nuevas)]))

    try:
        origenes = _origenes_pedidos(texto, request.user)
    except modo_mod.RutaNoPermitida as fallo:
        messages.error(request, str(fallo))
        return redirect(modo.pantalla)

    if not origenes:
        messages.error(request, "No indicaste ningún archivo.")
        return redirect(modo.pantalla)

    if modo.un_solo_archivo and len(origenes) > 1:
        # No se descarta en silencio el segundo: se dice, y se dice a dónde ir.
        messages.error(
            request,
            "Organizar trabaja sobre un solo PDF. Para juntar varios, use «Unir PDF».",
        )
        return redirect(modo.pantalla)

    entradas = receta_mod.desde_texto(request.POST.get("receta", ""), len(origenes))
    accion, _, argumento = (request.POST.get("accion") or "").partition(":")

    # Al añadir archivos, la receta anterior ya no describe la lista: se rehace.
    if accion == "analizar" or llegados or not entradas:
        try:
            entradas = _receta_inicial(origenes)
        except ComposicionInvalida as fallo:
            messages.error(request, str(fallo))
            return render(request, "documents/unir.html", _contexto(origenes, [], _extra(modo)))
    elif accion in ACCIONES_DE_FILA:
        indice = int(argumento) if argumento.isdigit() else -1
        entradas = getattr(receta_mod, accion)(entradas, indice)
    elif accion == "generar":
        return _generar(request, origenes, entradas, modo)

    return render(request, "documents/unir.html", _contexto(origenes, entradas, _extra(modo)))


@login_required
def miniatura(request):
    """El PNG de una página. La pantalla pone una por fila.

    **La caché la hace el navegador, no nosotros.** La respuesta lleva un `ETag` que
    depende del archivo —su fecha y su tamaño— más la página, el giro y el ancho, así que
    al pulsar «bajar» las cincuenta y seis miniaturas vuelven con un 304 y no se dibuja
    ninguna otra vez. Guardarlas en disco traería una carpeta que crece, que hay que
    barrer, y que se queda obsoleta cuando el archivo cambia.

    El origen pasa por la misma puerta que la inspección: una ruta es lectura del disco, y
    una vista que sirve imágenes no es excepción. Con un archivo subido hay además algo que
    antes no se podía hacer: **comprobar el dueño**, porque una subida sí tiene uno.
    """
    try:
        origen = entrada_mod.resolver(request.GET.get("ruta") or "", usuario=request.user)
    except modo_mod.RutaNoPermitida:
        return HttpResponseBadRequest("Ruta no permitida.")

    ruta = origen.ruta

    try:
        pagina = int(request.GET.get("pagina", "1"))
        giro = int(request.GET.get("giro", "0"))
        ancho = int(request.GET.get("ancho", miniaturas.ANCHO))
    except ValueError:
        return HttpResponseBadRequest("Parámetros no válidos.")

    if giro not in GIROS:
        giro = 0

    sello = f'"{miniaturas.etiqueta(ruta, pagina, giro, ancho)}"'
    if request.headers.get("If-None-Match") == sello:
        return HttpResponseNotModified()

    try:
        png = miniaturas.dibujar(ruta, pagina, giro=giro, ancho=ancho)
    except miniaturas.NoSePudoDibujar:
        # Una miniatura que no sale no puede tumbar la pantalla: la fila se queda sin
        # imagen y con su texto, que sigue diciendo de qué página se trata.
        return HttpResponseBadRequest("No se pudo dibujar esa página.")

    respuesta = HttpResponse(png, content_type="image/png")
    respuesta["ETag"] = sello
    # `private`: es el archivo de alguien, no se guarda en ningún intermedio compartido.
    respuesta["Cache-Control"] = "private, max-age=3600"
    return respuesta


def _receta_inicial(origenes: list):
    """Todas las páginas de todos los archivos, en el orden en que se pegaron."""
    entradas = []
    for indice, origen in enumerate(origenes):
        try:
            cabecera = lectura_pdf.leer_cabecera(origen.ruta)
        except lectura_pdf.NoEsPdf as fallo:
            raise ComposicionInvalida(f"{origen.nombre}: {fallo}") from fallo
        if cabecera.cifrado:
            raise ComposicionInvalida(
                f"{origen.nombre} pide contraseña. Ábrelo con ella y guárdalo sin ella."
            )
        entradas.extend(receta_mod.Entrada(indice, pagina.numero) for pagina in cabecera.paginas)
    return entradas


def _generar(request, origenes: list, entradas, modo: Modo = UNIR):
    """Encola la receta tal como quedó en la pantalla.

    **La receta viaja en texto, no en páginas resueltas**: es la misma cadena que la pantalla
    lleva de un POST al siguiente, indexa posiciones de la lista de archivos, y esa lista es
    justo el orden de `EntradaDeTrabajo`. Así el hijo la entiende con `receta.py` sin que
    haya una segunda forma de escribirla. Una receta vacía no llega aquí: `_componer` la
    rehace antes con todas las páginas.
    """
    return cola_mod.encolar(
        request,
        modo.herramienta,
        origenes,
        {"receta": receta_mod.a_texto(entradas)},
        sufijo=modo.sufijo,
    )
