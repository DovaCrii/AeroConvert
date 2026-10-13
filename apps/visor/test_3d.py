"""Piloto de globo 3D (F20.9): sesión, 403, la CSP de siempre, el SRI y que nada sale del servidor.

CesiumJS (`static/vendor/cesium/`) **no cambia la CSP**: medido en el navegador, el globo dibuja con
`script-src 'self'` a secas (ver `docs/INVESTIGACION_TOPOGRAFIA.md` §4). Aquí se vigila que nadie
la ensanche «para que funcione» y que el HTML, el JavaScript propio y la configuración no apunten a
Ion ni a ningún servidor de mapas. Lo que el navegador **de verdad** pidió (todas las peticiones, al
propio servidor) está medido con fecha en el documento de investigación.
"""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.jobs.models import HECHO, ConversionJob

pytestmark = pytest.mark.django_db

RAIZ = Path(__file__).resolve().parents[2]
VENDOR = RAIZ / "static" / "vendor" / "cesium"
JS = (RAIZ / "static" / "js" / "visor3d.js").read_text(encoding="utf-8")
PLANTILLA = RAIZ / "templates" / "visor" / "mapa_3d.html"

EXTERNA = re.compile(r"(?:https?:|wss?:|ftp:)?//[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}", re.I)
ESQUEMA = re.compile(r"\b(?:https?|wss?|ftp)://", re.I)


def _sin_comentarios(texto: str) -> str:
    sin_bloques = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", sin_bloques)


def _sri(ruta: Path) -> str:
    return "sha384-" + base64.b64encode(hashlib.sha384(ruta.read_bytes()).digest()).decode()


def _sin_comentarios_de_plantilla(html: str) -> str:
    return re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", html, flags=re.S)


class TestLaPantalla:
    def test_sin_sesion_es_302_a_la_entrada(self, client):
        respuesta = client.get(reverse("visor:mapa-3d"))
        assert respuesta.status_code == 302 and reverse("login") in respuesta["Location"]

    def test_es_de_solo_lectura(self, con_sesion):
        url = reverse("visor:mapa-3d")
        assert con_sesion.post(url).status_code == 405
        assert con_sesion.delete(url).status_code == 405

    def test_sin_imagen_dibuja_el_globo_y_ofrece_elegir(self, con_sesion, gdal_de_mentira):
        respuesta = con_sesion.get(reverse("visor:mapa-3d"))
        cuerpo = respuesta.content.decode()
        assert respuesta.status_code == 200
        assert 'id="globo-3d"' in cuerpo and "vendor/cesium/Cesium.js" in cuerpo
        assert 'data-capa3d="{}"' in cuerpo
        assert "¿Qué ortofoto o imagen georreferenciada?" in cuerpo

    def test_con_una_imagen_lleva_la_direccion_de_las_mismas_teselas(
        self, con_sesion, gdal_de_mentira, tif_de_obra
    ):
        respuesta = con_sesion.get(reverse("visor:mapa-3d"), {"ruta": str(tif_de_obra)})
        cuerpo = respuesta.content.decode()
        assert respuesta.status_code == 200
        assert "&quot;teselas&quot;: &quot;/mapa/teselas/0/0/0.png&quot;" in cuerpo
        assert "&quot;zoom_maximo&quot;" in cuerpo
        # El navegador pide la imagen por la ficha de la entrada, como el mapa plano.
        assert reverse("visor:inicio") + "?ruta=" in cuerpo

    def test_fuera_de_las_raices_es_403_con_su_codigo(
        self, con_sesion, gdal_de_mentira, raiz_de_obra, tmp_path
    ):
        ajeno = tmp_path / "ajeno" / "otra.tif"
        ajeno.parent.mkdir()
        ajeno.write_bytes(b"II*\x00ajeno")
        respuesta = con_sesion.get(reverse("visor:mapa-3d"), {"ruta": str(ajeno)})
        assert respuesta.status_code == 403
        assert "No se pudo abrir" in respuesta.content.decode()

    def test_el_resultado_de_otra_persona_es_403_y_no_confirma_que_exista(
        self, con_sesion, gdal_de_mentira, raiz_de_obra
    ):
        ajena = get_user_model().objects.create_user("beto")
        salida = raiz_de_obra / "salida.tif"
        salida.write_bytes(b"II*\x00" + b"x" * 50)
        trabajo = ConversionJob.objects.create(
            owner=ajena,
            source_name="x.tif",
            target_format_code="cog",
            status=HECHO,
            output_path=str(salida),
            finished_at=timezone.now(),
        )
        respuesta = con_sesion.get(reverse("visor:mapa-3d"), {"ruta": f"resultado:{trabajo.pk}"})
        cuerpo = respuesta.content.decode()
        assert respuesta.status_code == 403
        assert "No se pudo abrir" in cuerpo
        assert 'id="globo-3d"' not in cuerpo and "vendor/cesium/Cesium.js" not in cuerpo
        assert "salida.tif" not in cuerpo

    def test_sin_gdal_el_globo_se_ve_y_la_eleccion_dice_por_que_esta_apagada(
        self, con_sesion, monkeypatch
    ):
        from apps.engines.base import Disponibilidad
        from apps.visor import motor

        monkeypatch.setattr(
            motor,
            "disponibilidad",
            lambda: Disponibilidad.no("sin-gdal", "GDAL no está", sugerencia="Instale GDAL"),
        )
        respuesta = con_sesion.get(reverse("visor:mapa-3d"))
        cuerpo = respuesta.content.decode()
        assert respuesta.status_code == 200
        assert 'id="globo-3d"' in cuerpo
        assert "ahora mismo no se puede" in cuerpo


