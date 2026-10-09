"""El lateral cuenta lo mismo que enseña.

En p340 (2026-10-09) «Imagen, video y planta» decía 2 y enseñaba 1: la cifra contaba también la
herramienta apagada, que el lateral no pinta. Ahora el procesador deja en cada grupo solo las
disponibles, y un grupo sin ninguna desaparece del menú (sigue, con su motivo, en la portada).
"""

from __future__ import annotations

from types import SimpleNamespace

from django.test import RequestFactory

from apps.core import context_processors
from apps.dashboard import acciones as acciones_mod


def _grupo(clave, *disponibles):
    return {
        "clave": clave,
        "titulo": clave,
        "cuando": "",
        "icono": "icon-todas",
        "seccion": "",
        "acciones": [
            SimpleNamespace(nombre=f"{clave}{i}", disponible=d) for i, d in enumerate(disponibles)
        ],
    }


def _peticion():
    peticion = RequestFactory().get("/")
    peticion.user = SimpleNamespace(is_authenticated=True)
    return peticion


def test_cuenta_solo_las_disponibles(monkeypatch):
    monkeypatch.setattr(
        acciones_mod, "por_categoria", lambda: [_grupo("planta", True, False), _grupo("gnss", True)]
    )
    grupos = context_processors.menu(_peticion())["menu_grupos"]
    assert [len(g["acciones"]) for g in grupos] == [1, 1]
    assert all(a.disponible for g in grupos for a in g["acciones"])


def test_un_grupo_sin_ninguna_disponible_no_sale(monkeypatch):
    monkeypatch.setattr(
        acciones_mod,
        "por_categoria",
        lambda: [_grupo("planta", False, False), _grupo("gnss", True)],
    )
    grupos = context_processors.menu(_peticion())["menu_grupos"]
    assert [g["clave"] for g in grupos] == ["gnss"]


def test_la_herramienta_donde_se_esta_queda_marcada(client, django_user_model):
    """Antes solo el ratón encima resaltaba la herramienta; ahora la página actual lleva
    `aria-current` y su grupo se abre (`plegable.js`)."""
    import re

    from django.urls import reverse

    client.force_login(django_user_model.objects.create_user("lateral"))
    url = reverse("documents:vuelo_dron")
    html = client.get(url).content.decode()
    marcados = re.findall(r'<a href="([^"]+)" class="menu-enlace"\s+aria-current="page"', html)
    assert marcados == [url]
    # La chapa del modo lleva su símbolo, en la barra y al pie del lateral.
    assert html.count('class="chapa-icono"') == 2


def test_quien_no_ha_entrado_no_recibe_menu():
    peticion = RequestFactory().get("/")
    peticion.user = SimpleNamespace(is_authenticated=False)
    assert context_processors.menu(peticion) == {}
