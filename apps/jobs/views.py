from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def lista(request):
    """El historial. Todavia vacio: el modelo de trabajo llega en la fase F1.2."""
    return render(request, "jobs/lista.html", {"trabajos": ()})
