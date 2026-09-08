"""La mesa: soltar un archivo, ver qué tiene dentro y qué abre dónde."""

from dataclasses import dataclass
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.core import modo as modo_mod
from apps.engines import registry
from apps.engines.base import ParDeFormatos
from apps.formats import catalogo, deteccion
from apps.jobs.models import ConversionJob
from apps.targets import perfiles as perfiles_mod


@dataclass(frozen=True)
class DestinoOfrecido:
    """Un perfil y si esta maquina puede cumplirlo ahora mismo.

    Se calcula contra la matriz de capacidades, no contra una lista fija: si falta la clave
    de ECW, el botón aparece **apagado con su motivo escrito y su alternativa**, no
    desaparece. Ocultarlo haría parecer que ese destino nunca existió.
    """

    perfil: perfiles_mod.PerfilDeDestino
    se_puede: bool
    nombre_destino: str = ""
    motivo: str = ""
    alternativas: tuple[str, ...] = ()


def _destinos_para(codigo_origen: str) -> tuple[DestinoOfrecido, ...]:
    ofrecidos = []
    for perfil in perfiles_mod.PERFILES.values():
        destino = perfil.formato_destino
        formato = catalogo.FORMATOS.get(destino)
        celda = registry.celda(ParDeFormatos(codigo_origen, destino))
        ofrecidos.append(
            DestinoOfrecido(
                perfil=perfil,
                se_puede=celda.se_puede,
                nombre_destino=formato.nombre if formato else destino,
                motivo=celda.mensaje,
                alternativas=tuple(
                    catalogo.FORMATOS[a].nombre
                    for a in celda.alternativas
                    if a in catalogo.FORMATOS
                ),
            )
        )
    return tuple(ofrecidos)


@login_required
def mesa(request):
    return render(request, "dashboard/mesa.html", {})


@login_required
def inspeccionar(request):
    """Inspecciona la ruta enviada y devuelve la ficha con sus veredictos.

    Responde un fragmento, no una página: htmx lo inserta bajo la zona de soltar. Y es una
    petición aparte de la conversión a propósito — inspeccionar es barato y no cambia nada,
    así que puede pasar mientras la persona todavía decide.
    """
    ruta_pedida = (request.GET.get("ruta") or "").strip()
    if not ruta_pedida:
        return render(request, "dashboard/_ficha.html", {})

    inspeccion, error = _inspeccionar(ruta_pedida)
    if error:
        return render(request, "dashboard/_ficha.html", error)

    return render(
        request,
        "dashboard/_ficha.html",
        {
            "i": inspeccion,
            "veredictos": perfiles_mod.veredictos(inspeccion),
            "perfiles": _destinos_para(inspeccion.codigo_formato),
            "escribibles": catalogo.escribibles(inspeccion.familia or catalogo.RASTER),
        },
    )


def _inspeccionar(ruta_pedida: str):
    try:
        ruta = modo_mod.comprobar_ruta(ruta_pedida)
    except modo_mod.RutaNoPermitida as fallo:
        return None, {"error": str(fallo), "codigo_error": fallo.codigo}

    try:
        return deteccion.inspeccionar(ruta), None
    except deteccion.OrigenIlegible as fallo:
        return None, {"error": str(fallo), "codigo_error": fallo.codigo}


@login_required
@require_POST
def convertir(request):
    """Encola el trabajo y lleva a su ficha.

    No convierte aquí: encola. La conversión la hace el despachador en un proceso hijo, y
    esta vista tiene que devolver en milisegundos — si esperara, el navegador agotaría el
    tiempo en cualquier archivo de verdad.
    """
    inspeccion, error = _inspeccionar(request.POST.get("ruta") or "")
    if error:
        messages.error(request, error["error"])
        return redirect("dashboard:mesa")

    identificador = (request.POST.get("perfil") or "").strip()
    perfil = perfiles_mod.PERFILES.get(identificador)

    if perfil is not None:
        formato = perfil.formato_destino
        opciones = dict(perfil.opciones)
    else:
        formato = (request.POST.get("formato") or "").strip()
        opciones = {}
        if formato not in catalogo.FORMATOS:
            messages.error(request, "Ese formato de destino no existe.")
            return redirect("dashboard:mesa")

    origen = Path(inspeccion.ruta)
    job = ConversionJob.objects.create(
        owner=request.user,
        source_path=str(origen),
        source_name=origen.name,
        source_size_bytes=inspeccion.bytes_totales,
        source_format_code=inspeccion.codigo_formato,
        source_format_confidence=inspeccion.confianza,
        source_crs_authority=inspeccion.crs.autoridad,
        source_crs_code=inspeccion.crs.codigo,
        source_crs_origin=inspeccion.crs.origen,
        target_format_code=formato,
        target_profile_id=identificador,
        options=opciones,
        output_path=str(_ruta_de_salida(origen, formato, identificador)),
    )
    job.registrar(f"Encolado hacia {formato}." + (f" Perfil: {identificador}." if perfil else ""))
    return redirect("jobs:ficha", pk=job.pk)


def _ruta_de_salida(origen: Path, formato: str, perfil_id: str) -> Path:
    """Dónde se escribe el resultado.

    En taller, junto al original y con un sufijo que dice para qué es. Se prefiere eso a una
    carpeta aparte porque quien convierte una ortofoto la quiere al lado de su entregable,
    no perdida en un directorio de la aplicación.
    """
    definicion = catalogo.FORMATOS.get(formato)
    extension = sorted(definicion.extensiones)[0] if definicion else ".out"
    sufijo = perfil_id or formato
    if modo_mod.es_taller():
        return origen.with_name(f"{origen.stem}_{sufijo}{extension}")

    from apps.jobs import retencion

    return retencion.carpeta_de_trabajo() / f"{origen.stem}_{sufijo}{extension}"
