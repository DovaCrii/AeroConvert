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
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotModified
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.core import entrada as entrada_mod
from apps.core import modo as modo_mod
from apps.core import subidas as subidas_mod
from apps.engines.base import ruta_parcial
from apps.formats import pdf as lectura_pdf

from . import a_imagenes as a_imagenes_mod
from . import dividir as dividir_mod
from . import marcas as marcas_mod
from . import miniaturas
from . import office as office_mod
from . import receta as receta_mod
from . import seguridad as seguridad_mod
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


def _origenes_pedidos(texto: str, usuario) -> list:
    """Un origen por línea: una ruta del disco **o** un archivo subido.

    Los dos conviven en el mismo campo de texto, y cuál es cuál lo dice el prefijo — nunca se
    adivina. Ver `apps/core/entrada.py`.

    Se admiten comillas alrededor porque «Copiar como ruta» del Explorador las pone, y
    quitarlas a mano cada vez es exactamente el tipo de fricción que sobra.
    """
    return entrada_mod.resolver_varios(texto, usuario=usuario, maximo=MAXIMO_ARCHIVOS)


def _filas(entradas, origenes: list, cabeceras: dict) -> list[Fila]:
    filas = []
    for indice, entrada in enumerate(entradas):
        origen = origenes[entrada.archivo]
        cabecera = cabeceras.get(origen.ruta)
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
                nombre_archivo=origen.nombre,
                # **El identificador, no la ruta.** Es lo que la plantilla mete en la URL de
                # la miniatura, y devolver la ruta real de un archivo subido dejaría que el
                # navegador la usara como si fuera una ruta del disco.
                ruta=origen.token,
                numero=entrada.pagina,
                giro=entrada.giro,
                etiqueta=etiqueta,
                girada=bool(entrada.giro),
            )
        )
    return filas


def _contexto(origenes: list, entradas, extra: dict | None = None) -> dict:
    cabeceras: dict = {}
    for origen in origenes:
        try:
            cabeceras[origen.ruta] = lectura_pdf.leer_cabecera(origen.ruta)
        except lectura_pdf.NoEsPdf:
            cabeceras[origen.ruta] = None

    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Junta varios PDF en uno",
        "proposito": (
            "Elige qué páginas entran, en qué orden, y gira las láminas que lo necesiten."
        ),
        "nombres": [o.nombre for o in origenes],
        "receta": receta_mod.a_texto(entradas),
        "filas": _filas(entradas, origenes, cabeceras),
        # **Los identificadores, no las rutas.** Es la única línea de esta pantalla donde
        # equivocarse sería una fuga: si aquí volviera la ruta de un archivo subido, el POST
        # siguiente la trataría como una ruta del disco del servidor.
        "rutas_texto": "\n".join(o.token for o in origenes),
    }
    contexto.update(extra or {})
    return contexto


