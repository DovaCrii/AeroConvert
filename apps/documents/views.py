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
from . import a_markdown as a_markdown_mod
from . import catalogos as catalogos_mod
from . import comprimir as comprimir_mod
from . import desde_markdown as desde_markdown_mod
from . import dividir as dividir_mod
from . import marcas as marcas_mod
from . import miniaturas
from . import ocr as ocr_mod
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


def _origen_del_formulario(request, campo: str = "ruta", archivo: str = "archivo"):
    """De dónde parte la pantalla: el archivo subido si lo hay, y si no lo que venga escrito.

    ## Por qué existe

    Cinco pantallas llamaban a `modo.comprobar_ruta()` por su cuenta, saltándose la puerta
    única de `apps/core/entrada.py`. Consecuencia: **en esas cinco la subida nunca funcionó**
    — el identificador `subida:<uuid>` llegaba a una función que solo entiende rutas del
    disco y lo rechazaba por no estar dentro de las raíces permitidas.

    `EntradaNoPermitida` hereda de `RutaNoPermitida` justamente para esto: los `except` que
    ya había siguen capturándola sin tocar una línea.

    ## Y el tope de tamaño

    `guardar()` levanta `ValidationError` cuando el archivo pasa del tope, **antes** de
    escribir nada. Se traduce aquí para que la pantalla lo enseñe como cualquier otro motivo
    en vez de reventar con un 500.
    """
    subido = request.FILES.get(archivo)
    if subido is None:
        return entrada_mod.resolver(request.POST.get(campo) or "", usuario=request.user)

    try:
        subida = subidas_mod.guardar(subido, usuario=request.user)
    except ValidationError as fallo:
        raise entrada_mod.EntradaNoPermitida(
            "; ".join(fallo.messages), "ruta-no-permitida"
        ) from fallo
    return entrada_mod.resolver(f"{entrada_mod.PREFIJO}{subida.pk}", usuario=request.user)


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
        "sale": "un PDF",
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
        "sale": "uno o varios PDF",
        "familia": "componer",
        "url": "documents:dividir",
        "nombre": "Dividir PDF",
        "que_hace": "Saca una parte, o parte uno grande en hojas sueltas.",
    },
    {
        "id": "imagenes",
        "icono": "icon-pdf-a-pdf",
        "sale": "un PDF",
        "familia": "transformar",
        "url": "documents:imagenes",
        "nombre": "Imágenes a PDF",
        "que_hace": "Fotos o escaneos en un solo documento, en A4 o al tamaño del original.",
    },
    {
        "id": "a_imagenes",
        "icono": "icon-pdf-a-imagen",
        "sale": "JPG o PNG",
        "familia": "transformar",
        "url": "documents:a_imagenes",
        "nombre": "PDF a imágenes",
        "que_hace": "Una lámina como JPG o PNG, para meterla en un informe o en una diapositiva.",
    },
    {
        "id": "comprimir",
        "icono": "icon-pdf-comprimir",
        "sale": "el mismo PDF, más ligero",
        "familia": "transformar",
        "url": "documents:comprimir",
        "nombre": "Comprimir PDF",
        "que_hace": "Para que un juego de planos entre en un correo. Dice cuánto baja antes.",
    },
    {
        "id": "ocr",
        "icono": "icon-pdf-ocr",
        "sale": "el mismo PDF, con el texto dentro",
        "familia": "transformar",
        "url": "documents:ocr",
        "nombre": "Reconocer el texto de un escaneo",
        "que_hace": "Un PDF escaneado pasa a poder buscarse y copiarse. Se ve igual.",
        # La tercera que depende de algo de fuera, y con el mismo trato que Office y Access:
        # cuando Tesseract no esta, la tarjeta **sigue saliendo**, apagada y con el motivo.
        "exige_tesseract": True,
    },
    {
        "id": "numerar",
        "icono": "icon-pdf-numerar",
        "sale": "el mismo PDF, numerado",
        "familia": "marcar",
        "url": "documents:numerar",
        "nombre": "Numerar páginas",
        "que_hace": ("Pone «3 / 56» en cada hoja. Sin numerar la portada, si no quieres."),
    },
    {
        "id": "marca",
        "icono": "icon-pdf-marca",
        "sale": "el mismo PDF, con la marca",
        "familia": "marcar",
        "url": "documents:marca",
        "nombre": "Marca de agua",
        "que_hace": "Estampa «BORRADOR» o «CONFIDENCIAL» cruzando cada página.",
    },
    {
        "id": "proteger",
        "icono": "icon-pdf-proteger",
        "sale": "el mismo PDF, con contraseña",
        "familia": "proteger",
        "url": "documents:proteger",
        "nombre": "Proteger PDF",
        "que_hace": "Le pone contraseña, con AES-256. O se la quita, si la sabes.",
    },
    {
        "id": "office",
        "icono": "icon-pdf-office",
        "sale": "un PDF",
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
        "sale": "un DOCX",
        "familia": "transformar",
        "url": "documents:a_word",
        "nombre": "PDF a Word",
        "que_hace": "El camino de vuelta, para poder editarlo. Con lo que eso significa.",
        "exige_office": True,
    },
    # --- Texto y tablas ---------------------------------------------------
    #
    # **Seis entradas y una sola pantalla.** La pantalla mira la extensión y hace lo que toca;
    # las seis entradas existen porque quien busca escribe «excel a markdown» o «epub», no
    # «a markdown». Es el mismo patrón que los seis destinos geoespaciales, que también van a
    # una sola pantalla con la elección en la consulta.
    {
        "id": "md_excel",
        "categoria": "texto",
        "icono": "icon-texto-tabla",
        "sale": "un .md con una tabla por hoja",
        "familia": "texto",
        "url": "documents:a_markdown",
        "consulta": {"de": "xlsx"},
        "nombre": "Excel a Markdown",
        "que_hace": "Cada hoja, una tabla que se pega en un correo o en una ficha.",
    },
    {
        "id": "md_csv",
        "categoria": "texto",
        "icono": "icon-texto-tabla",
        "sale": "un .md con la tabla",
        "familia": "texto",
        "url": "documents:a_markdown",
        "consulta": {"de": "csv"},
        "nombre": "CSV a Markdown",
        "que_hace": "Detecta si separa por punto y coma o por coma, que aquí cambia.",
    },
    {
        "id": "md_word",
        "categoria": "texto",
        "icono": "icon-texto-parrafo",
        "sale": "un .md",
        "familia": "texto",
        "url": "documents:a_markdown",
        "consulta": {"de": "docx"},
        "nombre": "Word a Markdown",
        "que_hace": "Títulos, listas, tablas y negritas. Lo que no sobrevive se avisa.",
    },
    {
        "id": "md_pdf",
        "categoria": "texto",
        "icono": "icon-texto-parrafo",
        "sale": "un .md",
        "familia": "texto",
        "url": "documents:a_markdown",
        "consulta": {"de": "pdf"},
        "nombre": "PDF a Markdown",
        "que_hace": "El texto que el PDF ya tiene. Si es un escaneo, se dice.",
    },
    {
        "id": "md_epub",
        "categoria": "texto",
        "icono": "icon-texto-libro",
        "sale": "un .md con los capítulos en orden",
        "familia": "texto",
        "url": "documents:a_markdown",
        "consulta": {"de": "epub"},
        "nombre": "EPUB a Markdown",
        "que_hace": "En el orden en que se lee, no en el que vienen dentro del archivo.",
    },
    {
        "id": "md_html",
        "categoria": "texto",
        "icono": "icon-texto-parrafo",
        "sale": "un .md",
        "familia": "texto",
        "url": "documents:a_markdown",
        "consulta": {"de": "html"},
        "nombre": "Página web a Markdown",
        "que_hace": "Una página guardada, sin el armazón ni los menús.",
    },
    {
        "id": "md_a_pdf",
        "categoria": "texto",
        "icono": "icon-texto-imprimir",
        "sale": "un PDF",
        "familia": "texto",
        "url": "documents:de_markdown",
        "nombre": "Markdown a PDF",
        "que_hace": "El camino de vuelta, para entregar lo que se redactó en Markdown.",
    },
    # --- Catálogos de tubería ---------------------------------------------
    #
    # Son bases de Access de AutoCAD Plant 3D. Van en este grupo porque es lo mismo que hacen
    # las de arriba: sacar el contenido de un archivo para poder trabajarlo en otro sitio.
    {
        "id": "catalogo_excel",
        "categoria": "texto",
        "icono": "icon-catalogo",
        "sale": "un Excel con una hoja por tabla",
        "familia": "texto",
        "url": "documents:catalogo_a_excel",
        "nombre": "Catálogo de tubería a Excel",
        "que_hace": "Saca las nueve tablas del catálogo para poder editarlas cómodo.",
        "exige_access": True,
    },
    {
        "id": "excel_catalogo",
        "categoria": "texto",
        "icono": "icon-catalogo-volver",
        "sale": "un catálogo listo para Plant 3D",
        "familia": "texto",
        "url": "documents:excel_a_catalogo",
        "nombre": "Excel a catálogo de tubería",
        "que_hace": "El camino de vuelta. Se parte del catálogo original, que pone el esquema.",
        "exige_access": True,
    },
)


