"""Vistas de vuelos: la portada de Topografía. Ver `apps/vuelos/views/__init__.py`."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.documents.views._comun import estado_de_herramientas

#: Las herramientas de cada sección de la portada, por su `id` en `herramientas.py`.
LA_PRINCIPAL = ("vuelo_dron",)
LAS_UTILIDADES = ("telemetria", "fotos_dron", "video")


@login_required
def vuelos(request):
    """La portada de «Topografía» (F20.1): el grupo `gnss` de la taxonomía, en tres secciones.

    **Procesamiento GNSS** (los crudos de receptor a RINEX viven en «Convertir»: aquí solo se
    enlaza), **Procesamiento de trayectoria** (la herramienta principal) y **Utilidades del dron**
    (la traza, las fotos y el video: visibles, pero plegadas y en segundo plano).

    Conserva la ruta `documents:vuelos` de cuando era el índice de «Vuelos de dron». Las apagadas se
    muestran con su motivo y su alternativa, nunca ocultas (regla 4 de `AGENTS.md`).
    """
    por_id = {h["id"]: h for h in estado_de_herramientas()}
    return render(
        request,
        "vuelos/topografia.html",
        {
            "seccion": "pdf",
            "etiqueta_seccion": "Topografía",
            "titulo_pagina": "Topografía",
            "proposito": (
                "Lo que se mide en campo, posprocesado en el servidor de la oficina: datos de "
                "receptor GNSS, la trayectoria de un vuelo y sus fotos."
            ),
            "principales": [por_id[i] for i in LA_PRINCIPAL if i in por_id],
            "utilidades": [por_id[i] for i in LAS_UTILIDADES if i in por_id],
        },
    )
