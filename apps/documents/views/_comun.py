"""Vistas de documentos:  comun. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ValidationError
from django.shortcuts import render

from apps.core import entrada as entrada_mod
from apps.core import modo as modo_mod
from apps.core import subidas as subidas_mod
from apps.dashboard import taxonomia
from apps.formats import pdf as lectura_pdf

from .. import catalogos as catalogos_mod
from .. import ocr as ocr_mod
from .. import office as office_mod
from .. import portadas as portadas_mod
from .. import receta as receta_mod

# **Reexportado**: el índice, las pruebas y `acciones.py` lo leen de aquí desde siempre. Los
# datos viven en `herramientas.py` para que el modelo y el proceso hijo puedan leerlos sin
# importar las vistas.
from ..herramientas import HERRAMIENTAS

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
            "Elija qué páginas entran, en qué orden, y gire las láminas que lo necesiten."
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


def _agrupar(herramientas, grupos: tuple[str, ...]):
    """Las herramientas por grupo de la **taxonomía única**, en su orden (`taxonomia.GRUPOS`).

    **Siete tarjetas seguidas se reparten en cuatro y tres y dejan un hueco**, y el hueco se
    lee como si faltara algo. Agrupadas, cada fila tiene el tamaño que le toca y además el
    encabezado contesta antes de que haya que leer los nombres uno a uno.

    Un grupo vacío no se pinta: con Office ausente, «convertir documentos» pierde dos de sus
    cuatro y sigue teniendo sentido, pero si algún día se queda sin ninguna, un encabezado
    solo sería peor que nada.

    Antes había aquí una lista propia (`GRUPOS`: componer, transformar, marcar, proteger…) que no
    coincidía con la de la portada y el lateral. Ahora este índice enseña **un trozo del mismo
    árbol**: ver `apps/dashboard/taxonomia.py`.
    """
    por_grupo: dict[str, list] = {}
    for herramienta in herramientas:
        por_grupo.setdefault(taxonomia.grupo_de_documento(herramienta["id"]), []).append(
            herramienta
        )

    return [
        {
            "clave": grupo.id,
            "titulo": grupo.titulo,
            "cuando": grupo.cuando,
            "herramientas": por_grupo[grupo.id],
        }
        for grupo in taxonomia.GRUPOS
        if grupo.id in grupos and por_grupo.get(grupo.id)
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
    # Las plantillas de portada de la empresa: archivos fuera del repositorio.
    plantillas = portadas_mod.sondar()
    # FFmpeg, para el video: programa aparte, sondeado (D1).
    from .. import video as video_mod

    ffmpeg = video_mod.sondar()
    # Ghostscript, para el PDF/A: programa aparte, sondeado (D1).
    from .. import pdfa as pdfa_mod

    ghostscript = pdfa_mod.sondar()

    estado = []
    for herramienta in HERRAMIENTAS:
        fila = dict(herramienta)
        if herramienta.get("exige_office"):
            fila["disponible"] = bool(office)
            fila["motivo"] = office.motivo
            fila["sugerencia"] = office.sugerencia
            # Sin Office, «Office a PDF» se puede con LibreOffice, **dicho**: el PDF puede variar
            # y la pantalla pide aceptarlo (F17.1). «PDF a Word» sigue siendo solo de Word.
            if not office and herramienta.get("id") == "office" and office_mod.sondar_libreoffice():
                fila["disponible"] = True
                fila["variante"] = "con LibreOffice: el PDF puede variar"
        elif herramienta.get("exige_ffmpeg"):
            fila["disponible"] = bool(ffmpeg)
            fila["motivo"] = ffmpeg.motivo
            fila["sugerencia"] = ffmpeg.sugerencia
        elif herramienta.get("exige_ghostscript"):
            fila["disponible"] = bool(ghostscript)
            fila["motivo"] = ghostscript.motivo
            fila["sugerencia"] = ghostscript.sugerencia
        elif herramienta.get("exige_access"):
            fila["disponible"] = bool(access)
            fila["motivo"] = access.motivo
            fila["sugerencia"] = access.sugerencia
        elif herramienta.get("exige_plantillas"):
            fila["disponible"] = bool(plantillas)
            fila["motivo"] = plantillas.motivo
            fila["sugerencia"] = plantillas.sugerencia
        elif herramienta.get("exige_tesseract"):
            fila["disponible"] = bool(tesseract)
            fila["motivo"] = tesseract.motivo
            fila["sugerencia"] = tesseract.sugerencia
        else:
            fila["disponible"] = True
        estado.append(fila)
    return estado


def _indice(request, *, categoria: str, etiqueta: str, titulo: str, proposito: str):
    """El índice de una categoría. Lo comparten las dos pantallas.

    Las apagadas se cuentan **dentro de su categoría**: decirle a quien mira las de texto que
    hay dos apagadas de Office sería contarle un problema que no es el suyo.
    """
    grupos = taxonomia.INDICES[categoria]
    estado = [
        h for h in estado_de_herramientas() if taxonomia.grupo_de_documento(h["id"]) in grupos
    ]
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
            "grupos": _agrupar(disponibles, grupos),
            "disponibles": disponibles,
            # Solo para contarlas y enlazar a `/motores/`, que es donde se explican.
            "apagadas": apagadas,
        },
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
            f"{origen.nombre} pide contraseña. Quítesela primero en «Proteger o desbloquear PDF».",
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
