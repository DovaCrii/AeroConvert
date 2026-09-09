"""La mesa: soltar un archivo, ver qué tiene dentro y qué abre dónde."""

from dataclasses import dataclass
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.core import modo as modo_mod
from apps.engines import formulario as formulario_mod
from apps.engines import registry
from apps.engines.base import ParDeFormatos
from apps.formats import catalogo, deteccion
from apps.jobs import estimacion as estimacion_mod
from apps.jobs.models import ConversionJob
from apps.presets.models import ConversionPreset
from apps.targets import perfiles as perfiles_mod


@dataclass(frozen=True)
class DestinoOfrecido:
    """Un perfil y si esta máquina puede cumplirlo ahora mismo.

    Se calcula contra la matriz de capacidades, no contra una lista fija: si falta la clave
    de ECW, el botón aparece **apagado con su motivo escrito y su alternativa**, no
    desaparece. Ocultarlo haría parecer que ese destino nunca existió.
    """

    perfil: perfiles_mod.PerfilDeDestino
    se_puede: bool
    nombre_destino: str = ""
    motivo: str = ""
    alternativas: tuple[str, ...] = ()
    estimacion: estimacion_mod.Estimacion | None = None


def _destinos_para(inspeccion) -> tuple[DestinoOfrecido, ...]:
    ofrecidos = []
    for perfil in perfiles_mod.PERFILES.values():
        destino = perfil.formato_destino
        formato = catalogo.FORMATOS.get(destino)
        celda = registry.celda(ParDeFormatos(inspeccion.codigo_formato, destino))

        estimada = None
        if celda.se_puede:
            estimada = estimacion_mod.estimar(
                inspeccion=inspeccion,
                formato_destino=destino,
                opciones=perfil.opciones,
            )

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
                estimacion=estimada,
            )
        )
    return tuple(ofrecidos)


def _formulario_experto(inspeccion, formato: str, valores: dict | None = None):
    """Los campos que el motor del par declara, o `None` si no hay motor.

    Se construye desde `opciones()` y no a mano: así el formulario no puede ofrecer un
    ajuste que el motor vaya a ignorar, que es exactamente el fallo silencioso que ya tuvo
    este proyecto con los perfiles de destino.
    """
    par = ParDeFormatos(inspeccion.codigo_formato, formato)
    motor = registry.motor_para(par)
    if motor is None:
        return None, None
    return motor, formulario_mod.construir(motor, par, valores)


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

    escribibles = catalogo.escribibles(inspeccion.familia or catalogo.RASTER)
    experto = (request.GET.get("formato") or "").strip()
    if experto not in {f.codigo for f in escribibles}:
        experto = escribibles[0].codigo if escribibles else ""

    _, campos = _formulario_experto(inspeccion, experto) if experto else (None, None)

    return render(
        request,
        "dashboard/_ficha.html",
        {
            "i": inspeccion,
            "veredictos": perfiles_mod.veredictos(inspeccion),
            "perfiles": _destinos_para(inspeccion),
            "escribibles": escribibles,
            "formato_experto": experto,
            "campos": campos,
            "preajustes": ConversionPreset.objects.filter(
                target_format_code__in=[f.codigo for f in escribibles]
            )[:12],
        },
    )


@login_required
def ajustes(request):
    """Los campos del modo experto para el formato elegido.

    Endpoint propio porque cambiar el formato de destino cambia los ajustes: JP2 tiene
    calidad y GeoTIFF tiene tamaño de tesela. htmx lo pide al cambiar el `<select>`.
    """
    inspeccion, error = _inspeccionar(request.GET.get("ruta") or "")
    if error:
        return render(request, "dashboard/_ajustes.html", {})

    formato = (request.GET.get("formato") or "").strip()
    if formato not in catalogo.FORMATOS:
        return render(request, "dashboard/_ajustes.html", {})

    _, campos = _formulario_experto(inspeccion, formato)
    return render(
        request,
        "dashboard/_ajustes.html",
        {"campos": campos, "formato_experto": formato, "i": inspeccion},
    )


def _inspeccionar(ruta_pedida: str):
    ruta_pedida = (ruta_pedida or "").strip()
    if not ruta_pedida:
        return None, {"error": "No se indicó ninguna ruta.", "codigo_error": "ruta-no-permitida"}
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

    try:
        formato, opciones, perfil_id, preajuste = _destino_pedido(request, inspeccion)
    except formulario_mod.OpcionInvalida as fallo:
        messages.error(request, fallo.mensaje)
        return redirect("dashboard:mesa")
    except ValueError as fallo:
        messages.error(request, str(fallo))
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
        target_profile_id=perfil_id,
        options=opciones,
        output_path=str(_ruta_de_salida(origen, formato, perfil_id)),
    )

    if preajuste is not None:
        preajuste.usar()
        job.registrar(f"Encolado con el preajuste «{preajuste.nombre}».")
    elif perfil_id:
        job.registrar(f"Encolado hacia {formato}. Perfil: {perfil_id}.")
    else:
        job.registrar(f"Encolado hacia {formato} con ajustes a mano.")

    return redirect("jobs:ficha", pk=job.pk)


def _destino_pedido(request, inspeccion):
    """Qué conversión se pidió: por preajuste, por perfil, o a mano.

    Los tres caminos acaban en lo mismo -- un formato y un diccionario de opciones -- y se
    resuelven aquí para que la vista no tenga tres ramas con el mismo `create()` al final.
    """
    slug = (request.POST.get("preajuste") or "").strip()
    if slug:
        preajuste = ConversionPreset.objects.filter(slug=slug).first()
        if preajuste is None:
            raise ValueError("Ese preajuste ya no existe.")
        return (
            preajuste.target_format_code,
            dict(preajuste.options),
            preajuste.target_profile_id,
            preajuste,
        )

    identificador = (request.POST.get("perfil") or "").strip()
    perfil = perfiles_mod.PERFILES.get(identificador)
    if perfil is not None:
        return perfil.formato_destino, dict(perfil.opciones), identificador, None

    formato = (request.POST.get("formato") or "").strip()
    if formato not in catalogo.FORMATOS:
        raise ValueError("Ese formato de destino no existe.")

    par = ParDeFormatos(inspeccion.codigo_formato, formato)
    motor = registry.motor_para(par)
    if motor is None:
        celda = registry.celda(par)
        raise ValueError(celda.mensaje or "Ningún motor sabe hacer esa conversión.")

    return formato, formulario_mod.leer(motor, par, request.POST), "", None


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
