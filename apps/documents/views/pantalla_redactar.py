"""Vistas de documentos: redactar. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

import json
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .. import cola as cola_mod
from .. import redactar as redactar_mod
from ..composicion import ComposicionInvalida
from ._comun import _entero, _mirar_pdf

#: «1: 20, 30, 120, 50»: página, y luego izquierda, arriba, derecha y abajo en milímetros.
_AREA = re.compile(
    r"^\s*(\d+)\s*[:;]\s*([\d.,]+)\s*[,;]\s*([\d.,]+)\s*[,;]\s*([\d.,]+)\s*[,;]\s*([\d.,]+)\s*$"
)


def _numero(texto: str) -> float:
    return float(texto.replace(",", "."))


def _leer_areas(texto: str) -> list[redactar_mod.Area]:
    areas = []
    for numero, linea in enumerate((texto or "").splitlines(), start=1):
        if not linea.strip():
            continue
        m = _AREA.match(linea)
        if m is None:
            raise ComposicionInvalida(
                f"El área de la línea {numero} no se entiende. Use «página: izquierda, arriba, "
                "derecha, abajo», en milímetros, por ejemplo «1: 20, 30, 120, 50»."
            )
        pagina = int(m.group(1))
        x0, y0, x1, y1 = (_numero(m.group(i)) for i in range(2, 6))
        areas.append(redactar_mod.Area(pagina, x0, y0, x1, y1))
    return areas


@login_required
def redactar_vista(request):
    """Tachar de verdad nombres, RUT o áreas de un PDF.

    **Los términos no vuelven al formulario ni se guardan**: son justo lo que se tapa. Salen de
    la pantalla por el mismo camino que la contraseña de «Proteger» y el campo se devuelve vacío
    en cada respuesta, para que no quede escrito en una pantalla que alguien deja abierta.
    """
    contexto = {
        "seccion": "pdf",
        "etiqueta_seccion": "PDF",
        "titulo_pagina": "Redactar: tachar de verdad",
        "proposito": "Que lo tachado ya no exista en el archivo: ni en el texto, ni debajo.",
        "ruta_texto": (request.GET.get("ruta") or "").strip(),
        "resoluciones": redactar_mod.RESOLUCIONES,
        "ppp_elegido": 200,
        "areas_texto": "",
    }

    if request.method != "POST":
        return render(request, "documents/redactar.html", contexto)

    contexto["areas_texto"] = (request.POST.get("areas") or "").strip()
    contexto["ppp_elegido"] = _entero(request.POST.get("ppp"), 200)

    cabecera, origen, error = _mirar_pdf(request)
    if error:
        messages.error(request, error)
        return render(request, "documents/redactar.html", contexto)

    contexto["ruta_texto"] = contexto["ruta"] = origen.token
    contexto["nombre_origen"] = origen.nombre
    contexto["cabecera"] = cabecera

    if request.POST.get("accion") != "redactar":
        return render(request, "documents/redactar.html", contexto)

    try:
        terminos = redactar_mod.limpiar_terminos((request.POST.get("terminos") or "").splitlines())
        areas = _leer_areas(contexto["areas_texto"])
        if not terminos and not areas:
            raise ComposicionInvalida(
                "Escriba qué tachar: un texto por línea, o un área con su página."
            )
        if contexto["ppp_elegido"] not in redactar_mod.RESOLUCIONES:
            raise ComposicionInvalida(
                f"«{contexto['ppp_elegido']}» no es una de las resoluciones que se ofrecen."
            )
        for area in areas:
            if not 1 <= area.pagina <= cabecera.cuantas:
                raise ComposicionInvalida(
                    f"{origen.nombre} tiene {cabecera.cuantas} página(s): no existe la "
                    f"{area.pagina}."
                )
            if not (area.x1 > area.x0 and area.y1 > area.y0):
                raise ComposicionInvalida(f"El área de la página {area.pagina} no tiene tamaño.")
    except (ComposicionInvalida, ValueError) as fallo:
        messages.error(request, str(fallo))
        return render(request, "documents/redactar.html", contexto)

    try:
        return cola_mod.encolar(
            request,
            "redactar",
            [origen],
            {
                "ppp": contexto["ppp_elegido"],
                "areas": [
                    {"pagina": a.pagina, "x0": a.x0, "y0": a.y0, "x1": a.x1, "y1": a.y1}
                    for a in areas
                ],
                # Hace que «Reintentar» vuelva aquí: los términos ya no están en ningún sitio.
                "pide_contrasena": True,
            },
            sufijo="_redactado.pdf",
            secreto=json.dumps(terminos, ensure_ascii=False),
        )
    finally:
        terminos = []  # noqa: F841 - que no siga viva en el marco más de lo necesario
