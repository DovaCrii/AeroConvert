"""La mesa: soltar un archivo, ver que tiene dentro y que abre donde."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core import modo as modo_mod
from apps.formats import deteccion
from apps.targets import perfiles


@login_required
def mesa(request):
    return render(request, "dashboard/mesa.html", {"perfiles": perfiles.PERFILES.values()})


@login_required
def inspeccionar(request):
    """Inspecciona la ruta enviada y devuelve la ficha con sus veredictos.

    Responde un fragmento, no una pagina: htmx lo inserta bajo la zona de soltar. Y es una
    peticion aparte de la conversion a proposito -- inspeccionar es barato y no cambia
    nada, asi que puede pasar mientras la persona todavia decide.
    """
    ruta_pedida = (request.GET.get("ruta") or "").strip()
    if not ruta_pedida:
        return render(request, "dashboard/_ficha.html", {})

    try:
        ruta = modo_mod.comprobar_ruta(ruta_pedida)
    except modo_mod.RutaNoPermitida as fallo:
        return render(
            request,
            "dashboard/_ficha.html",
            {"error": str(fallo), "codigo_error": fallo.codigo},
        )

    try:
        inspeccion = deteccion.inspeccionar(ruta)
    except deteccion.OrigenIlegible as fallo:
        return render(
            request,
            "dashboard/_ficha.html",
            {"error": str(fallo), "codigo_error": fallo.codigo},
        )

    return render(
        request,
        "dashboard/_ficha.html",
        {"i": inspeccion, "veredictos": perfiles.veredictos(inspeccion)},
    )
