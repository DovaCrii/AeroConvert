from django.http import JsonResponse

from . import salud as salud_mod


def salud(request):
    """Sonda de vida. La usa `run.ps1` y el guion de despliegue para saber cuando el
    servicio esta arriba, en vez de dormir unos segundos y cruzar los dedos.

    Sin `login_required` **a proposito**: la comprueba un monitor, no una persona. Por eso
    tampoco sale de aqui ninguna ruta, ningun nombre de maquina ni ninguna version: solo
    booleanos, conteos y gigabytes. Lo que comprueba y lo que no, en `salud.py`.
    """
    parte = salud_mod.revisar()
    return JsonResponse(parte.a_json(), status=200 if parte.sirve else 503)
