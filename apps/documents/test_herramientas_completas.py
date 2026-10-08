"""Cada herramienta de documentos trae **todas** sus piezas.

Añadir una herramienta toca unas catorce cosas (el registro, la taxonomía, la cola, la pantalla, la
ruta, el icono, las pruebas…) y, repartidas en ocho archivos, siempre se olvida alguna: una sin
plantilla falla al abrirla, una sin especificación nunca corre, una sin icono sale con un hueco.
Esta prueba las recorre todas y dice **qué falta y en cuál**.

Es la lista de comprobación de la skill `/nueva-herramienta`, hecha ejecutable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from apps.dashboard import taxonomia
from apps.documents import motor, tarea
from apps.documents.herramientas import HERRAMIENTAS

RAIZ = Path(settings.BASE_DIR)
SPRITE = (RAIZ / "static" / "img" / "icons.svg").read_text(encoding="utf-8")
PRUEBAS = {
    p: p.read_text(encoding="utf-8") for p in (RAIZ / "apps").rglob("test_*.py") if p.is_file()
}

#: Las que no corren en `tarea.py`: su hijo es `pwsh` hablando con Office.
SIN_TAREA = {"office", "a_word"}

IDS = [h["id"] for h in HERRAMIENTAS]


def _por_id(id_: str) -> dict:
    return next(h for h in HERRAMIENTAS if h["id"] == id_)


@pytest.mark.parametrize("id_", IDS)
@pytest.mark.django_db
class TestPiezas:
    def test_tiene_los_campos_que_pinta_el_catalogo(self, id_):
        h = _por_id(id_)
        for campo in ("icono", "sale", "familia", "url", "nombre", "que_hace"):
            assert str(h.get(campo, "")).strip(), f"{id_}: falta «{campo}»"

    def test_su_icono_esta_en_el_sprite(self, id_):
        icono = _por_id(id_)["icono"]
        assert f'id="{icono}"' in SPRITE, f"{id_}: el icono «{icono}» no está en icons.svg"

    def test_tiene_grupo(self, id_):
        assert id_ in taxonomia.DE_DOCUMENTOS, f"{id_}: no está en taxonomia.DE_DOCUMENTOS"

    def test_la_cola_sabe_correrla(self, id_):
        assert id_ in motor.ESPECIFICACIONES, f"{id_}: falta su Especificacion en motor.py"
        if id_ not in SIN_TAREA:
            assert id_ in tarea.TAREAS, f"{id_}: falta su función en tarea.TAREAS"

    def test_su_pantalla_existe_y_pide_sesion(self, id_, client):
        url = _por_id(id_)["url"]
        respuesta = client.get(reverse(url))
        assert respuesta.status_code == 302, f"{id_}: «{url}» tiene que pedir sesión"

    def test_su_pantalla_abre_con_sesion(self, id_, client):
        # Es la prueba de que la plantilla existe y se pinta: un 500 aquí es una plantilla ausente.
        from django.contrib.auth import get_user_model

        client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
        url = _por_id(id_)["url"]
        assert client.get(reverse(url)).status_code == 200, f"{id_}: «{url}» no abre"

    def test_tiene_alguna_prueba_de_su_pantalla(self, id_):
        url = _por_id(id_)["url"]
        assert any(url in texto for texto in PRUEBAS.values()), (
            f"{id_}: ninguna prueba abre «{url}»"
        )


def test_no_hay_ids_repetidos():
    assert len(IDS) == len(set(IDS))
