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
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.core import modo as modo_mod
from apps.engines.base import ruta_parcial
from apps.formats import pdf as lectura_pdf

from . import receta as receta_mod
from .composicion import ComposicionInvalida, componer

#: Cuántos PDF se admiten de una vez. Más que esto no es una entrega: es un lote, y para
#: un lote hace falta otra pantalla.
MAXIMO_ARCHIVOS = 20


@dataclass(frozen=True)
class Fila:
    """Una página, lista para pintar."""

    indice: int
    nombre_archivo: str
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
        "seccion": "unir-pdf",
        "etiqueta_seccion": "Unir PDF",
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


def _ruta_de_salida(primero: Path) -> Path:
    """Junto al primer archivo, con un sufijo que dice qué es.

    El mismo criterio que el resto de la aplicación: quien compone una entrega la quiere
    al lado de sus archivos, no perdida en un directorio del programa.
    """
    return primero.with_name(f"{primero.stem}_unido.pdf")
