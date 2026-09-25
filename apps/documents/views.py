"""Las pantallas de las veinte herramientas de documentos.

## Mirar aquí, hacer en la cola

Hasta la fase 9 esto decía por qué las herramientas **no** pasaban por la cola: componer se
escribe en menos de un segundo, y esperar a un proceso en segundo plano para reordenar tres
hojas parecía absurdo. El razonamiento era bueno para Unir y malo para todo lo demás, y costó
caro sin que se viera:

- gunicorn corta la petición a los 120 s, y el OCR de un escaneo de cuarenta páginas moría a
  medias sin decir nada;
- trece de las veinte no dejaban descargar lo que salía de un archivo subido;
- y el uso no dejaba rastro: el servidor decía «0 trabajos» sin distinguir «nadie ha usado
  esto» de «se ha usado mucho, pero no aquí».

Así que ahora se separan dos cosas que antes iban juntas. **Mirar se hace aquí**, síncrono y
barato: leer la cabecera, avisar de que es un escaneo, dejar que Unir ordene las páginas,
decir que la contraseña es corta. **Hacer va a la cola**, por `cola.encolar()`, y la ficha
del trabajo trae el progreso, el recibo, la descarga con dueño, reintentar y cancelar. Ver
`tarea.py` para el proceso hijo y `motor.py` para cómo se verifica lo que sale.

La regla para lo que queda aquí: **todo lo que se pueda comprobar sin abrir el documento
entero se comprueba antes de encolar**, con el formulario delante. Descubrirlo en la cola
manda a una ficha roja y de vuelta a esta pantalla con el formulario vacío.

## Sin estado en el servidor

La receta de Unir viaja en un campo oculto del propio formulario, así que no hay sesión que
caducar ni fila que limpiar, y dos personas pueden componer a la vez sin pisarse. Es la misma
cadena que se encola al generar. Ver `receta.py`.

## Lo que se conserva del resto de la aplicación

**La ruta se comprueba contra las raíces permitidas** igual que en la inspección, y **el
original no se toca**: el corredor compara su huella antes y después de cada intento.
"""

from __future__ import annotations

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
from apps.formats import pdf as lectura_pdf

from . import a_imagenes as a_imagenes_mod
from . import a_markdown as a_markdown_mod
from . import catalogos as catalogos_mod
from . import cola as cola_mod
from . import comprimir as comprimir_mod
from . import dividir as dividir_mod
from . import marcas as marcas_mod
from . import miniaturas
from . import ocr as ocr_mod
from . import office as office_mod
from . import receta as receta_mod
from . import seguridad as seguridad_mod
from .composicion import GIROS, ComposicionInvalida

