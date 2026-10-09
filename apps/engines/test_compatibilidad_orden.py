"""El orden de Compatibilidad: lo que falta primero, en una lista; lo fino, plegado.

En p340 (2026-10-09) la pantalla eran dos rejillas de tarjetas grandes (motores y documentos) y
pedía tres pantallas de desplazamiento antes de llegar a lo que funciona. Ahora lo apagado va en
una sola lista con «por qué» y «qué hace falta» escritos, lo que funciona en una línea por motor,
y la matriz y el historial plegados y recordados.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.documents.views import estado_de_herramientas


@pytest.fixture
def cuerpo(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("compat"))
    return client.get(reverse("engines:matriz")).content.decode()


def test_lo_que_falta_va_antes_que_lo_que_funciona(cuerpo):
    if 'class="faltas"' in cuerpo:
        assert cuerpo.index('class="faltas"') < cuerpo.index("Listas para usar")
    else:
        assert "Todo está encendido en este equipo" in cuerpo


def test_cada_apagada_dice_por_que_con_su_rotulo(cuerpo):
    apagadas = [d for d in estado_de_herramientas() if not d["disponible"]]
    assert cuerpo.count('<li class="falta">') >= len(apagadas)
    assert cuerpo.count('<span class="falta-rotulo">Por qué</span>') == cuerpo.count(
        '<li class="falta">'
    )


def test_la_matriz_y_el_historial_van_plegados_y_recordados(cuerpo):
    assert '<details class="grupo-herramientas" data-recuerda="compatibilidad-matriz">' in cuerpo
    # Plegada por omisión: nadie la abre para saber si algo funciona.
    assert 'data-recuerda="compatibilidad-matriz" open' not in cuerpo


def test_el_paso_a_paso_del_equipo_siempre_esta_enlazado(cuerpo):
    assert reverse("engines:equipo") in cuerpo
