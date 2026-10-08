"""Vistas de documentos: inicio. Ver `apps/documents/views/__init__.py`."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required

# **Reexportado**: el índice, las pruebas y `acciones.py` lo leen de aquí desde siempre. Los
# datos viven en `herramientas.py` para que el modelo y el proceso hijo puedan leerlos sin
# importar las vistas.
from ._comun import _indice


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