#: Los cuatro grupos, en el orden en que se piensan: primero mover páginas de sitio, luego
#: cambiar de formato, luego estampar encima, y al final cerrar con llave.
#:
#: Cada uno con **la pregunta que lo trae**, no con un sustantivo. «Componer» es la palabra
#: correcta y no le dice nada a quien llega con dos PDF que quiere juntar.
GRUPOS = (
    ("componer", "Juntar o separar", "Cuando el documento está repartido, o sobra la mitad."),
    ("transformar", "Cambiar de formato", "Cuando hace falta en otra cosa: PDF, imagen o Word."),
    ("marcar", "Estampar encima", "Cuando el documento está bien pero le falta algo en cada hoja."),
    ("proteger", "Poner o quitar contraseña", "Cuando no puede abrirlo cualquiera."),
    ("texto", "Sacar el contenido", "Cuando el texto o la tabla tienen que salir del archivo."),
)


def _agrupar(herramientas):
    """Las herramientas por familia, en el orden de `GRUPOS`.

    **Siete tarjetas seguidas se reparten en cuatro y tres y dejan un hueco**, y el hueco se
    lee como si faltara algo. Agrupadas, cada fila tiene el tamaño que le toca y además el
    encabezado contesta antes de que haya que leer los nombres uno a uno.

    Un grupo vacío no se pinta: con Office ausente, «cambiar de formato» pierde dos de sus
    cuatro y sigue teniendo sentido, pero si algún día se queda sin ninguna, un encabezado
    solo sería peor que nada.
    """
    por_familia: dict[str, list] = {}
    for herramienta in herramientas:
        por_familia.setdefault(herramienta.get("familia", ""), []).append(herramienta)

    return [
        {"clave": clave, "titulo": titulo, "cuando": cuando, "herramientas": por_familia[clave]}
        for clave, titulo, cuando in GRUPOS
        if por_familia.get(clave)
    ]