#: Las herramientas, para el indice y para el titulo de cada pantalla. Una lista y no seis
#: entradas en la barra: la barra es de secciones, y esto es una seccion con varias cosas
#: dentro. Ademas asi entra la siguiente sin rediscutir donde ponerla.
#:
#: El `icono` es el identificador dentro de `static/img/icons.svg`. Va aqui y no en la
#: plantilla porque la plantilla recorre la lista: con un `if` por herramienta, anadir la
#: decima obligaria a tocar dos sitios y el segundo se olvida.
HERRAMIENTAS = (
    {
        "id": "unir",
        "url": "documents:unir",
        "icono": "icon-pdf-unir",
        "familia": "componer",
        "nombre": "Unir PDF",
        "que_hace": (
            "Junta varios en uno. Eliges qué páginas entran, en qué orden, y giras las "
            "láminas que lo necesiten."
        ),
    },
    {
        "id": "dividir",
        "icono": "icon-pdf-dividir",
        "familia": "componer",
        "url": "documents:dividir",
        "nombre": "Dividir PDF",
        "que_hace": "Saca una parte, o parte uno grande en hojas sueltas.",
    },
    {
        "id": "imagenes",
        "icono": "icon-pdf-a-pdf",
        "familia": "transformar",
        "url": "documents:imagenes",
        "nombre": "Imágenes a PDF",
        "que_hace": "Fotos o escaneos en un solo documento, en A4 o al tamaño del original.",
    },
    {
        "id": "a_imagenes",
        "icono": "icon-pdf-a-imagen",
        "familia": "transformar",
        "url": "documents:a_imagenes",
        "nombre": "PDF a imágenes",
        "que_hace": "Una lámina como JPG o PNG, para meterla en un informe o en una diapositiva.",
    },
    {
        "id": "numerar",
        "icono": "icon-pdf-numerar",
        "familia": "marcar",
        "url": "documents:numerar",
        "nombre": "Numerar páginas",
        "que_hace": ("Pone «3 / 56» en cada hoja. Sin numerar la portada, si no quieres."),
    },
    {
        "id": "marca",
        "icono": "icon-pdf-marca",
        "familia": "marcar",
        "url": "documents:marca",
        "nombre": "Marca de agua",
        "que_hace": "Estampa «BORRADOR» o «CONFIDENCIAL» cruzando cada página.",
    },
    {
        "id": "proteger",
        "icono": "icon-pdf-proteger",
        "familia": "proteger",
        "url": "documents:proteger",
        "nombre": "Proteger PDF",
        "que_hace": "Le pone contraseña, con AES-256. O se la quita, si la sabes.",
    },
    {
        "id": "office",
        "icono": "icon-pdf-office",
        "familia": "transformar",
        "url": "documents:office",
        "nombre": "Word, Excel o PowerPoint a PDF",
        "que_hace": "Con el Office de tu equipo, así que sale idéntico al original.",
        # La unica que depende de algo de fuera. Cuando no esta, la tarjeta **sigue
        # saliendo**, apagada y con el motivo: ocultarla haria parecer que nunca existio.
        "exige_office": True,
    },
    {
        "id": "a_word",
        "icono": "icon-pdf-a-word",
        "familia": "transformar",
        "url": "documents:a_word",
        "nombre": "PDF a Word",
        "que_hace": "El camino de vuelta, para poder editarlo. Con lo que eso significa.",
        "exige_office": True,
    },
)


@login_required
def inicio(request):
    """El índice de herramientas de PDF.

    Una herramienta que hoy no se puede usar **no desaparece**: sale apagada y diciendo por
    qué. Es la misma regla que con ECW en la matriz de motores.

    ## Pero apagada **abajo y en su propio bloque**, no intercalada

    Las dos que dependen de Office comparten motivo, y ese motivo es un párrafo de cuatro
    líneas. Mezcladas en la rejilla pasaban tres cosas a la vez: el párrafo salía repetido
    palabra por palabra, su fila se estiraba al triple que las demás, y la herramienta que
    venía detrás caía sola a una tercera fila con media pantalla en blanco alrededor.

    Separadas, el motivo se escribe **una vez** —es el mismo— y las siete que funcionan
    forman filas parejas.
    """
    office = office_mod.sondar()
    disponibles = []
    apagadas = []
    for herramienta in HERRAMIENTAS:
        fila = dict(herramienta)
        if herramienta.get("exige_office") and not office:
            apagadas.append(fila)
        else:
            disponibles.append(fila)

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
            "disponibles": disponibles,
            "apagadas": apagadas,
            # El motivo va aparte porque es **uno solo** para las dos.
            "motivo_office": office.motivo,
            "sugerencia_office": office.sugerencia,
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
    destino = _ruta_de_salida(origenes[0])
    parcial = ruta_parcial(destino)

    try:
        resultado = componer(receta_mod.a_paginas(entradas, [o.ruta for o in origenes]), parcial)
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/unir.html", _contexto(origenes, entradas))

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
        _contexto(
            origenes,
            entradas,
            {
                "generado": destino,
                "resultado": resultado,
                "descarga": subidas_mod.anotar_resultado(
                    destino, usuario=request.user, herramienta="unir"
                ),
                # Si el origen era una subida, la ruta que se enseña es la de la VM y no
                # sirve para pegarla en ningun sitio: lo unico util es el boton.
                "solo_descarga": origenes[0].es_subida,
            },
        ),
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

    destino = _ruta_de_salida_de(origenes[0], "_imagenes.pdf")
    parcial = ruta_parcial(destino)

    try:
        cuantas = dividir_mod.desde_imagenes(
            [o.ruta for o in origenes], parcial, tamano=contexto["tamano"]
        )
    except ComposicionInvalida as fallo:
        parcial.unlink(missing_ok=True)
        messages.error(request, str(fallo))
        return render(request, "documents/imagenes.html", contexto)

    os.replace(parcial, destino)
    messages.success(request, f"{cuantas} imagen(es) en {destino.name}.")
    contexto["generado"] = destino
    contexto["descarga"] = subidas_mod.anotar_resultado(
        destino, usuario=request.user, herramienta="imagenes"
    )
    contexto["solo_descarga"] = origenes[0].es_subida
    return render(request, "documents/imagenes.html", contexto)


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

    cabecera, ruta, error = _mirar_pdf(request.POST.get("ruta"))
    if error:
        messages.error(request, error)
        return render(request, "documents/a_imagenes.html", contexto)

    contexto["ruta_texto"] = str(ruta)
    contexto["ruta"] = str(ruta)
    contexto["cabecera"] = cabecera

    if request.POST.get("accion") != "convertir":
        return render(request, "documents/a_imagenes.html", contexto)

    try:
        trozos = (
            dividir_mod.analizar_rangos(contexto["rangos"], cabecera.cuantas)
            if contexto["rangos"]
            else dividir_mod.una_por_pagina(cabecera.cuantas)
        )
        escritas = a_imagenes_mod.paginas_a_imagenes(
            ruta,
            trozos,
            formato=contexto["formato"],
            ppp=contexto["ppp_elegido"],
        )
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/a_imagenes.html", contexto)

    messages.success(request, f"{len(escritas)} imagen(es) junto al original.")
    contexto["escritas"] = escritas
    return render(request, "documents/a_imagenes.html", contexto)


