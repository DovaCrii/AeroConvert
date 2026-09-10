"""La pantalla de unir PDF.

## Por qué no pasa por el motor de conversión

El resto de AeroConvert coge **un** archivo, elige un destino y lo encola: la conversión
tarda, así que hay un despachador, una barra de progreso y un recibo. Componer un PDF no se
parece en nada. Se cogen varios archivos, se toca la lista muchas veces —subir, bajar,
quitar, girar— y el resultado se escribe en menos de un segundo. Meter eso en la cola sería
pedirle a alguien que espere a un proceso en segundo plano para reordenar tres hojas.

Así que es una pantalla directa: cada acción es una petición que devuelve la lista otra vez.

## Sin estado en el servidor

La receta viaja en un campo oculto del propio formulario, así que no hay sesión que caducar
ni fila que limpiar, y dos personas pueden componer a la vez sin pisarse. La pantalla es una
función de lo que hay escrito en ella. Ver `receta.py`.

## Lo que sí se conserva del resto de la aplicación

Las tres promesas: **la ruta se comprueba contra las raíces permitidas** igual que en la
inspección, **el original no se toca** —pypdf lee y escribe en un documento nuevo— y la
salida se escribe primero en un parcial y solo se pone en su sitio si sale bien.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotModified
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.core import modo as modo_mod
from apps.engines.base import ruta_parcial
from apps.formats import pdf as lectura_pdf

from . import dividir as dividir_mod
from . import miniaturas
from . import receta as receta_mod
from .composicion import GIROS, ComposicionInvalida, componer

#: Cuántos PDF se admiten de una vez. Más que esto no es una entrega: es un lote, y para
#: un lote hace falta otra pantalla.
MAXIMO_ARCHIVOS = 20


@dataclass(frozen=True)
class Fila:
    """Una página, lista para pintar."""

    indice: int
    nombre_archivo: str
    #: La ruta completa, que es lo que pide la miniatura. No se enseña: la fila muestra
    #: solo el nombre, porque una ruta de OneDrive ocupa media pantalla.
    ruta: str
    numero: int
    giro: int
    etiqueta: str
    #: `True` si el giro pedido la deja distinta de como venía. Se marca para que se vea
    #: de un vistazo qué se ha tocado.
    girada: bool


def _rutas_pedidas(texto: str) -> list[Path]:
    """Una ruta por línea, comprobadas contra las raíces permitidas.

    Se admiten comillas alrededor porque «Copiar como ruta» del Explorador las pone, y
    quitarlas a mano cada vez es exactamente el tipo de fricción que sobra.
    """
    rutas: list[Path] = []
    for linea in (texto or "").splitlines():
        limpia = linea.strip().strip('"')
        if not limpia:
            continue
        rutas.append(modo_mod.comprobar_ruta(limpia))
        if len(rutas) >= MAXIMO_ARCHIVOS:
            break
    return rutas


def _filas(entradas, archivos: list[Path], cabeceras: dict[Path, object]) -> list[Fila]:
    filas = []
    for indice, entrada in enumerate(entradas):
        archivo = archivos[entrada.archivo]
        cabecera = cabeceras.get(archivo)
        etiqueta = ""
        if cabecera is not None and entrada.pagina <= len(cabecera.paginas):
            pagina = cabecera.paginas[entrada.pagina - 1]
            # La etiqueta enseña la orientación **con el giro pedido ya aplicado**: es lo
            # que va a salir en el papel, que es lo único que le importa a quien mira.
            gira_el_cuarto = entrada.giro in (90, 270)
            apaisada = pagina.apaisada if not gira_el_cuarto else not pagina.apaisada
            etiqueta = f"{pagina.formato} {'apaisada' if apaisada else 'vertical'}"
        filas.append(
            Fila(
                indice=indice,
                nombre_archivo=archivo.name,
                ruta=str(archivo),
                numero=entrada.pagina,
                giro=entrada.giro,
                etiqueta=etiqueta,
                girada=bool(entrada.giro),
            )
        )
    return filas


def _contexto(rutas: list[Path], entradas, extra: dict | None = None) -> dict:
    cabeceras: dict[Path, object] = {}
    for ruta in rutas:
        try:
            cabeceras[ruta] = lectura_pdf.leer_cabecera(ruta)
        except lectura_pdf.NoEsPdf:
            cabeceras[ruta] = None

    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Junta varios PDF en uno",
        "proposito": (
            "Elige qué páginas entran, en qué orden, y gira las láminas que lo necesiten."
        ),
        "archivos": [str(r) for r in rutas],
        "nombres": [r.name for r in rutas],
        "receta": receta_mod.a_texto(entradas),
        "filas": _filas(entradas, rutas, cabeceras),
        "rutas_texto": "\n".join(str(r) for r in rutas),
    }
    contexto.update(extra or {})
    return contexto


#: Las herramientas, para el indice y para el titulo de cada pantalla. Una lista y no seis
#: entradas en la barra: la barra es de secciones, y esto es una seccion con varias cosas
#: dentro. Ademas asi entra la siguiente sin rediscutir donde ponerla.
HERRAMIENTAS = (
    {
        "id": "unir",
        "url": "documents:unir",
        "nombre": "Unir PDF",
        "que_hace": (
            "Junta varios en uno. Eliges qué páginas entran, en qué orden, y giras las "
            "láminas que lo necesiten."
        ),
    },
    {
        "id": "dividir",
        "url": "documents:dividir",
        "nombre": "Dividir PDF",
        "que_hace": "Saca una parte, o parte uno grande en hojas sueltas.",
    },
    {
        "id": "imagenes",
        "url": "documents:imagenes",
        "nombre": "Imágenes a PDF",
        "que_hace": "Fotos o escaneos en un solo documento, en A4 o al tamaño del original.",
    },
)


@login_required
def inicio(request):
    """El índice de herramientas de PDF."""
    return render(
        request,
        "documents/inicio.html",
        {
            "seccion": "pdf",
            "etiqueta_seccion": "PDF",
            "titulo_pagina": "Herramientas de PDF",
            "proposito": (
                "Todo pasa en tu equipo: los archivos no se copian, no se suben, y el "
                "original nunca se toca."
            ),
            "herramientas": HERRAMIENTAS,
        },
    )


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
    """Todas las acciones de la pantalla. Cuál se pidió lo dice `accion`."""
    try:
        rutas = _rutas_pedidas(request.POST.get("archivos_texto", ""))
    except modo_mod.RutaNoPermitida as fallo:
        messages.error(request, str(fallo))
        return redirect("documents:unir")

    if not rutas:
        messages.error(request, "No indicaste ningún archivo.")
        return redirect("documents:unir")

    entradas = receta_mod.desde_texto(request.POST.get("receta", ""), len(rutas))
    accion, _, argumento = (request.POST.get("accion") or "").partition(":")

    if accion == "analizar" or not entradas:
        try:
            entradas = _receta_inicial(rutas)
        except ComposicionInvalida as fallo:
            messages.error(request, str(fallo))
            return render(request, "documents/unir.html", _contexto(rutas, []))
    elif accion in ("subir", "bajar", "quitar", "girar"):
        indice = int(argumento) if argumento.isdigit() else -1
        entradas = getattr(receta_mod, accion)(entradas, indice)
    elif accion == "generar":
        return _generar(request, rutas, entradas)

    return render(request, "documents/unir.html", _contexto(rutas, entradas))


@login_required
def miniatura(request):
    """El PNG de una página. La pantalla pone una por fila.

    **La caché la hace el navegador, no nosotros.** La respuesta lleva un `ETag` que
    depende del archivo —su fecha y su tamaño— más la página, el giro y el ancho, así que
    al pulsar «bajar» las cincuenta y seis miniaturas vuelven con un 304 y no se dibuja
    ninguna otra vez. Guardarlas en disco traería una carpeta que crece, que hay que
    barrer, y que se queda obsoleta cuando el archivo cambia.

    La ruta pasa por la misma puerta que la inspección: en taller, una ruta es lectura del
    disco entero, y una vista que sirve imágenes no es excepción.
    """
    try:
        ruta = modo_mod.comprobar_ruta((request.GET.get("ruta") or "").strip())
    except modo_mod.RutaNoPermitida:
        return HttpResponseBadRequest("Ruta no permitida.")

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


def _receta_inicial(rutas: list[Path]):
    """Todas las páginas de todos los archivos, en el orden en que se pegaron."""
    entradas = []
    for indice, ruta in enumerate(rutas):
        try:
            cabecera = lectura_pdf.leer_cabecera(ruta)
        except lectura_pdf.NoEsPdf as fallo:
            raise ComposicionInvalida(f"{ruta.name}: {fallo}") from fallo
        if cabecera.cifrado:
            raise ComposicionInvalida(
                f"{ruta.name} pide contraseña. Ábrelo con ella y guárdalo sin ella."
            )
        entradas.extend(receta_mod.Entrada(indice, pagina.numero) for pagina in cabecera.paginas)
    return entradas


def _generar(request, rutas: list[Path], entradas):
    destino = _ruta_de_salida(rutas[0])
    parcial = ruta_parcial(destino)

    try:
        resultado = componer(receta_mod.a_paginas(entradas, rutas), parcial)
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/unir.html", _contexto(rutas, entradas))

    # Igual que en el runner: se escribe en el parcial y solo se pone en su sitio cuando
    # ya salió bien. Un fallo a mitad no deja un PDF a medias con nombre de entregable.
    os.replace(parcial, destino)

    messages.success(
        request,
        f"{resultado.paginas_escritas} páginas en {destino.name}.",
    )
    return render(
        request,
        "documents/unir.html",
        _contexto(rutas, entradas, {"generado": destino, "resultado": resultado}),
    )


@login_required
def dividir_vista(request):
    """Partir un PDF: una parte, o cada hoja por su lado.

    Dos pasos como en unir —mirar y después hacer— porque partir sin ver cuántas páginas
    hay obliga a abrir el documento en otro sitio para saber qué rangos escribir.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Dividir un PDF",
        "proposito": "Saca una parte, o parte uno grande en hojas sueltas.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
        "modo": "rangos",
        "rangos": "",
    }

    if request.method != "POST":
        return render(request, "documents/dividir.html", contexto)

    try:
        ruta = modo_mod.comprobar_ruta((request.POST.get("ruta") or "").strip().strip('"'))
    except modo_mod.RutaNoPermitida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/dividir.html", contexto)

    contexto["ruta_texto"] = str(ruta)
    contexto["modo"] = request.POST.get("modo") or "rangos"
    contexto["rangos"] = (request.POST.get("rangos") or "").strip()

    try:
        cabecera = lectura_pdf.leer_cabecera(ruta)
    except lectura_pdf.NoEsPdf as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/dividir.html", contexto)

    if cabecera.cifrado:
        messages.error(request, f"{ruta.name} pide contraseña, así que no se puede partir.")
        return render(request, "documents/dividir.html", contexto)

    contexto["cabecera"] = cabecera
    contexto["ruta"] = str(ruta)

    if request.POST.get("accion") != "partir":
        return render(request, "documents/dividir.html", contexto)

    try:
        trozos = (
            dividir_mod.una_por_pagina(cabecera.cuantas)
            if contexto["modo"] == "hojas"
            else dividir_mod.analizar_rangos(contexto["rangos"], cabecera.cuantas)
        )
        escritos = dividir_mod.partir(ruta, trozos)
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/dividir.html", contexto)

    messages.success(request, f"{len(escritos)} archivo(s) escritos junto al original.")
    contexto["escritos"] = escritos
    return render(request, "documents/dividir.html", contexto)


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

    contexto["rutas_texto"] = request.POST.get("archivos_texto", "")
    contexto["tamano"] = request.POST.get("tamano") or "a4"

    try:
        rutas = _rutas_pedidas(contexto["rutas_texto"])
    except modo_mod.RutaNoPermitida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/imagenes.html", contexto)

    if not rutas:
        messages.error(request, "No indicaste ninguna imagen.")
        return render(request, "documents/imagenes.html", contexto)

    destino = rutas[0].with_name(f"{rutas[0].stem}_imagenes.pdf")
    parcial = ruta_parcial(destino)

    try:
        cuantas = dividir_mod.desde_imagenes(rutas, parcial, tamano=contexto["tamano"])
    except ComposicionInvalida as fallo:
        parcial.unlink(missing_ok=True)
        messages.error(request, str(fallo))
        return render(request, "documents/imagenes.html", contexto)

    os.replace(parcial, destino)
    messages.success(request, f"{cuantas} imagen(es) en {destino.name}.")
    contexto["generado"] = destino
    return render(request, "documents/imagenes.html", contexto)


def _ruta_de_salida(primero: Path) -> Path:
    """Junto al primer archivo, con un sufijo que dice qué es.

    El mismo criterio que el resto de la aplicación: quien compone una entrega la quiere
    al lado de sus archivos, no perdida en un directorio del programa.
    """
    return primero.with_name(f"{primero.stem}_unido.pdf")
