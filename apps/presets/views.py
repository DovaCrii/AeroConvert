from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def lista(request):
    """Preajustes con nombre propio. Llegan en la fase F1.7."""
    return render(request, "presets/lista.html", {"preajustes": ()})