# **Reexportado**: el índice, las pruebas y `acciones.py` lo leen de aquí desde siempre. Los
# datos viven en `herramientas.py` para que el modelo y el proceso hijo puedan leerlos sin
# importar las vistas.
from .herramientas import HERRAMIENTAS

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
        # Decía «todo pasa en tu equipo: los archivos no se suben», escrito cuando esto era
        # una estación de trabajo. En el servidor sí se suben —a él, y a nadie más—, y la
        # frase vieja contradecía el botón de subir de la misma pantalla.
        proposito=(
            "Todo pasa en el servidor de la oficina: nada sale a un servicio de fuera, y el "
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
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/dividir.html", contexto)

    # Dos trozos iguales saldrían con el mismo nombre, y el segundo pisaría al primero.
    # Antes pasaba en silencio; dentro de un zip, además, lo dejaría con una pieza de menos.
    repetidos = sorted({t.sufijo.lstrip("_") for t in trozos if trozos.count(t) > 1})
    if repetidos:
        messages.error(
            request,
            f"«{', '.join(repetidos)}» está más de una vez. Cada trozo es un archivo, "
            "y dos iguales saldrían con el mismo nombre.",
        )
        return render(request, "documents/dividir.html", contexto)

    # Un trozo sale suelto, con el nombre que ya tenía; varios, juntos en un zip.
    sufijo = f"{trozos[0].sufijo}.pdf" if len(trozos) == 1 else "_partes.zip"
    return cola_mod.encolar(
        request,
        "dividir",
        [origen],
        {"trozos": [[t.desde, t.hasta] for t in trozos]},
        sufijo=sufijo,
    )


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

    contrasena = request.POST.get("contrasena") or ""
    try:
        # **Todo lo que se puede decir aquí se dice aquí**, con el formulario delante: una
        # contraseña corta o que no abre el archivo, descubierta en la cola, manda a una
        # ficha roja y de vuelta a esta pantalla a escribirla otra vez.
        problema = _problema_de_proteger(accion, origen, cabecera, contrasena)
        if problema:
            messages.error(request, problema)
            return render(request, "documents/proteger.html", contexto)

        sufijo = "_protegido.pdf" if accion == "proteger" else "_sin_clave.pdf"
        return cola_mod.encolar(
            request,
            "proteger",
            [origen],
            # `pide_contrasena` es lo que hace que «Reintentar» vuelva aquí a pedirla, en vez
            # de repetir un trabajo que ya no tiene con qué abrir el archivo.
            {"accion": accion, "pide_contrasena": True},
            sufijo=sufijo,
            secreto=contrasena,
        )
    finally:
        # Que no quede viva en el marco más de lo necesario.
        contrasena = ""  # noqa: F841


def _problema_de_proteger(accion: str, origen, cabecera, contrasena: str) -> str:
    """Lo que impide proteger o quitar, en una frase. Vacío si se puede.

    Con `origen.nombre`: el que la persona reconoce, no el que quedó en el servidor.
    """
    if accion == "proteger":
        if cabecera.cifrado:
            return (
                f"{origen.nombre} ya está protegido. Quítale la contraseña primero si quieres "
                "cambiarla."
            )
        if len(contrasena) < seguridad_mod.MINIMO:
            return f"La contraseña tiene que tener al menos {seguridad_mod.MINIMO} caracteres."
        return ""
    if not cabecera.cifrado:
        return f"{origen.nombre} no pide contraseña: no hay nada que quitar."
    if not seguridad_mod.abre(origen.ruta, contrasena):
        return "Esa contraseña no abre el archivo."
    return ""


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

    contexto["ruta_texto"] = origen.token
    contexto["nombre_origen"] = origen.nombre

    # Por la extensión del nombre que se reconoce, que es el que trae la del original.
    try:
        programa = office_mod.programa_de(origen.nombre)
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/office.html", contexto)
    if not office.tiene(programa):
        messages.error(request, f"{office_mod.NOMBRES[programa]} no está instalado en este equipo.")
        return render(request, "documents/office.html", contexto)

    return cola_mod.encolar(
        request,
        "office",
        [origen],
        {"ajustar_ancho": contexto["ajustar_ancho"]},
        sufijo=".pdf",
    )


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

    return cola_mod.encolar(request, "a_word", [origen], {}, sufijo=".docx")


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

    return cola_mod.encolar(request, "md_a_pdf", [origen], {}, sufijo=".pdf")


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
        # Se abre aquí antes de encolar: un archivo que no es un catálogo se dice con el
        # formulario delante, no en una ficha roja. Las tablas salen en el recibo.
        catalogos_mod.esquema(origen.ruta)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/catalogo_a_excel.html", contexto)

    return cola_mod.encolar(request, "catalogo_excel", [origen], {}, sufijo=".xlsx")


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

    from apps.jobs.models import EntradaDeTrabajo

    try:
        hoja = _origen_del_formulario(request)
        plantilla = _origen_del_formulario(request, campo="plantilla", archivo="plantilla_subida")
        # La plantilla se abre aquí: si no es un catálogo, se dice antes de encolar.
        catalogos_mod.esquema(plantilla.ruta)
    except (modo_mod.RutaNoPermitida, ComposicionInvalida) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/excel_a_catalogo.html", contexto)

    return cola_mod.encolar(
        request,
        "excel_catalogo",
        [hoja, plantilla],
        {},
        sufijo=".mdb",
        papeles=[EntradaDeTrabajo.HOJA, EntradaDeTrabajo.PLANTILLA],
    )


def _ppp(crudo) -> int:
    """La resolución de Comprimir: 200 si no viene, **y el 0 se respeta**."""
    try:
        return int(crudo)
    except (TypeError, ValueError):
        return 200


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
