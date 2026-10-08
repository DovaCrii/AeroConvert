from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.formats import catalogo
from apps.formats import crs as crs_mod
from apps.jobs.models import LoteDeTrabajos

from . import aplicar as aplicar_mod
from . import paquetes as paquetes_mod
from .models import ConversionPreset, PaqueteDeEntrega


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
                "Los de fábrica salen de los perfiles y se actualizan con ellos. Copie uno "
                "y cámbielo para tener el suyo: «Entrega cliente BHP», por ejemplo."
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
    de borrar uno de fábrica siga contestando lo que explica —«cópielos y cambie la copia»—
    en vez de un 404 que no enseña nada.
    """
    preajuste = get_object_or_404(ConversionPreset.visibles_para(request.user), slug=slug)
    if preajuste.de_fabrica:
        messages.error(
            request, "Los preajustes de fábrica no se borran; cópielos y cambie la copia."
        )
        return redirect("presets:lista")
    nombre = preajuste.nombre
    preajuste.delete()
    messages.info(request, f"Borrado «{nombre}».")
    return redirect("presets:lista")


# --- Paquetes de entrega y lotes (F16.1 y F16.2) ------------------------------------------------


def _contexto_de_paquetes(request, **extra):
    propios = PaqueteDeEntrega.propios_de(request.user)
    nombres = {p.slug: p.nombre for p in ConversionPreset.visibles_para(request.user)}
    return {
        "paquetes": [
            {"paquete": p, "pasos": [nombres.get(s, f"{s} (ya no existe)") for s in p.pasos]}
            for p in propios
        ],
        "preajustes": ConversionPreset.visibles_para(request.user),
        "lotes": LoteDeTrabajos.objects.filter(owner=request.user)[:10],
        "marcas": paquetes_mod.MARCAS,
        "patron_por_omision": paquetes_mod.PATRON_POR_OMISION,
        "seccion": "preajustes",
        "etiqueta_seccion": "Preajustes",
        "titulo_pagina": "Paquetes de entrega",
        "proposito": (
            "Una receta con nombre: varios destinos que se aplican juntos a un archivo o a una "
            "carpeta entera, con el nombre de salida que usted fije."
        ),
        **extra,
    }


@login_required
def paquetes(request):
    return render(request, "presets/paquetes.html", _contexto_de_paquetes(request))


def _slug_libre(nombre: str) -> str:
    base = slugify(nombre) or "paquete"
    candidato, numero = base, 2
    while PaqueteDeEntrega.objects.filter(slug=candidato).exists():
        candidato = f"{base}-{numero}"
        numero += 1
    return candidato


@login_required
@require_POST
def paquete_nuevo(request):
    nombre = (request.POST.get("nombre") or "").strip()
    pasos = [s for s in request.POST.getlist("pasos") if s]
    patron = (request.POST.get("patron") or "").strip() or paquetes_mod.PATRON_POR_OMISION
    crs_texto = (request.POST.get("crs") or "").strip()
    try:
        if not nombre:
            raise paquetes_mod.PaqueteInvalido("El paquete necesita un nombre.")
        if not pasos:
            raise paquetes_mod.PaqueteInvalido("Elija al menos un preajuste.")
        visibles = set(
            ConversionPreset.visibles_para(request.user)
            .filter(slug__in=pasos)
            .values_list("slug", flat=True)
        )
        faltan = [s for s in pasos if s not in visibles]
        if faltan:
            raise paquetes_mod.PaqueteInvalido("Alguno de los preajustes ya no existe.")
        paquetes_mod.validar_patron(patron)
        codigo = ""
        if crs_texto:
            try:
                codigo = crs_mod.validar_declarado(crs_texto).codigo
            except crs_mod.CrsInvalido as fallo:
                raise paquetes_mod.PaqueteInvalido(str(fallo)) from fallo
    except paquetes_mod.PaqueteInvalido as fallo:
        messages.error(request, str(fallo))
        return render(
            request,
            "presets/paquetes.html",
            _contexto_de_paquetes(
                request,
                escrito={"nombre": nombre, "patron": patron, "crs": crs_texto, "pasos": pasos},
            ),
        )
    PaqueteDeEntrega.objects.create(
        slug=_slug_libre(nombre),
        nombre=nombre,
        descripcion=(request.POST.get("descripcion") or "").strip()[:250],
        pasos=pasos,
        patron_de_nombre=patron,
        target_crs_code=codigo,
        owner=request.user,
    )
    messages.info(request, f"Paquete «{nombre}» guardado.")
    return redirect("presets:paquetes")


@login_required
@require_POST
def paquete_borrar(request, slug):
    # Solo los propios: el de otro es un 404, que no confirma que exista.
    paquete = get_object_or_404(PaqueteDeEntrega.propios_de(request.user), slug=slug)
    nombre = paquete.nombre
    paquete.delete()
    messages.info(request, f"Borrado el paquete «{nombre}».")
    return redirect("presets:paquetes")


@login_required
@require_POST
def lote_nuevo(request):
    """Aplica un paquete a la carpeta (o al archivo) elegida y lleva a la ficha del lote."""
    paquete = get_object_or_404(
        PaqueteDeEntrega.propios_de(request.user), slug=request.POST.get("paquete") or ""
    )
    ruta = (request.POST.get("ruta") or "").strip()
    if not ruta:
        messages.error(request, "Elija la carpeta con los archivos.")
        return redirect("presets:paquetes")
    try:
        resultado = aplicar_mod.aplicar_paquete(usuario=request.user, paquete=paquete, ruta=ruta)
    except paquetes_mod.PaqueteInvalido as fallo:
        messages.error(request, str(fallo))
        return redirect("presets:paquetes")
    return redirect("presets:lote", pk=resultado.lote.pk)


@login_required
def lote(request, pk):
    # Solo de quien lo pidió; el ajeno es un 404.
    objeto = get_object_or_404(LoteDeTrabajos.objects.filter(owner=request.user), pk=pk)
    trabajos = list(objeto.trabajos.order_by("source_name", "queued_at"))
    cuentas = objeto.cuentas()
    if not trabajos and not objeto.omitidos:
        raise Http404("El lote no tiene nada.")
    return render(
        request,
        "presets/lote.html",
        {
            "lote": objeto,
            "trabajos": trabajos,
            "cuentas": cuentas,
            "estado": objeto.estado,
            "omitidos": objeto.omitidos,
            "seccion": "preajustes",
            "etiqueta_seccion": "Preajustes",
            "titulo_pagina": f"Lote «{objeto.nombre}»",
            "proposito": "Cada archivo es un trabajo verificado; si falla uno, falla el lote.",
        },
    )
