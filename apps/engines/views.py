from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from . import registry


@login_required
def matriz(request):
    """La rejilla origen x destino. Es la pantalla que se mira antes de escribir a
    soporte, asi que cada celda apagada lleva su motivo y su alternativa."""
    return render(
        request,
        "engines/matriz.html",
        {"celdas": registry.matriz_de_capacidades().values(), "motores": registry.todos()},
    )
