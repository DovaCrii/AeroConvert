"""Vistas de documentos: unir. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from pathlib import Path

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


@login_required
def unir(request):
    """La pantalla. Llega vacía, o con `?ruta=` desde la ficha de un PDF."""
    ruta_inicial = (request.GET.get("ruta") or "").strip()
    return render(
        request,
        "documents/unir.html",
        _contexto([], [], {"rutas_texto": ruta_inicial}),
    )


@login_required
@require_POST
def componer_vista(request):
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
            return redirect("documents:unir")
        texto = "\n".join(filter(None, [texto.strip(), *(s.token for s in nuevas)]))

    try:
        origenes = _origenes_pedidos(texto, request.user)
    except modo_mod.RutaNoPermitida as fallo:
        messages.error(request, str(fallo))
        return redirect("documents:unir")

    if not origenes:
        messages.error(request, "No indicaste ningún archivo.")
        return redirect("documents:unir")

    entradas = receta_mod.desde_texto(request.POST.get("receta", ""), len(origenes))
    accion, _, argumento = (request.POST.get("accion") or "").partition(":")

    # Al añadir archivos, la receta anterior ya no describe la lista: se rehace.
    if accion == "analizar" or llegados or not entradas:
        try:
            entradas = _receta_inicial(origenes)
        except ComposicionInvalida as fallo:
            messages.error(request, str(fallo))
            return render(request, "documents/unir.html", _contexto(origenes, []))
    elif accion in ("subir", "bajar", "quitar", "girar"):
        indice = int(argumento) if argumento.isdigit() else -1
        entradas = getattr(receta_mod, accion)(entradas, indice)
    elif accion == "generar":
        return _generar(request, origenes, entradas)

    return render(request, "documents/unir.html", _contexto(origenes, entradas))


@login_required
def descargar(request, pk):
    """Entrega un archivo que una de estas pantallas escribió.

    **Por identificador y no por ruta**, y esa es toda la razón de que exista una fila. Una
    vista que aceptara `?ruta=<absoluta>` convertiría una herramienta que escribe en lectura
    de cualquier cosa del recurso compartido, por GET y sin testigo: pasaría la comprobación
    de raíces —y por tanto sería «permitida»— y bastaría un enlace en un correo para sacar un
    archivo a través del navegador de otra persona.

    404 y no 403 cuando es de otro, por lo mismo que las fichas de trabajo: no confirmar que
    un identificador ajeno es válido.
    """
    from django.http import FileResponse
    from django.shortcuts import get_object_or_404

    from apps.core.models import Resultado

    fila = get_object_or_404(Resultado, pk=pk, owner=request.user)
    ruta = Path(fila.ruta)

    if not ruta.exists():
        messages.error(
            request,
            f"{fila.nombre} ya no está donde se dejó. Puede que alguien lo haya movido desde "
            "la carpeta compartida, o que ya se barriera.",
        )
        return redirect("documents:inicio")

    return FileResponse(
        open(ruta, "rb"),  # noqa: SIM115 - FileResponse se encarga de cerrarlo
        as_attachment=True,
        filename=fila.nombre,
    )


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


def _generar(request, origenes: list, entradas):
    """Encola la receta tal como quedó en la pantalla.

    **La receta viaja en texto, no en páginas resueltas**: es la misma cadena que la pantalla
    lleva de un POST al siguiente, indexa posiciones de la lista de archivos, y esa lista es
    justo el orden de `EntradaDeTrabajo`. Así el hijo la entiende con `receta.py` sin que
    haya una segunda forma de escribirla. Una receta vacía no llega aquí: `componer_vista` la
    rehace antes con todas las páginas.
    """
    return cola_mod.encolar(
        request,
        "unir",
        origenes,
        {"receta": receta_mod.a_texto(entradas)},
        sufijo="_unido.pdf",
    )
