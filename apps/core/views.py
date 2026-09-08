from django.http import JsonResponse


def salud(request):
    """Sonda de vida. La usa `run.ps1` para saber cuando abrir el navegador, en vez de
    dormir unos segundos y cruzar los dedos."""
    return JsonResponse({"estado": "ok"})
