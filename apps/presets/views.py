from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.formats import catalogo

from .models import ConversionPreset


@login_required
def lista(request):
    return render(
        request,
        "presets/lista.html",
        {
            "de_fabrica": ConversionPreset.objects.filter(de_fabrica=True),
            # **Los de quien pregunta, no los de todos.** Un preajuste lleva el nombre del
            # cliente y del contrato — «Entrega cliente BHP» — así que la lista de otro dice
            # con quién está trabajando. En un servidor compartido eso no es un detalle.
            "propios": ConversionPreset.propios_de(request.user),
            "formatos": {f.codigo: f.nombre for f in catalogo.FORMATOS.values()},
            "seccion": "preajustes",
            "etiqueta_seccion": "Preajustes",
            "titulo_pagina": "Destinos guardados con nombre propio",
            "proposito": (
                "Los de fábrica salen de los perfiles y se actualizan con ellos. Copia uno "
                "y cámbialo para tener el tuyo: «Entrega cliente BHP», por ejemplo."
            ),
        },
    )


@login_required
@require_POST
def copiar(request, slug):
    """Duplica un preajuste para poder cambiarlo.

    Los de fábrica no se editan: son el punto de partida de todos los demás, y perderlos
    dejaría a alguien sin referencia. Copiarlos sí, y eso cubre el caso real — «como el de
    Civil 3D, pero con la compresión cambiada».
    """
    # De fábrica o suyo. El de otro devuelve 404 y no 403: además de correcto, no confirma
    # que exista, que es la misma regla que en `jobs/views.py::_mio`.
    original = get_object_or_404(ConversionPreset.visibles_para(request.user), slug=slug)

    base = slugify(f"{original.slug}-copia")
    candidato = base
    numero = 2
    while ConversionPreset.objects.filter(slug=candidato).exists():
        candidato = f"{base}-{numero}"
        numero += 1

    ConversionPreset.objects.create(
        slug=candidato,
        nombre=f"{original.nombre} (copia)",
        descripcion=original.descripcion,
        target_format_code=original.target_format_code,
        target_profile_id=original.target_profile_id,
        options=dict(original.options),
        target_crs_code=original.target_crs_code,
        owner=request.user,
        de_fabrica=False,
    )
    messages.info(request, f"Copiado como «{original.nombre} (copia)».")
    return redirect("presets:lista")


@login_required
@require_POST
def borrar(request, slug):
    """Borra un preajuste **propio**.

    Antes bastaba con conocer el `slug` para borrar el de cualquiera, y era un POST de un
    clic. No era una fuga de información: era destruir el trabajo de otro sin dejar rastro y
    sin que se enterase, que es peor.

    La búsqueda va contra `visibles_para` y no contra los propios a secas para que el intento
    de borrar uno de fábrica siga contestando lo que explica —«cópialos y cambia la copia»—
    en vez de un 404 que no enseña nada.
    """
    preajuste = get_object_or_404(ConversionPreset.visibles_para(request.user), slug=slug)
    if preajuste.de_fabrica:
        messages.error(
            request, "Los preajustes de fábrica no se borran; cópialos y cambia la copia."
        )
        return redirect("presets:lista")
    nombre = preajuste.nombre
    preajuste.delete()
    messages.info(request, f"Borrado «{nombre}».")
    return redirect("presets:lista")