@login_required
def proteger_vista(request):
    """Poner o quitar la contraseña.

    **Aquí no hay paso de «mirar» con miniaturas**, a propósito: si el archivo ya está
    cifrado no se puede dibujar nada de él sin la clave, y una pantalla que a veces enseña
    las hojas y a veces no confunde más de lo que ayuda. Lo que sí se dice es en cuál de los
    dos casos está el archivo, que es lo que decide qué botón pulsar.

    La contraseña **no vuelve nunca al formulario**: el campo sale vacío en cada respuesta,
    también cuando hubo un error, para que no se quede escrita en una pantalla que alguien
    deja abierta. Ver el docstring de `seguridad.py`.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Proteger un PDF",
        "proposito": "Ponle contraseña antes de mandarlo, o quítasela para poder componerlo.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
        "minimo": seguridad_mod.MINIMO,
        "algoritmo": seguridad_mod.ALGORITMO,
    }

    if request.method != "POST":
        return render(request, "documents/proteger.html", contexto)

    contexto["ruta_texto"] = (request.POST.get("ruta") or "").strip().strip('"')
    try:
        ruta = modo_mod.comprobar_ruta(contexto["ruta_texto"])
    except modo_mod.RutaNoPermitida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/proteger.html", contexto)

    contexto["ruta_texto"] = str(ruta)
    contexto["ruta"] = str(ruta)

    try:
        cabecera = lectura_pdf.leer_cabecera(ruta)
    except lectura_pdf.NoEsPdf as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/proteger.html", contexto)

    contexto["cifrado"] = cabecera.cifrado
    contexto["cabecera"] = cabecera

    accion = request.POST.get("accion")
    if accion not in ("proteger", "quitar"):
        return render(request, "documents/proteger.html", contexto)

    sufijo = "_protegido" if accion == "proteger" else "_sin_clave"
    destino = ruta.with_name(f"{ruta.stem}{sufijo}.pdf")
    parcial = ruta_parcial(destino)
    contrasena = request.POST.get("contrasena") or ""

    try:
        if accion == "proteger":
            paginas = seguridad_mod.proteger(ruta, parcial, contrasena)
        else:
            paginas = seguridad_mod.quitar_contrasena(ruta, parcial, contrasena)
    except ComposicionInvalida as fallo:
        parcial.unlink(missing_ok=True)
        messages.error(request, str(fallo))
        return render(request, "documents/proteger.html", contexto)
    finally:
        # Que no quede viva en el marco de la excepcion mas de lo necesario.
        contrasena = ""

    os.replace(parcial, destino)
    messages.success(request, f"{paginas} página(s) en {destino.name}.")
    contexto["generado"] = destino
    contexto["hecho"] = accion
    return render(request, "documents/proteger.html", contexto)


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

    cabecera, ruta, error = _mirar_pdf(request.POST.get("ruta"))
    if error:
        messages.error(request, error)
        return render(request, "documents/numerar.html", contexto)

    contexto["ruta_texto"] = contexto["ruta"] = str(ruta)
    contexto["cabecera"] = cabecera

    if request.POST.get("accion") != "numerar":
        return render(request, "documents/numerar.html", contexto)

    destino = ruta.with_name(f"{ruta.stem}_numerado.pdf")
    parcial = ruta_parcial(destino)
    try:
        resultado = marcas_mod.numerar(
            ruta,
            parcial,
            posicion=contexto["posicion"],
            formato=contexto["formato"],
            desde=contexto["desde"],
            empezar_en=contexto["empezar_en"],
        )
    except ComposicionInvalida as fallo:
        parcial.unlink(missing_ok=True)
        messages.error(request, str(fallo))
        return render(request, "documents/numerar.html", contexto)

    os.replace(parcial, destino)
    messages.success(request, f"{resultado.marcadas} página(s) numeradas en {destino.name}.")
    contexto["generado"] = destino
    contexto["resultado"] = resultado
    return render(request, "documents/numerar.html", contexto)


@login_required
def marca_vista(request):
    """Estampar un texto cruzando cada página.

    Un plano que se emite para revisión tiene que ir marcado: uno sin marca que circula por
    correo acaba en obra como si estuviera aprobado.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Marca de agua",
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

    cabecera, ruta, error = _mirar_pdf(request.POST.get("ruta"))
    if error:
        messages.error(request, error)
        return render(request, "documents/marca.html", contexto)

    contexto["ruta_texto"] = contexto["ruta"] = str(ruta)
    contexto["cabecera"] = cabecera

    if request.POST.get("accion") != "marcar":
        return render(request, "documents/marca.html", contexto)

    destino = ruta.with_name(f"{ruta.stem}_marcado.pdf")
    parcial = ruta_parcial(destino)
    try:
        resultado = marcas_mod.marca_de_agua(
            ruta,
            parcial,
            contexto["texto"],
            opacidad=contexto["opacidad"],
            diagonal=contexto["diagonal"],
        )
    except ComposicionInvalida as fallo:
        parcial.unlink(missing_ok=True)
        messages.error(request, str(fallo))
        return render(request, "documents/marca.html", contexto)

    os.replace(parcial, destino)
    messages.success(request, f"{resultado.marcadas} página(s) marcadas en {destino.name}.")
    contexto["generado"] = destino
    return render(request, "documents/marca.html", contexto)