class TestLaCspNoSeEnsancha:
    #: La política de `apps/core/middleware.py`, escrita aquí a mano: si alguien ensancha la
    #: constante «para que funcione», esta prueba no lo sigue y falla.
    ESPERADA = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )

    def test_es_la_de_siempre_al_pie_de_la_letra(self, con_sesion, gdal_de_mentira):
        respuesta = con_sesion.get(reverse("visor:mapa-3d"))
        assert respuesta["Content-Security-Policy"] == self.ESPERADA

    def test_ni_eval_ni_inline_ni_workers_aparte(self, con_sesion, gdal_de_mentira):
        csp = con_sesion.get(reverse("visor:mapa-3d"))["Content-Security-Policy"]
        script = csp.split("script-src")[1].split(";")[0]
        assert "unsafe-eval" not in csp and "unsafe-inline" not in script
        assert "wasm-unsafe-eval" not in csp and "worker-src" not in csp
        assert "blob:" not in csp


class TestElSri:
    def test_el_integrity_de_la_plantilla_es_el_del_archivo(self):
        html = PLANTILLA.read_text(encoding="utf-8")
        parejas = 0
        for etiqueta in re.findall(r"<(?:link|script)\b[^>]*>", html, flags=re.S):
            integridad = re.search(r'integrity="(sha384-[^"]+)"', etiqueta)
            recurso = re.search(r"""\{%\s*static\s*['"]([^'"]+)['"]\s*%\}""", etiqueta)
            if integridad and recurso:
                parejas += 1
                ruta = RAIZ / "static" / recurso.group(1)
                assert _sri(ruta) == integridad.group(1), recurso.group(1)
        assert parejas == 2  # el motor y su hoja

    def test_la_bitacora_de_vendor_dice_lo_mismo_que_el_disco(self):
        """El `sha256` del README de `vendor/cesium/` es el del archivo, no uno copiado."""
        texto = (VENDOR / "README.md").read_text(encoding="utf-8")
        for nombre in (
            "Cesium.js",
            "Widgets/CesiumWidget/CesiumWidget.css",
            "Assets/approximateTerrainHeights.json",
        ):
            esperado = hashlib.sha256((VENDOR / nombre).read_bytes()).hexdigest()
            assert esperado in texto, nombre

    def test_viene_con_su_licencia(self):
        assert "Apache License" in (VENDOR / "LICENSE.md").read_text(encoding="utf-8")
        # Y los avisos de lo que el bundle trae de terceros.
        assert "Bundled license information" in (VENDOR / "Cesium.js.LEGAL.txt").read_text(
            encoding="utf-8"
        )
        assert (VENDOR / "ThirdParty.json").stat().st_size > 0

    def test_no_se_sirve_lo_que_no_se_usa(self):
        for sobra in (
            "Widgets/CesiumWidget/lighter.css",
            "Assets/Images/bing_maps_credit.png",
            "Assets/Images/google_earth_credit.png",
            "Assets/Images/cesium_credit.png",
        ):
            assert not (VENDOR / sobra).exists(), sobra
        assert not (VENDOR / "Assets" / "Textures").exists()
        # El logotipo que el widget pide en cada carga (`CreditDisplay`): sin él, un 404.
        assert (VENDOR / "Assets" / "Images" / "ion-credit.png").exists()

    #: Lo que el bundle puede contener de código dinámico o WebAssembly: **nada**. Si una versión
    #: nueva de Cesium trae algo, el nombre del módulo y la razón se anotan aquí y en el README.
    PERMITIDOS_EN_EL_BUNDLE: dict[str, int] = {}

    def test_el_bundle_no_trae_codigo_dinamico_ni_webassembly(self):
        texto = (VENDOR / "Cesium.js").read_text(encoding="utf-8")
        cuentas = {
            "new Function": texto.count("new Function"),
            "eval(": len(re.findall(r"(?<![\w.])eval\(", texto)),
            "WebAssembly.": texto.count("WebAssembly."),
            "\\0asm": texto.count("\\0asm"),
        }
        encontrados = {k: v for k, v in cuentas.items() if v}
        assert encontrados == self.PERMITIDOS_EN_EL_BUNDLE, encontrados

    def test_el_build_no_trae_el_worker_que_llama_a_new_function(self):
        assert not (VENDOR / "Workers" / "transcodeKTX2.js").exists()
        for worker in (VENDOR / "Workers").glob("*.js"):
            texto = worker.read_text(encoding="utf-8")
            assert "new Function" not in texto and "eval(" not in texto, worker.name


