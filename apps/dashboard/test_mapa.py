"""La retícula y la huella de la ficha (F13.11): SVG propio, sin biblioteca ni mapa base."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.dashboard import mapa
from apps.formats.tests.constructor import geotiff_minimo

pytestmark = pytest.mark.django_db

CAJA = ((-69.5, -23.4), (-69.4, -23.4), (-69.4, -23.5), (-69.5, -23.5))


class TestElDibujo:
    def test_el_poligono_tiene_cuatro_vertices_dentro_del_lienzo(self):
        d = mapa.dibujo(CAJA)
        puntos = [tuple(map(float, p.split(","))) for p in d["poligono"].split()]
        assert len(puntos) == 4
        for x, y in puntos:
            assert 0 <= x <= mapa.ANCHO and 0 <= y <= mapa.ALTO

    def test_el_norte_va_arriba_y_el_este_a_la_derecha(self):
        d = mapa.dibujo(CAJA)
        (x_no, y_no), (x_ne, _), (_, y_se), (x_so, _) = (
            tuple(map(float, p.split(","))) for p in d["poligono"].split()
        )
        assert x_ne > x_no == x_so
        assert y_no < y_se

    def test_hay_lineas_con_su_texto_en_grados(self):
        d = mapa.dibujo(CAJA)
        assert d["meridianos"] and d["paralelos"]
        assert all(re.fullmatch(r"[\d.]+° [EO]", m["texto"]) for m in d["meridianos"])
        assert all(re.fullmatch(r"[\d.]+° [NS]", p["texto"]) for p in d["paralelos"])

    def test_un_punto_sin_area_tambien_se_dibuja(self):
        d = mapa.dibujo(((-70.0, -23.0),) * 4)
        assert d["poligono"]


def test_la_ficha_pinta_la_huella_sin_pedir_nada_fuera(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    tif = tmp_path / "orto.tif"
    tif.write_bytes(geotiff_minimo())
    cuerpo = client.get(reverse("dashboard:inspeccionar"), {"ruta": str(tif)}).content.decode()
    assert 'class="mapa-svg"' in cuerpo and "mapa-huella" in cuerpo
    assert "Dónde está" in cuerpo and "Noroeste" in cuerpo
    # En español Django escribe 104,0: dentro del SVG tiene que ser 104.0 o no se dibuja.
    assert not re.search(r'(?:x|y|x1|x2|y1|y2|width|height)="[^"]*\d,\d', cuerpo)
    assert not re.search(r"https?://", cuerpo[cuerpo.index('class="mapa-svg"') :][:3000])


def test_sin_sistema_la_ficha_no_dibuja_nada(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    client.force_login(get_user_model().objects.create_user("ana", password="x" * 20))  # nosec B106
    tif = tmp_path / "sin.tif"
    tif.write_bytes(geotiff_minimo(epsg=None))
    cuerpo = client.get(reverse("dashboard:inspeccionar"), {"ruta": str(tif)}).content.decode()
    assert 'class="mapa-svg"' not in cuerpo


def test_ningun_script_de_mapas_en_el_proyecto():
    """D5: sin mapa base. Ni Leaflet, ni MapLibre, ni teselas en la plantilla ni en `static/js`."""
    raiz = Path(settings.BASE_DIR)
    for ruta in [
        *(raiz / "static" / "js").glob("*.js"),
        raiz / "templates" / "dashboard" / "_ficha.html",
    ]:
        texto = ruta.read_text(encoding="utf-8").lower()
        for palabra in ("leaflet", "maplibre", "openlayers", "tile.openstreetmap", "mapbox"):
            assert palabra not in texto, (ruta.name, palabra)
