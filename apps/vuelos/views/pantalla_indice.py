"""Vistas de vuelos: el índice. Ver `apps/vuelos/views/__init__.py`."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required

from apps.documents.views._comun import _indice


@login_required
def vuelos(request):
    """El índice de «Vuelos de dron»: la traza de un video, las fotos y el proceso PPK.

    Tiene el suyo, como GNSS, y no comparte el de texto: no tienen nada que ver y el desplegable
    prometería una separación que no existe.
    """
    return _indice(
        request,
        categoria="vuelos",
        etiqueta="Vuelos de dron",
        titulo="Lo que graba un vuelo",
        proposito=(
            "La traza de un video, las fotos con su posición y el proceso que las corrige. "
            "Todo pasa en el servidor de la oficina."
        ),
    )