class TestNadaSaleDelServidor:
    def test_el_html_no_nombra_una_direccion_externa(
        self, con_sesion, gdal_de_mentira, tif_de_obra
    ):
        for parametros in ({}, {"ruta": str(tif_de_obra)}):
            cuerpo = con_sesion.get(reverse("visor:mapa-3d"), parametros).content.decode()
            assert not ESQUEMA.search(cuerpo), ESQUEMA.search(cuerpo)
            assert not EXTERNA.search(cuerpo), EXTERNA.search(cuerpo)

    def test_los_scripts_y_las_hojas_son_de_static(self, con_sesion, gdal_de_mentira, tif_de_obra):
        cuerpo = con_sesion.get(
            reverse("visor:mapa-3d"), {"ruta": str(tif_de_obra)}
        ).content.decode()
        fuentes = re.findall(r'<script[^>]*\bsrc="([^"]+)"', cuerpo)
        hojas = re.findall(r'<link[^>]*\bhref="([^"]+)"', cuerpo)
        assert "/static/vendor/cesium/Cesium.js" in fuentes
        assert "/static/js/visor3d.js" in fuentes
        for fuente in [*fuentes, *hojas]:
            assert fuente.startswith("/") and "//" not in fuente.lstrip("/"), fuente

    def test_la_plantilla_no_nombra_una_direccion_externa(self):
        html = _sin_comentarios_de_plantilla(PLANTILLA.read_text(encoding="utf-8"))
        assert not ESQUEMA.search(html) and not EXTERNA.search(html)

    def test_el_javascript_propio_no_nombra_una_direccion_externa(self):
        codigo = _sin_comentarios(JS)
        assert not ESQUEMA.search(codigo) and not EXTERNA.search(codigo)

    def test_el_javascript_no_tiene_otro_camino_de_red_ni_de_codigo_dinamico(self):
        codigo = _sin_comentarios(JS)
        for prohibido in (
            "fetch(",
            "XMLHttpRequest",
            "WebSocket",
            "EventSource",
            "sendBeacon",
            "importScripts",
            "import(",
            "new Worker",
            "eval(",
            "new Function",
            ".innerHTML",
            "document.write",
            "createWorldTerrain",
            "createWorldImagery",
            "IonImageryProvider",
            "IonResource",
            "BingMaps",
        ):
            assert prohibido not in codigo, prohibido

    def test_ion_queda_sin_token_y_sin_mapa_de_fondo_ni_selector(self):
        codigo = _sin_comentarios(JS)
        assert 'Ion.defaultAccessToken = ""' in codigo
        assert "baseLayer: false" in codigo
        assert "Geocoder" not in codigo and "BaseLayerPicker" not in codigo
        assert "buildModuleUrl.setBaseUrl(raiz.dataset.baseCesium)" in codigo

    def test_las_teselas_se_piden_a_la_direccion_de_la_plantilla(self):
        codigo = _sin_comentarios(JS)
        assert "capa.teselas.replace" in codigo
        assert '"{z}/{x}/{y}.png?ruta="' in codigo

    def test_la_configuracion_de_cesium_no_apunta_a_ion(self):
        """La base de Cesium es `static/` y nada nombra a Ion ni a su API, ni en la página, ni en el
        JavaScript propio, ni en lo que la vista le pasa a la plantilla."""
        html = _sin_comentarios_de_plantilla(PLANTILLA.read_text(encoding="utf-8"))
        assert "data-base-cesium=\"{% static 'vendor/cesium/' %}\"" in html
        for texto in (html, _sin_comentarios(JS)):
            for ion in ("ion.cesium", "api.cesium", "assets.ion", "cesium.com"):
                assert ion not in texto.lower(), ion
