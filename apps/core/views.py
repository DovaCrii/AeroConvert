import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.views.decorators.http import require_POST

from . import incidentes
from . import salud as salud_mod

#: Lo que cabe en un informe del navegador. Más que esto no es un informe: es otra cosa.
CUERPO_MAXIMO_DE_UN_INFORME = 2_048


def salud(request):
    """Sonda de vida. La usa `run.ps1` y el guion de despliegue para saber cuando el
    servicio esta arriba, en vez de dormir unos segundos y cruzar los dedos.

    Sin `login_required` **a proposito**: la comprueba un monitor, no una persona. Por eso
    tampoco sale de aqui ninguna ruta, ningun nombre de maquina ni ninguna version: solo
    booleanos, conteos y gigabytes. Lo que comprueba y lo que no, en `salud.py`.
    """
    parte = salud_mod.revisar()
    return JsonResponse(parte.a_json(), status=200 if parte.sirve else 503)


@login_required
@require_POST
def incidente_del_navegador(request):
    """El navegador avisa de que una petición de htmx falló (F9.6).

    Solo con sesión y solo por POST con el token de CSRF: nadie de fuera puede llenar la tabla.
    Se guarda dónde y con qué código, y **nada del contenido**. 204 siempre que el informe sea
    legible: lo que se haga con él no es asunto del navegador.
    """
    if len(request.body) > CUERPO_MAXIMO_DE_UN_INFORME:
        return HttpResponseBadRequest("Informe demasiado largo.")
    try:
        datos = json.loads(request.body or b"{}")
        ruta = str(datos["ruta"])
        estado = int(datos["estado"])
    except (ValueError, KeyError, TypeError):
        return HttpResponseBadRequest("Informe ilegible.")

    incidentes.registrar("navegador", ruta, estado=estado, usuario=request.user)
    return HttpResponse(status=204)