@login_required
def office_vista(request):
    """Word, Excel o PowerPoint a PDF, con el Office instalado.

    De un solo paso, a diferencia de las demás: no hay nada que previsualizar de un `.docx`
    sin abrirlo, y abrirlo ya es la conversión.
    """
    office = office_mod.sondar()
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Word, Excel o PowerPoint a PDF",
        "proposito": (
            "Lo convierte el Office de tu equipo, así que el PDF sale idéntico al original."
        ),
        "office": office,
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
        "ajustar_ancho": True,
    }

    if request.method != "POST" or not office:
        return render(request, "documents/office.html", contexto)

    contexto["ruta_texto"] = (request.POST.get("ruta") or "").strip().strip('"')
    contexto["ajustar_ancho"] = request.POST.get("ajustar_ancho") == "si"

    try:
        ruta = modo_mod.comprobar_ruta(contexto["ruta_texto"])
    except modo_mod.RutaNoPermitida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/office.html", contexto)

    contexto["ruta_texto"] = str(ruta)
    destino = ruta.with_suffix(".pdf")
    parcial = ruta_parcial(destino)

    try:
        office_mod.convertir(ruta, parcial, ajustar_ancho=contexto["ajustar_ancho"])
    except ComposicionInvalida as fallo:
        parcial.unlink(missing_ok=True)
        messages.error(request, str(fallo))
        return render(request, "documents/office.html", contexto)

    os.replace(parcial, destino)
    try:
        cabecera = lectura_pdf.leer_cabecera(destino)
        contexto["cabecera"] = cabecera
        messages.success(request, f"{cabecera.resumen} en {destino.name}.")
    except lectura_pdf.NoEsPdf:  # pragma: no cover -- Office acaba de escribirlo
        messages.success(request, f"Hecho: {destino.name}.")

    contexto["generado"] = destino
    return render(request, "documents/office.html", contexto)


