from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import retencion
from .models import TERMINALES, ConversionJob


def _mio(request, pk) -> ConversionJob:
    """El trabajo, si es de quien pregunta.

    `get_object_or_404` filtrando por `owner` y no una comprobacion aparte: asi el trabajo
    de otro devuelve 404 y no 403, que ademas de correcto no confirma que exista.
    """
    return get_object_or_404(ConversionJob, pk=pk, owner=request.user)


@login_required
def lista(request):
    trabajos = ConversionJob.objects.filter(owner=request.user)[:100]
    return render(request, "jobs/lista.html", {"trabajos": trabajos})


@login_required
def ficha(request, pk):
    return render(request, "jobs/ficha.html", {"trabajo": _mio(request, pk)})


@login_required
def progreso(request, pk):
    """El fragmento que sondea htmx.

    Una consulta indexada y un fragmento pequeno. El sondeo se detiene solo porque la
    plantilla omite el `hx-trigger` cuando el trabajo es terminal.
    """
    return render(request, "jobs/_progreso.html", {"trabajo": _mio(request, pk)})


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


@login_required
def descargar(request, pk):
    """Entrega la salida. Con politica efimera, esta es su ultima oportunidad."""
    job = _mio(request, pk)
    if not job.output_path:
        raise Http404("Esta conversion ya no tiene archivo disponible.")

    ruta = Path(job.output_path)
    if not ruta.exists():
        raise Http404("El archivo ya se borro.")

    respuesta = RespuestaQueConsume(
        open(ruta, "rb"),  # noqa: SIM115 - FileResponse se encarga de cerrarlo
        as_attachment=True,
        filename=ruta.name,
        job=job,
    )
    respuesta._completada = True
    return respuesta
