"""Ninguna petición sale del servidor (F19.5, D5): ni el HTML, ni el JavaScript, ni la CSP.

«Nada sale del equipo» es una promesa que se rompe con **una** línea: un `<img>` a un servidor de
teselas, un `fetch` a una dirección absoluta, un script de un CDN. Esta prueba lo mide donde se
puede sin navegador: lo que el servidor escribe en la página, lo que el JavaScript propio puede
pedir y lo que la política de seguridad deja pedir. Lo que el navegador **de verdad** pidió lo mide
el recorrido manual de `docs/PRUEBAS_CON_ORACULO.md` (pestaña de red), con fecha.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.urls import reverse

from apps.visor.testing import crear_vuelo_sintetico

pytestmark = pytest.mark.django_db

RAIZ = Path(__file__).resolve().parents[2]
JS = (RAIZ / "static" / "js" / "visor.js").read_text(encoding="utf-8")

#: Una dirección que sale del servidor: con esquema o con `//` delante de un nombre de equipo.
EXTERNA = re.compile(r"(?:https?:|wss?:|ftp:)?//[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}", re.I)
ESQUEMA = re.compile(r"\b(?:https?|wss?|ftp)://", re.I)


def _atributos_con_direccion(cuerpo: str) -> list[str]:
    """Los atributos que el navegador **pide**, con los `data-*` de direcciones del mapa. No
    `data-ruta`: es un archivo del disco que el servidor resuelve (en Windows, `C:\\...`)."""
    return re.findall(
        r'\b(?:src|href|action|poster|srcset|data-capa|data-teselas|data-punto|data-perfil)="([^"]*)"',
        cuerpo,
    )


def _sin_comentarios_de_js(texto: str) -> str:
    sin_bloques = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", sin_bloques)


@pytest.fixture
def pantallas(con_sesion, gdal_de_mentira, tif_de_obra, raiz_de_obra, persona, settings):
    """Todas las formas de la pantalla: elegir, con una imagen, con todas las capas y el fondo."""
    base = raiz_de_obra / "base.tif"
    base.write_bytes(b"II*\x00base")
    settings.VISOR_MAPA_BASE = f"Casa={base}"
    otra = raiz_de_obra / "otra.tif"
    otra.write_bytes(b"II*\x00otra")
    vuelo = crear_vuelo_sintetico(persona, raiz_de_obra / "salidas")
    inicio = reverse("visor:inicio")
    return {
        "elegir": con_sesion.get(inicio),
        "una imagen": con_sesion.get(inicio, {"ruta": str(tif_de_obra)}),
        "con todo": con_sesion.get(
            inicio, {"ruta": str(tif_de_obra), "capa": str(otra), "vuelo": str(vuelo.pk)}
        ),
        "solo vuelo": con_sesion.get(inicio, {"vuelo": str(vuelo.pk)}),
        "sin fondo": con_sesion.get(inicio, {"ruta": str(tif_de_obra), "fondo": "ninguno"}),
    }


class TestElHtml:
    def test_ninguna_pantalla_nombra_una_direccion_externa(self, pantallas):
        for nombre, respuesta in pantallas.items():
            assert respuesta.status_code == 200, nombre
            cuerpo = respuesta.content.decode()
            assert not ESQUEMA.search(cuerpo), f"{nombre}: {ESQUEMA.search(cuerpo)}"
            assert not EXTERNA.search(cuerpo), f"{nombre}: {EXTERNA.search(cuerpo)}"

    def test_toda_direccion_de_un_atributo_es_del_propio_servidor(self, pantallas):
        for nombre, respuesta in pantallas.items():
            for valor in _atributos_con_direccion(respuesta.content.decode()):
                partes = urlparse(valor.replace("&amp;", "&"))
                assert not partes.scheme and not partes.netloc, f"{nombre}: {valor}"
                assert not valor.startswith("//"), f"{nombre}: {valor}"

    def test_los_scripts_y_las_hojas_son_de_static(self, pantallas):
        for nombre, respuesta in pantallas.items():
            cuerpo = respuesta.content.decode()
            fuentes = re.findall(r'<script[^>]*\bsrc="([^"]+)"', cuerpo)
            hojas = re.findall(r'<link[^>]*\bhref="([^"]+)"', cuerpo)
            for fuente in [*fuentes, *hojas]:
                assert fuente.startswith("/static/") or fuente.startswith("/"), (
                    f"{nombre}: {fuente}"
                )
                assert "//" not in fuente.lstrip("/"), f"{nombre}: {fuente}"

    def test_la_direccion_de_las_teselas_es_la_del_servidor_y_no_lleva_el_fondo(self, pantallas):
        cuerpo = pantallas["con todo"].content.decode()
        assert 'data-teselas="/mapa/teselas/0/0/0.png"' in cuerpo
        # El navegador no sabe dónde está el fondo en el disco: solo su posición en la lista.
        assert "base.tif" not in cuerpo and "fondo:0" in cuerpo

    def test_la_plantilla_no_nombra_una_direccion_externa(self):
        html = (RAIZ / "templates" / "visor" / "inicio.html").read_text(encoding="utf-8")
        sin_comentarios = re.sub(
            r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", html, flags=re.S
        )
        assert not ESQUEMA.search(sin_comentarios) and not EXTERNA.search(sin_comentarios)


class TestElJavaScript:
    def test_no_nombra_ninguna_direccion_externa(self):
        codigo = _sin_comentarios_de_js(JS)
        assert not ESQUEMA.search(codigo), ESQUEMA.search(codigo)
        assert not EXTERNA.search(codigo), EXTERNA.search(codigo)

    @pytest.mark.parametrize(
        "prohibido",
        [
            "XMLHttpRequest",
            "WebSocket",
            "EventSource",
            "sendBeacon",
            "importScripts",
            "import(",
            "new Worker",
            "<iframe",
            'createElement("script")',
            'createElement("link")',
            'createElement("img")',
            "new Image(",
            'setAttribute("src"',
            ".innerHTML",
            "document.write",
        ],
    )
    def test_no_tiene_otro_camino_de_red_que_fetch(self, prohibido):
        assert prohibido not in _sin_comentarios_de_js(JS)

    def test_cada_fetch_pide_una_direccion_que_arma_del_servidor(self):
        """Los `fetch` de este archivo pueden pedir: la ficha de la capa y del vuelo, las teselas,
        el punto, el perfil y la ficha de la foto. Todas salen de `data-*` de la plantilla o de la
        respuesta del propio servidor; ninguna es una cadena escrita aquí."""
        codigo = _sin_comentarios_de_js(JS)
        primeros = re.findall(r"fetch\(\s*([^,)\s][^,)]*)", codigo)
        assert len(primeros) >= 5, primeros
        permitidos = (
            "direccion(",
            "url",
            "urlDelPerfil(",
            "raiz.dataset.",
            "urls.ficha",
        )
        for primero in primeros:
            assert primero.strip().startswith(permitidos), primero

    def test_las_direcciones_que_arma_empiezan_por_las_de_la_plantilla(self):
        codigo = _sin_comentarios_de_js(JS)
        assert "raiz.dataset.teselas" in codigo
        assert "raiz.dataset.capa" in codigo and "raiz.dataset.punto" in codigo
        assert "raiz.dataset.perfil" in codigo
        # Y al quitar una capa solo se navega dentro del propio sitio.
        assert "window.location.assign(url.pathname + url.search)" in codigo

    def test_las_imagenes_de_la_ficha_son_las_de_las_vistas_del_vuelo(self):
        codigo = _sin_comentarios_de_js(JS)
        assert 'urls.miniatura.replace("{n}"' in codigo


class TestLaPolitica:
    def test_la_csp_solo_deja_pedir_al_propio_servidor(self, pantallas):
        for nombre, respuesta in pantallas.items():
            csp = respuesta["Content-Security-Policy"]
            assert "default-src 'self'" in csp, nombre
            assert "connect-src 'self'" in csp, nombre
            assert "img-src 'self' data:" in csp, nombre
            assert "script-src 'self'" in csp, nombre
            assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0], nombre
            assert not ESQUEMA.search(csp) and "*" not in csp, f"{nombre}: {csp}"

    def test_ninguna_directiva_abre_un_origen_externo(self, pantallas):
        csp = pantallas["con todo"]["Content-Security-Policy"]
        for directiva in csp.split(";"):
            fuentes = directiva.split()[1:]
            for fuente in fuentes:
                assert fuente in ("'self'", "'none'", "data:", "'unsafe-inline'", "blob:") or (
                    fuente.startswith("'")
                ), f"{directiva.strip()}"

    def test_un_servidor_de_teselas_no_se_puede_configurar(self, settings, raiz_de_obra):
        from apps.visor import fondo

        for crudo in (
            "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            "//tile.example.org/{z}/{x}/{y}.png",
            "Mapa=https://example.org/mosaico.tif",
        ):
            settings.VISOR_MAPA_BASE = crudo
            assert all(not f.usable for f in fondo.configurados())