@login_required
def a_word_vista(request):
    """PDF a Word, y **con el aviso delante**.

    De dos pasos a propósito, porque lo que hay que decir antes de convertir no se puede
    decir sin mirar el archivo: un PDF escaneado no tiene texto dentro, así que lo que vuelve
    son las mismas fotos pegadas en un documento de Word. Y eso Word lo hace sin quejarse,
    devolviendo medio mega y un código de salida cero.
    """
    office = office_mod.sondar()
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "PDF a Word",
        "proposito": "Para poder editarlo. Mira antes lo que vas a recibir de verdad.",
        "office": office,
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST" or not office.tiene("word"):
        return render(request, "documents/a_word.html", contexto)

    contexto["ruta_texto"] = (request.POST.get("ruta") or "").strip().strip('"')
    try:
        ruta = modo_mod.comprobar_ruta(contexto["ruta_texto"])
        que_trae = office_mod.mirar_pdf(ruta)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/a_word.html", contexto)

    contexto["ruta_texto"] = contexto["ruta"] = str(ruta)
    contexto["que_trae"] = que_trae

    if request.POST.get("accion") != "convertir":
        return render(request, "documents/a_word.html", contexto)

    destino = ruta.with_suffix(".docx")
    parcial = destino.with_name(f"{destino.stem}.parcial.docx")
    try:
        office_mod.a_word(ruta, parcial)
    except ComposicionInvalida as fallo:
        parcial.unlink(missing_ok=True)
        messages.error(request, str(fallo))
        return render(request, "documents/a_word.html", contexto)

    os.replace(parcial, destino)
    messages.success(request, f"Hecho: {destino.name}.")
    contexto["generado"] = destino
    return render(request, "documents/a_word.html", contexto)


def _entero(crudo, por_omision: int) -> int:
    """Un entero del formulario, sin reventar. Un campo numérico es evadible desde fuera."""
    try:
        valor = int(crudo)
    except (TypeError, ValueError):
        return por_omision
    return valor if valor >= 1 else por_omision


def _mirar_pdf(crudo):
    """Ruta comprobada y cabecera leída, o el motivo por el que no.

    Devuelve `(cabecera, ruta, error)`. Es el trozo que comparten dividir y PDF a imágenes:
    comprobar la raíz permitida, leer la cabecera, y negarse si pide contraseña —porque sin
    la clave no hay páginas que sacar—.
    """
    try:
        ruta = modo_mod.comprobar_ruta((crudo or "").strip().strip('"'))
    except modo_mod.RutaNoPermitida as fallo:
        return None, None, str(fallo)

    try:
        cabecera = lectura_pdf.leer_cabecera(ruta)
    except lectura_pdf.NoEsPdf as fallo:
        return None, ruta, str(fallo)

    if cabecera.cifrado:
        return (
            None,
            ruta,
            f"{ruta.name} pide contraseña. Quítasela primero en «Proteger PDF».",
        )
    return cabecera, ruta, None


def _ruta_de_salida_de(primero, sufijo: str) -> Path:
    """Dónde se escribe el resultado. **La salida va donde estaba la entrada.**

    Si el primer archivo venía de una carpeta —la compartida o el disco de uno—, el
    resultado va **al lado**: quien compone una entrega la quiere junto a sus archivos, no
    perdida en un directorio del programa, y en la unidad de red ya la tiene montada.

    Si venía de una subida, no hay «al lado» que valga: se escribe en la carpeta de trabajo y
    se entrega por la vista de descarga, que comprueba el dueño.
    """
    nombre = f"{Path(primero.nombre).stem}{sufijo}"
    if primero.es_subida:
        from apps.jobs import retencion

        return retencion.carpeta_de_trabajo() / nombre
    return primero.ruta.with_name(nombre)


def _ruta_de_salida(primero) -> Path:
    """La de «unir»."""
    return _ruta_de_salida_de(primero, "_unido.pdf")