def estado_de_herramientas() -> list[dict]:
    """Las veinte, con si esta máquina puede hacerlas y por qué no.

    El número se queda escrito a propósito aunque envejezca: decía «las once» cuando ya eran
    dieciocho, y ese desfase es la señal de que alguien añadió herramientas sin repasar lo que
    las describe. Un «las que haya» no avisaría de nada.

    Pero *avisar* no es lo mismo que *enterarse*: el desfase estuvo escrito semanas y nadie lo
    vio, porque para verlo había que leer esta línea. Ahora lo comprueba
    `test_cuenta.py`, que mira también el README y el manual del servidor — que es donde la
    cifra vieja hacía daño de verdad.

    Vive aquí y la consume **también la pantalla de compatibilidad**: es la única forma de
    que lo que no se puede aparezca en un solo sitio y siga apareciendo. Antes las apagadas
    se enseñaban en el índice de PDF y en ningún otro lado; ahora salen de aquí.
    """
    office = office_mod.sondar()
    # Los catálogos son bases de Access: el motor es de Microsoft y en Linux no existe. Se
    # sondea igual que Office, y en el servidor salen apagadas con su motivo.
    access = catalogos_mod.sondar()
    # Tesseract es un programa aparte, como GDAL: no entra en las dependencias y no se da por
    # hecho. Donde no este, «reconocer el texto» sale apagada y explicando como ponerlo.
    tesseract = ocr_mod.sondar()

    estado = []
    for herramienta in HERRAMIENTAS:
        fila = dict(herramienta)
        if herramienta.get("exige_office"):
            fila["disponible"] = bool(office)
            fila["motivo"] = office.motivo
            fila["sugerencia"] = office.sugerencia
        elif herramienta.get("exige_access"):
            fila["disponible"] = bool(access)
            fila["motivo"] = access.motivo
            fila["sugerencia"] = access.sugerencia
        elif herramienta.get("exige_tesseract"):
            fila["disponible"] = bool(tesseract)
            fila["motivo"] = tesseract.motivo
            fila["sugerencia"] = tesseract.sugerencia
        else:
            fila["disponible"] = True
        estado.append(fila)
    return estado


