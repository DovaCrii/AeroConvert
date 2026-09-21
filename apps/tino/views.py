"""La pantalla de Tino.

## Una pantalla y no un chat flotante en todas partes

Un ayudante que sigue a la gente por la aplicación pidiendo atención es lo contrario de lo
que hace falta aquí: quien está convirtiendo una ortofoto no quiere que le hablen. Tino
está donde se va a buscarlo, y se va a buscarlo cuando hace falta.

## Y lo que contesta sale de esta máquina

Ver `saber.py`. La puerta hacia fuera nace cerrada y se dice en pantalla — **cada vez**, no
en una página de condiciones que nadie abre.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from . import fuera as fuera_mod
from . import saber as saber_mod

#: Preguntas de ejemplo, y **las tres se contestan desde esta máquina**.
#:
#: Es lo que demuestra el argumento entero sin explicarlo: quien pulsa una recibe una
#: respuesta exacta y no ha salido nada del equipo.
EJEMPLOS = (
    "¿puedo pasar un tif a jp2?",
    "¿qué es un COG?",
    "quitar la contraseña de un PDF",
)


@login_required
def preguntar(request):
    pregunta = (request.GET.get("p") or "").strip()
    respuesta = saber_mod.contestar(pregunta) if pregunta else None

    contexto = {
        "seccion": "tino",
        "etiqueta_seccion": "Tino",
        "titulo_pagina": "Pregúntale a Tino",
        "proposito": "Lo que esta máquina sabe de tus archivos y de lo que se puede hacer.",
        "p": pregunta,
        "respuesta": respuesta,
        "ejemplos": EJEMPLOS,
        "de_fuera": fuera_mod.sondar(),
    }

    # **Lo que saldría, enseñado antes de que salga.** Solo cuando hay pregunta y aquí no se
    # supo: es el único caso en que la puerta de fuera tendría algo que hacer, y enseñarlo
    # siempre convertiría el aviso en decorado que nadie lee.
    if pregunta and respuesta is None:
        contexto["saldria"] = fuera_mod.limpiar(pregunta)

    if request.headers.get("HX-Request"):
        return render(request, "tino/_respuesta.html", contexto)
    return render(request, "tino/preguntar.html", contexto)
