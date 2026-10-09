"""Vistas de documentos: escanear con el teléfono. Ver `apps/documents/views/__init__.py`.

Dos pasos, como las demás: **mirar** (se busca la hoja en cada foto y se enseña lo hallado, con las
cuatro esquinas editables) y **hacer** (a la cola). Mirar es síncrono y barato: cada foto se reduce
a unos 360 px para buscar su borde.

Nada se inventa: donde no se distingue una hoja, la tarjeta lo dice, deja la foto entera por omisión
y ofrece marcar las cuatro esquinas a mano —tocando la foto o escribiendo los porcentajes, que es
la vía del teclado—.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render

from apps.core import entrada as entrada_mod
from apps.core import modo as modo_mod
from apps.core import subidas as subidas_mod

from .. import cola as cola_mod
from .. import escanear as escanear_mod
from .. import imagenes_lote as lote_mod
from .. import motor as motor_mod
from .. import ocr as ocr_mod
from ..composicion import ComposicionInvalida
from ._comun import _origenes_pedidos

#: Los nombres de las esquinas, en el orden en que se marcan.
ESQUINAS = (
    ("Arriba a la izquierda", "arriba a la izquierda"),
    ("Arriba a la derecha", "arriba a la derecha"),
    ("Abajo a la derecha", "abajo a la derecha"),
    ("Abajo a la izquierda", "abajo a la izquierda"),
)

#: Lado mayor de la foto que se enseña para marcar. Más que esto no se ve mejor en una pantalla.
LADO_DE_VISTA = 1100


def _porcentaje(valor: float) -> str:
    """`0.3679` como `36.79`: con punto, que es lo que lee un `<input type="number">`."""
    return f"{valor * 100:.2f}"


def _contexto(request, extra: dict | None = None) -> dict:
    tesseract = ocr_mod.sondar()
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Escanear con el teléfono",
        "proposito": "Fotos de hojas a un PDF, rectas y recortadas, una página por foto.",
        "rutas_texto": "",
        "leidas": ", ".join(sorted(e.lstrip(".") for e in lote_mod.extensiones_admitidas())),
        "tamanos": escanear_mod.TAMANOS,
        "tamano": "hoja",
        "mejorar": False,
        "quiere_ocr": False,
        "idiomas": ocr_mod.IDIOMAS,
        "idioma": "spa",
        "tesseract": tesseract,
        "esquinas": ESQUINAS,
        "hojas": [],
    }
    contexto.update(extra or {})
    return contexto


def _tarjetas(origenes: list, posteado: dict | None = None) -> list[dict]:
    """Busca la hoja en cada foto y arma lo que pinta cada tarjeta.

    `posteado` lleva lo que la persona ya había puesto (si un envío vuelve con un error): el modo,
    las esquinas y el orden se respetan; la detección se repite porque es lo que dice el texto.
    """
    tarjetas = []
    for indice, origen in enumerate(origenes):
        imagen = escanear_mod.abrir_derecha(origen.ruta)
        deteccion = escanear_mod.detectar_hoja(imagen)
        imagen.close()

        if deteccion.esquinas:
            valores = [(_porcentaje(x), _porcentaje(y)) for x, y in deteccion.esquinas]
            modo = "esquinas"
        else:
            valores = [("", "")] * 4
            modo = "entera"
        orden = str(indice + 1)

        if posteado is not None:
            modo = posteado.get(f"modo_{indice}") or modo
            orden = posteado.get(f"orden_{indice}") or orden
            valores = [
                (posteado.get(f"e{indice}_{k}x", ""), posteado.get(f"e{indice}_{k}y", ""))
                for k in range(4)
            ]

        completas = all(x != "" and y != "" for x, y in valores)
        tarjetas.append(
            {
                "indice": indice,
                "numero": indice + 1,
                "nombre": origen.nombre,
                "token": origen.token,
                "detectada": bool(deteccion.esquinas),
                "motivo": deteccion.explicacion,
                "modo": modo,
                "orden": orden,
                "esquinas": [
                    {"k": k, "x": x, "y": y, "etiqueta": ESQUINAS[k][0]}
                    for k, (x, y) in enumerate(valores)
                ],
                "puntos": " ".join(f"{x},{y}" for x, y in valores) if completas else "",
            }
        )
    return tarjetas


def _flotante(texto) -> float | None:
    try:
        valor = float(str(texto).strip().replace(",", "."))
    except ValueError:
        return None
    return valor if 0 <= valor <= 100 else None


def _hojas_pedidas(post, origenes: list) -> tuple[list[dict], list[int], str]:
    """`(hojas, orden, problema)`: lo que se encola y en qué orden, o por qué no."""
    hojas: list[dict] = []
    orden: list[int] = []
    for indice, origen in enumerate(origenes):
        modo = post.get(f"modo_{indice}")
        if modo not in ("esquinas", "entera"):
            return [], [], f"Falta decir qué hacer con la foto {indice + 1} ({origen.nombre})."
        try:
            posicion = int(post.get(f"orden_{indice}") or indice + 1)
        except ValueError:
            return [], [], f"La posición de la foto {indice + 1} no es un número."
        orden.append(posicion)

        if modo == "entera":
            hojas.append({"modo": "entera", "esquinas": None})
            continue
        esquinas = []
        for k in range(4):
            x = _flotante(post.get(f"e{indice}_{k}x", ""))
            y = _flotante(post.get(f"e{indice}_{k}y", ""))
            if x is None or y is None:
                return (
                    [],
                    [],
                    f"Faltan las esquinas de la foto {indice + 1} ({origen.nombre}), o no están "
                    "entre 0 y 100. Márquelas de nuevo, o deje la foto entera.",
                )
            esquinas.append((x / 100, y / 100))
        try:
            # La forma no depende del tamaño: una hoja convexa lo es en cualquier escala.
            escanear_mod.comprobar_esquinas(esquinas, 1000, 1000)
        except ComposicionInvalida as fallo:
            return [], [], f"Foto {indice + 1} ({origen.nombre}): {fallo}"
        hojas.append({"modo": "esquinas", "esquinas": [list(e) for e in esquinas]})
    return hojas, orden, ""


@login_required
def escanear_vista(request):
    """Fotos de hojas a un PDF: mirar la hoja de cada foto y, después, hacerlo en la cola."""
    contexto = _contexto(request, {"rutas_texto": (request.GET.get("ruta") or "").strip()})
    if request.method != "POST":
        return render(request, "documents/escanear.html", contexto)

    texto = request.POST.get("archivos_texto", "")
    llegadas = request.FILES.getlist("archivos")
    if llegadas:
        try:
            nuevas = subidas_mod.guardar_varios(llegadas, usuario=request.user)
        except ValidationError as fallo:
            messages.error(request, "; ".join(fallo.messages))
            return render(request, "documents/escanear.html", contexto)
        texto = "\n".join(filter(None, [texto.strip(), *(s.token for s in nuevas)]))

    try:
        origenes = _origenes_pedidos(texto, request.user)
    except modo_mod.RutaNoPermitida as fallo:
        contexto["rutas_texto"] = texto
        messages.error(request, str(fallo))
        return render(request, "documents/escanear.html", contexto)
    contexto["rutas_texto"] = "\n".join(o.token for o in origenes)

    if not origenes:
        messages.error(request, "No indicó ninguna foto.")
        return render(request, "documents/escanear.html", contexto)
    problema = next((m for o in origenes if (m := lote_mod.motivo_si_no_se_lee(o.nombre))), "")
    if problema:
        messages.error(request, problema)
        return render(request, "documents/escanear.html", contexto)

    accion = request.POST.get("accion") or "mirar"
    posteado = request.POST if accion == "hacer" else None
    try:
        contexto["hojas"] = _tarjetas(origenes, posteado)
    except ComposicionInvalida as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/escanear.html", contexto)

    if accion != "hacer":
        return render(request, "documents/escanear.html", contexto)

    # --- Hacer -----------------------------------------------------------
    contexto["tamano"] = request.POST.get("tamano") or "hoja"
    contexto["mejorar"] = request.POST.get("mejorar") == "on"
    contexto["quiere_ocr"] = request.POST.get("ocr") == "on"
    contexto["idioma"] = request.POST.get("idioma") or "spa"

    if contexto["tamano"] not in escanear_mod.TAMANOS:
        messages.error(request, f"«{contexto['tamano']}» no es un tamaño de los que se ofrecen.")
        return render(request, "documents/escanear.html", contexto)

    opciones_ocr = {}
    if contexto["quiere_ocr"]:
        if contexto["idioma"] not in ocr_mod.IDIOMAS:
            messages.error(request, "Ese idioma no es de los que se ofrecen.")
            return render(request, "documents/escanear.html", contexto)
        opciones_ocr = {"ocr": True, "idioma": contexto["idioma"]}
        # Regla 4: sin Tesseract no se entrega un PDF «sin texto» donde se pidió con texto.
        estado = motor_mod.disponibilidad("escanear", opciones_ocr)
        if not estado.disponible:
            messages.error(request, " ".join(filter(None, [estado.mensaje, estado.sugerencia])))
            return render(request, "documents/escanear.html", contexto)

    hojas, orden, problema = _hojas_pedidas(request.POST, origenes)
    if problema:
        messages.error(request, problema)
        return render(request, "documents/escanear.html", contexto)

    # El orden que se eligió: por la posición escrita y, a igual posición, el de la lista.
    secuencia = sorted(range(len(origenes)), key=lambda i: (orden[i], i))
    return cola_mod.encolar(
        request,
        "escanear",
        [origenes[i] for i in secuencia],
        {
            "hojas": [hojas[i] for i in secuencia],
            "tamano": contexto["tamano"],
            "mejorar": contexto["mejorar"],
            **opciones_ocr,
        },
        sufijo="_escaneado.pdf",
    )


@login_required
def escanear_foto(request):
    """La foto de una subida, derecha y más chica, para marcar su hoja.

    Por identificador y por la misma puerta que las demás lecturas: una subida solo la ve su dueño.
    """
    try:
        origen = entrada_mod.resolver(request.GET.get("ruta") or "", usuario=request.user)
    except modo_mod.RutaNoPermitida:
        return HttpResponseBadRequest("Ruta no permitida.")
    try:
        jpeg = escanear_mod.vista_previa(origen.ruta, LADO_DE_VISTA)
    except ComposicionInvalida:
        return HttpResponseBadRequest("No se pudo abrir esa foto.")
    respuesta = HttpResponse(jpeg, content_type="image/jpeg")
    # `private`: es la foto de alguien, no se guarda en ningún intermedio compartido.
    respuesta["Cache-Control"] = "private, max-age=600"
    return respuesta