@login_required
def inicio(request):
    """El índice de herramientas de PDF.

    ## Lo que no se puede hacer **no sale aquí**

    Y es un cambio de criterio, no un descuido. La regla de la casa es que una capacidad
    ausente se apaga y no se esconde — pero «no se esconde» quiere decir que se puede
    encontrar, no que tenga que estar en todas partes. Repetida en las dos pantallas, la
    explicación de Office ocupaba un párrafo de cuatro líneas en la que se viene a trabajar,
    para contar algo que no cambia nunca en esta máquina.

    Así que se dice **una vez y en su sitio**: `/motores/`, que existe precisamente para
    contestar «qué se puede convertir en este equipo». Esta pantalla enseña lo que se puede
    usar ahora, y lleva un enlace a la otra.
    """
    return _indice(
        request,
        categoria="documentos",
        etiqueta="PDF",
        titulo="Herramientas de PDF",
        proposito=(
            "Todo pasa en tu equipo: los archivos no se copian, no se suben, y el "
            "original nunca se toca."
        ),
    )


@login_required
def texto(request):
    """El índice de «Texto y tablas», aparte del de PDF.

    **Eran la misma pantalla y no debían serlo.** Al entrar en «Documentos y PDF» aparecían
    también las siete de Markdown y las dos de catálogos, y al revés: quien venía a pasar un
    Excel a Markdown tenía que bajar por delante de nueve herramientas de PDF. El desplegable
    ofrece dos columnas distintas y las dos llevaban al mismo sitio, que es prometer una
    separación que no existe.
    """
    return _indice(
        request,
        categoria="texto",
        etiqueta="Texto y tablas",
        titulo="Sacar el contenido de un archivo",
        proposito=(
            "Cuando el texto o la tabla tienen que salir del archivo y entrar en un correo, "
            "en una ficha o en otro programa."
        ),
    )


