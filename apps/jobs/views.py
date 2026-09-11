import logging
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import retencion
from .models import ERROR, TERMINALES, ConversionJob

registro = logging.getLogger(__name__)


def _mio(request, pk) -> ConversionJob:
    """El trabajo, si es de quien pregunta.

    `get_object_or_404` filtrando por `owner` y no una comprobacion aparte: asi el trabajo
    de otro devuelve 404 y no 403, que ademas de correcto no confirma que exista.
    """
    return get_object_or_404(ConversionJob, pk=pk, owner=request.user)


@login_required
def lista(request):
    trabajos = ConversionJob.objects.filter(owner=request.user)[:100]
    return render(
        request,
        "jobs/lista.html",
        {
            "trabajos": trabajos,
            "seccion": "historial",
            "etiqueta_seccion": "Historial",
            "titulo_pagina": "Lo que has convertido",
            "proposito": (
                "Cada conversión queda registrada con su recibo: qué entró, qué salió, con "
                "qué motor y si se verificó. El recibo sobrevive aunque el archivo ya se "
                "haya borrado."
            ),
        },
    )


def _alternativas(job: ConversionJob) -> tuple[dict, ...]:
    """Los formatos que sí se pueden, cuando el pedido no se pudo.

    Cuando algo falla por falta de una herramienta, la respuesta útil no es «no»: es «no, y
    esto sí». Las alternativas las declara el propio motor en su `Disponibilidad`, así que
    salen de la matriz de capacidades y no de una lista escrita a mano aquí.
    """
    from apps.engines import registry
    from apps.engines.base import ParDeFormatos
    from apps.formats import catalogo

    if job.status != ERROR or not job.source_format_code:
        return ()

    celda = registry.celda(ParDeFormatos(job.source_format_code, job.target_format_code))
    salida = []
    for codigo in celda.alternativas:
        formato = catalogo.FORMATOS.get(codigo)
        if formato is None:
            continue
        # Se ofrece solo lo que de verdad se puede hacer ahora. Proponer una alternativa
        # que tambien falla es peor que no proponer nada.
        if registry.celda(ParDeFormatos(job.source_format_code, codigo)).se_puede:
            salida.append({"codigo": codigo, "nombre": formato.nombre})
    return tuple(salida)


@login_required
def ficha(request, pk):
    job = _mio(request, pk)
    return render(request, "jobs/ficha.html", {"trabajo": job, "alternativas": _alternativas(job)})


@login_required
def progreso(request, pk):
    """El fragmento que sondea htmx.

    Una consulta indexada y un fragmento pequeno. El sondeo se detiene solo porque la
    plantilla omite el `hx-trigger` cuando el trabajo es terminal.
    """
    job = _mio(request, pk)
    return render(
        request, "jobs/_progreso.html", {"trabajo": job, "alternativas": _alternativas(job)}
    )


@login_required
@require_POST
def cancelar(request, pk):
    """Pide la cancelacion. **No mata nada desde aqui.**

    El runner mira este campo en cada latido y se encarga de matar al hijo y borrar el
    parcial. Matar el proceso desde la vista dejaria el trabajo en `ejecutando` para
    siempre y el parcial en el disco.
    """
    job = _mio(request, pk)
    if job.status in TERMINALES:
        messages.info(request, "Ese trabajo ya había terminado.")
    else:
        ConversionJob.objects.filter(pk=job.pk).update(cancel_requested_at=timezone.now())
        job.registrar("Cancelación pedida.", nivel="warn")
        messages.info(request, "Cancelando. Puede tardar unos segundos en detenerse.")
    return redirect("jobs:ficha", pk=job.pk)


@login_required
@require_POST
def reencolar(request, pk):
    """Crea una fila nueva a partir de una anterior.

    Nueva y no un contador que se incrementa: asi no se pierde con qué motor falló, con qué
    versión, ni cuánto tardó en fallar. `retry_of` conserva el hilo.
    """
    anterior = _mio(request, pk)
    formato = (request.POST.get("formato") or anterior.target_format_code).strip()

    nuevo = ConversionJob.objects.create(
        owner=request.user,
        source_path=anterior.source_path,
        source_name=anterior.source_name,
        source_size_bytes=anterior.source_size_bytes,
        source_format_code=anterior.source_format_code,
        target_format_code=formato,
        target_profile_id=anterior.target_profile_id
        if formato == anterior.target_format_code
        else "",
        options=anterior.options if formato == anterior.target_format_code else {},
        output_path=anterior.output_path,
        retry_of=anterior,
        max_attempts=anterior.max_attempts,
    )
    nuevo.registrar(f"Reencolado desde {anterior.pk} hacia {formato}.")
    return redirect("jobs:ficha", pk=nuevo.pk)


class RespuestaQueConsume(FileResponse):
    """Sirve el archivo y lo borra en cuanto termina de enviarse.

    El borrado va **despues** de que la respuesta se cierre, no antes de empezar: si la
    descarga se corta a la mitad -- y con archivos de cientos de megabytes se corta -- la
    persona tiene que poder reintentarla. Borrar al empezar convertiria un corte de red en
    una perdida del entregable.
    """

    def __init__(self, *args, job=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._job = job
        self._completada = False

    def close(self):
        super().close()
        if self._job is not None and self._completada:
            retencion.consumir(self._job)


def _ya_no_esta(request, job, motivo: str):
    """La salida se fue, pero el recibo sigue. **410 y no 404**, y con su propia pagina.

    Un 404 dice «esto nunca existio». Aqui existio, se verifico, y desaparecio por una razon
    que sabemos nombrar — y en una carpeta compartida ese camino no es raro: cualquiera puede
    mover el archivo desde su Explorador.

    Lo que se ensena es el recibo entero y un boton para rehacerla. Eso es lo que significa
    la promesa de que **el recibo sobrevive al archivo**.
    """
    return render(
        request,
        "jobs/caducado.html",
        {
            "trabajo": job,
            "motivo": motivo,
            "carpeta": Path(job.output_path).parent.name if job.output_path else "",
            "seccion": "historial",
            "etiqueta_seccion": "Historial",
            "titulo_pagina": "Ese archivo ya no está",
        },
        status=410,
    )


@login_required
def descargar(request, pk):
    """Entrega la salida. Con politica efimera, esta es su ultima oportunidad."""
    job = _mio(request, pk)
    if not job.output_path:
        registro.info("Descarga de %s sin salida: la retencion ya se la llevo.", job.pk)
        return _ya_no_esta(request, job, "barrida")

    ruta = Path(job.output_path)
    if not ruta.exists():
        registro.warning("La salida de %s no esta en su sitio.", job.pk)
        return _ya_no_esta(request, job, "desaparecida")

    # **Que lo que hay ahi siga siendo lo que produjo este trabajo.** `_destino_libre()` en
    # el runner impide que otra persona escriba encima, pero nada impide que alguien
    # reemplace el archivo desde la carpeta compartida con el Explorador. Entregar entonces
    # lo que haya, con el nombre y el recibo de este trabajo, seria entregar otra cosa
    # diciendo que es esta.
    if job.output_size_bytes and ruta.stat().st_size != job.output_size_bytes:
        registro.warning("La salida de %s cambio de tamano: alguien la reemplazo.", job.pk)
        return _ya_no_esta(request, job, "reemplazada")

    respuesta = RespuestaQueConsume(
        open(ruta, "rb"),  # noqa: SIM115 - FileResponse se encarga de cerrarlo
        as_attachment=True,
        filename=ruta.name,
        job=job,
    )
    respuesta._completada = True
    return respuesta
