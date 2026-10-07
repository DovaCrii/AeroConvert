"""Una página web guardada, a PDF (F14.20).

El oráculo es **`pypdf` leyendo el PDF** (otro lector que el que lo escribió): las palabras de la
página tienen que estar en el texto, y los scripts y estilos no.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from pypdf import PdfReader

from apps.documents import html_a_pdf, tarea

pytestmark = pytest.mark.django_db

PAGINA = """<!doctype html>
<html><head><meta charset="utf-8"><title>Informe</title>
<style>body { color: red; }</style>
<script>var secreto = "NO_DEBE_SALIR";</script></head>
<body>
<h1>Informe de obra</h1>
<p>El avance del mes fue <strong>notable</strong>.</p>
<ul><li>Excavación terminada</li><li>Fundaciones en curso</li></ul>
<table><tr><th>Partida</th><th>Avance</th></tr>
<tr><td>Excavación</td><td>100 %</td></tr></table>
</body></html>
"""


def _texto(ruta: Path) -> str:
    return " ".join(p.extract_text() or "" for p in PdfReader(str(ruta)).pages)


class TestConvertir:
    def test_el_texto_los_titulos_las_listas_y_las_tablas_estan_en_el_pdf(self, tmp_path):
        origen = tmp_path / "informe.html"
        origen.write_text(PAGINA, encoding="utf-8")
        destino = tmp_path / "informe.pdf"
        paginas = html_a_pdf.convertir(origen, destino)

        assert paginas >= 1
        texto = _texto(destino)
        for esperado in ("Informe de obra", "notable", "Fundaciones en curso", "Partida", "100"):
            assert esperado in texto, esperado

    def test_los_programas_y_los_estilos_no_salen(self, tmp_path):
        origen = tmp_path / "informe.html"
        origen.write_text(PAGINA, encoding="utf-8")
        destino = tmp_path / "informe.pdf"
        html_a_pdf.convertir(origen, destino)
        texto = _texto(destino)
        assert "NO_DEBE_SALIR" not in texto and "color: red" not in texto

    def test_una_pagina_sin_texto_se_dice(self, tmp_path):
        origen = tmp_path / "vacia.html"
        origen.write_text("<html><body><img src='x.png'><script>1</script></body></html>")
        with pytest.raises(html_a_pdf.PaginaSinTexto, match="no tiene texto"):
            html_a_pdf.convertir(origen, tmp_path / "x.pdf")

    def test_lo_que_no_es_una_pagina_se_rechaza(self, tmp_path):
        otro = tmp_path / "datos.csv"
        otro.write_text("a,b")
        with pytest.raises(html_a_pdf.ComposicionInvalida, match="no es una página web"):
            html_a_pdf.convertir(otro, tmp_path / "x.pdf")

    def test_el_original_no_se_toca(self, tmp_path):
        import hashlib

        origen = tmp_path / "informe.html"
        origen.write_text(PAGINA, encoding="utf-8")
        antes = (hashlib.sha256(origen.read_bytes()).hexdigest(), origen.stat().st_mtime_ns)
        html_a_pdf.convertir(origen, tmp_path / "informe.pdf")
        assert (hashlib.sha256(origen.read_bytes()).hexdigest(), origen.stat().st_mtime_ns) == antes


class TestEnLaTareaYLaPantalla:
    def test_la_tarea_convierte(self, tmp_path):
        origen = tmp_path / "informe.html"
        origen.write_text(PAGINA, encoding="utf-8")
        parcial = tmp_path / "salida.parcial"
        informe = tarea.ejecutar(
            "html_a_pdf", {"entradas": [{"ruta": str(origen)}], "opciones": {}}, parcial
        )
        assert "codigo" not in informe
        assert "Informe de obra" in _texto(parcial)

    def test_una_pagina_sin_texto_falla_con_su_codigo(self, tmp_path):
        origen = tmp_path / "vacia.html"
        origen.write_text("<html><body><script>1</script></body></html>")
        informe = tarea.ejecutar(
            "html_a_pdf",
            {"entradas": [{"ruta": str(origen)}], "opciones": {}},
            tmp_path / "salida.parcial",
        )
        assert informe["codigo"] == "documento-invalido"

    @pytest.fixture
    def sesion(self, client, tmp_path, settings):
        settings.RAICES_PERMITIDAS = str(tmp_path)
        settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
        client.force_login(
            get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        )
        return client

    def test_pide_sesion(self, client):
        assert client.get(reverse("documents:html_a_pdf")).status_code == 302

    def test_la_pantalla_dice_que_no_es_un_navegador(self, sesion):
        cuerpo = sesion.get(reverse("documents:html_a_pdf")).content.decode()
        assert "No es un navegador" in cuerpo

    def test_rechaza_lo_que_no_es_una_pagina_antes_de_encolar(self, sesion, tmp_path):
        otro = tmp_path / "datos.csv"
        otro.write_text("a,b")
        respuesta = sesion.post(reverse("documents:html_a_pdf"), {"ruta": str(otro)})
        assert respuesta.status_code == 200
        assert "no es una página web" in respuesta.content.decode()

    def test_convierte_encolando(self, sesion, tmp_path):
        from apps.jobs import despachador
        from apps.jobs.models import ConversionJob

        origen = tmp_path / "informe.html"
        origen.write_text(PAGINA, encoding="utf-8")
        respuesta = sesion.post(reverse("documents:html_a_pdf"), {"ruta": str(origen)})
        assert respuesta.status_code == 302 and "/trabajos/" in respuesta["Location"]
        assert despachador.procesar_una_vez() == 1
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.status == "done", trabajo.reason_detail
        assert "Informe de obra" in _texto(Path(trabajo.output_path))