def _indice(request, *, categoria: str, etiqueta: str, titulo: str, proposito: str):
    """El índice de una categoría. Lo comparten las dos pantallas.

    Las apagadas se cuentan **dentro de su categoría**: decirle a quien mira las de texto que
    hay dos apagadas de Office sería contarle un problema que no es el suyo.
    """
    estado = [h for h in estado_de_herramientas() if h.get("categoria", "documentos") == categoria]
    disponibles = [h for h in estado if h["disponible"]]
    apagadas = [h for h in estado if not h["disponible"]]

    return render(
        request,
        "documents/inicio.html",
        {
            "seccion": "pdf" if categoria == "documentos" else "texto",
            "etiqueta_seccion": etiqueta,
            "titulo_pagina": titulo,
            "proposito": proposito,
            "grupos": _agrupar(disponibles),
            "disponibles": disponibles,
            # Solo para contarlas y enlazar a `/motores/`, que es donde se explican.
            "apagadas": apagadas,
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
        origen = _origen_del_formulario(request)
    except modo_mod.RutaNoPermitida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/dividir.html", contexto)

    ruta = origen.ruta
    # **El token, no la ruta.** Para un archivo subido son cosas distintas, y devolver la del
    # servidor dejaría que el POST siguiente la tratara como una ruta del disco.
    contexto["ruta_texto"] = origen.token
    contexto["nombre_origen"] = origen.nombre
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
    contexto["ruta"] = origen.token

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

    cabecera, origen, error = _mirar_pdf(request)
    if error:
        messages.error(request, error)
        return render(request, "documents/a_imagenes.html", contexto)

    ruta = origen.ruta
    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre
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

    try:
        origen = _origen_del_formulario(request)
    except modo_mod.RutaNoPermitida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/proteger.html", contexto)

    ruta = origen.ruta
    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre

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

    cabecera, origen, error = _mirar_pdf(request)
    if error:
        messages.error(request, error)
        return render(request, "documents/numerar.html", contexto)

    ruta = origen.ruta
    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre
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

    cabecera, origen, error = _mirar_pdf(request)
    if error:
        messages.error(request, error)
        return render(request, "documents/marca.html", contexto)

    ruta = origen.ruta
    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre
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

    contexto["ajustar_ancho"] = request.POST.get("ajustar_ancho") == "si"

    try:
        origen = _origen_del_formulario(request)
    except modo_mod.RutaNoPermitida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/office.html", contexto)

    ruta = origen.ruta
    contexto["ruta_texto"] = origen.token
    contexto["nombre_origen"] = origen.nombre
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

    try:
        origen = _origen_del_formulario(request)
        ruta = origen.ruta
        que_trae = office_mod.mirar_pdf(ruta)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/a_word.html", contexto)

    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre
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
        destino = a_markdown_mod.a_markdown(origen.ruta, destino=_ruta_de_salida_de(origen, ".md"))
    except a_markdown_mod.SinTextoQueSacar as fallo:
        # **Su propio aviso, y no un error rojo.** El archivo está bien: lo que no tiene es
        # texto. Tratarlo como un fallo manda a alguien a probar otra vez con el mismo
        # archivo, que es exactamente lo que no va a funcionar.
        contexto["sin_texto"] = str(fallo)
        return render(request, "documents/a_markdown.html", contexto)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/a_markdown.html", contexto)

    messages.success(request, f"Hecho: {destino.name}.")
    contexto["generado"] = destino
    contexto["vista_previa"] = _asomarse(destino)
    return render(request, "documents/a_markdown.html", contexto)


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
        destino = desde_markdown_mod.markdown_a_pdf(
            origen.ruta, destino=_ruta_de_salida_de(origen, ".pdf")
        )
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/de_markdown.html", contexto)

    messages.success(request, f"Hecho: {destino.name}.")
    contexto["generado"] = destino
    return render(request, "documents/de_markdown.html", contexto)


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
        "ppp": _entero(request.POST.get("ppp"), 200),
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST":
        return render(request, "documents/comprimir.html", contexto)

    try:
        origen = _origen_del_formulario(request)
        destino, resultado = comprimir_mod.comprimir(
            origen.ruta,
            ppp=contexto["ppp"],
            destino=_ruta_de_salida_de(origen, "_ligero.pdf"),
        )
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/comprimir.html", contexto)

    contexto["resultado"] = resultado
    if destino is None:
        # Ni verde ni rojo: el archivo está bien y ya estaba comprimido.
        contexto["no_valio"] = True
        return render(request, "documents/comprimir.html", contexto)

    messages.success(request, f"Hecho: {destino.name}.")
    contexto["generado"] = destino
    return render(request, "documents/comprimir.html", contexto)


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

    try:
        origen = _origen_del_formulario(request)
        ya_tenia = ocr_mod.ya_tiene_texto(origen.ruta)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/ocr.html", contexto)

    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre
    contexto["ya_tenia_texto"] = ya_tenia

    if request.POST.get("accion") != "reconocer":
        return render(request, "documents/ocr.html", contexto)

    try:
        destino = ocr_mod.reconocer(
            origen.ruta,
            idioma=contexto["idioma"],
            destino=_ruta_de_salida_de(origen, "_con_texto.pdf"),
        )
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/ocr.html", contexto)

    messages.success(request, f"Hecho: {destino.name}.")
    contexto["generado"] = destino
    return render(request, "documents/ocr.html", contexto)


@login_required
def catalogo_a_excel(request):
    """Un catálogo de tubería a una hoja de cálculo, una hoja por tabla.

    **Esta va primero de las dos**, y no por orden alfabético: nadie escribe cincuenta y dos
    columnas desde cero. El camino real es sacar el catálogo que ya se tiene, cambiar lo que
    haga falta, y volver a meterlo con la otra.
    """
    access = catalogos_mod.sondar()
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "Catálogos de tubería",
        "titulo_pagina": "Catálogo de tubería a Excel",
        "proposito": "Para poder editarlo sin abrir Access, y volver a meterlo después.",
        "access": access,
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST" or not access:
        return render(request, "documents/catalogo_a_excel.html", contexto)

    try:
        origen = _origen_del_formulario(request)
        # La ficha del catálogo antes de nada: si alguien se equivocó de archivo, se ve aquí
        # y no después de abrir un Excel de nueve hojas que no son las suyas.
        contexto["tablas"] = catalogos_mod.esquema(origen.ruta)
        destino = catalogos_mod.a_excel(origen.ruta, destino=_ruta_de_salida_de(origen, ".xlsx"))
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/catalogo_a_excel.html", contexto)

    messages.success(request, f"Hecho: {destino.name}.")
    contexto["generado"] = destino
    return render(request, "documents/catalogo_a_excel.html", contexto)


@login_required
def excel_a_catalogo(request):
    """La hoja de cálculo de vuelta al catálogo, **sobre el catálogo original**.

    Dos archivos, y el segundo no es un extra: es el que pone el esquema. Ver el docstring de
    `catalogos.desde_excel`, donde está por qué se copia la plantilla en vez de crear una base
    nueva.
    """
    access = catalogos_mod.sondar()
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "Catálogos de tubería",
        "titulo_pagina": "Excel a catálogo de tubería",
        "proposito": "El camino de vuelta. Hacen falta los dos: la hoja editada y el catálogo.",
        "access": access,
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
    }

    if request.method != "POST" or not access:
        return render(request, "documents/excel_a_catalogo.html", contexto)

    try:
        hoja = _origen_del_formulario(request)
        plantilla = _origen_del_formulario(request, campo="plantilla", archivo="plantilla_subida")
        destino, avisos = catalogos_mod.desde_excel(
            hoja.ruta, plantilla.ruta, destino=_ruta_de_salida_de(hoja, ".mdb")
        )
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/excel_a_catalogo.html", contexto)

    messages.success(request, f"Hecho: {destino.name}.")
    contexto["generado"] = destino
    contexto["avisos"] = avisos
    return render(request, "documents/excel_a_catalogo.html", contexto)


#: Cuántos caracteres del resultado se enseñan antes de descargarlo.
ASOMO = 1200


def _asomarse(destino: Path) -> str:
    """Las primeras líneas del `.md`, para ver que salió lo que se esperaba.

    Es barato y evita el viaje de descargar, abrir y descubrir que la hoja que hacía falta era
    la otra. Se corta por líneas enteras: cortar a mitad de una fila de tabla enseña una tabla
    rota y hace pensar que la conversión lo está.
    """
    try:
        crudo = destino.read_text(encoding="utf-8")
    except OSError:
        return ""
    if len(crudo) <= ASOMO:
        return crudo
    return crudo[:ASOMO].rsplit("\n", 1)[0] + "\n\n…"


def _entero(crudo, por_omision: int) -> int:
    """Un entero del formulario, sin reventar. Un campo numérico es evadible desde fuera."""
    try:
        valor = int(crudo)
    except (TypeError, ValueError):
        return por_omision
    return valor if valor >= 1 else por_omision


def _mirar_pdf(request):
    """Origen resuelto y cabecera leída, o el motivo por el que no.

    Devuelve `(cabecera, origen, error)`. Es el trozo que comparten numerar, marcar y PDF a
    imágenes: resolver de dónde sale el archivo, leer la cabecera, y negarse si pide
    contraseña —porque sin la clave no hay páginas que sacar—.

    **Recibe la petición y no una cadena** desde que estas pantallas aceptan archivos subidos:
    lo que hay que resolver puede venir en `request.FILES` y no en el POST.
    """
    try:
        origen = _origen_del_formulario(request)
        ruta = origen.ruta
    except modo_mod.RutaNoPermitida as fallo:
        return None, None, str(fallo)

    try:
        cabecera = lectura_pdf.leer_cabecera(ruta)
    except lectura_pdf.NoEsPdf as fallo:
        return None, origen, str(fallo)

    if cabecera.cifrado:
        return (
            None,
            origen,
            # El nombre que la persona reconoce, no el que quedó en el servidor.
            f"{origen.nombre} pide contraseña. Quítasela primero en «Proteger PDF».",
        )
    return cabecera, origen, None


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
