"""Encadenar herramientas (F12.10): seguir con el resultado sin descargarlo y volver a subirlo.

Lo que se vigila es la puerta, no el adorno: `resultado:<id>` resuelve **solo** para quien pidió
el trabajo, **solo** si terminó, y nunca devuelve la ruta del servidor. Y el recorrido entero:
organizar un PDF, numerar el resultado y comprobar con otro lector el archivo que sale.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import quote

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from pypdf import PdfWriter

from apps.core import entrada
from apps.formats import pdf as lector
from apps.jobs import despachador
from apps.jobs.models import ERROR, ConversionJob

pytestmark = pytest.mark.django_db


def _pdf(carpeta, nombre, paginas=3):
    escritor = PdfWriter()
    for _ in range(paginas):
        escritor.add_blank_page(width=210 / lector.MM_POR_PUNTO, height=297 / lector.MM_POR_PUNTO)
    ruta = carpeta / nombre
    with open(ruta, "wb") as salida:
        escritor.write(salida)
    return ruta


@pytest.fixture
def ana(db):
    return get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106


@pytest.fixture
def beto(db):
    return get_user_model().objects.create_user("beto", password="x" * 20)  # nosec B106


@pytest.fixture
def entorno(tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    return tmp_path


@pytest.fixture
def sesion(client, ana, entorno):
    client.force_login(ana)
    return client


def _organizar(sesion, origen, receta="0:3:0,0:1:0,0:2:0"):
    """Corre «Organizar páginas» de verdad y devuelve el trabajo terminado."""
    respuesta = sesion.post(
        reverse("documents:componer_organizar"),
        {"archivos_texto": str(origen), "receta": receta, "accion": "generar"},
    )
    assert respuesta.status_code == 302, respuesta.content.decode()[:300]
    assert despachador.procesar_una_vez() == 1
    trabajo = ConversionJob.objects.get(herramienta="organizar")
    assert trabajo.status == "done", (trabajo.status, trabajo.reason_code)
    return trabajo


@pytest.fixture
def organizado(sesion, entorno):
    return _organizar(sesion, _pdf(entorno, "memoria.pdf"))


class TestLaPuertaDelResultado:
    def test_resuelve_el_resultado_de_quien_lo_pidio(self, organizado, ana):
        origen = entrada.resolver(f"resultado:{organizado.pk}", usuario=ana)
        assert str(origen.ruta) == organizado.output_path
        assert origen.nombre == "memoria_organizado.pdf"

    def test_el_token_es_el_identificador_y_nunca_la_ruta(self, organizado, ana):
        origen = entrada.resolver(f"resultado:{organizado.pk}", usuario=ana)
        assert origen.token == f"resultado:{organizado.pk}"
        assert str(origen.ruta) not in origen.token

    def test_el_de_otra_persona_no_resuelve_y_dice_lo_mismo_que_si_no_existiera(
        self, organizado, beto
    ):
        ajeno = None
        inexistente = None
        with pytest.raises(entrada.EntradaNoPermitida) as uno:
            entrada.resolver(f"resultado:{organizado.pk}", usuario=beto)
        ajeno = str(uno.value)
        with pytest.raises(entrada.EntradaNoPermitida) as otro:
            entrada.resolver("resultado:00000000-0000-0000-0000-000000000000", usuario=beto)
        inexistente = str(otro.value)
        assert ajeno == inexistente, "distinguirlos confirmaría que el identificador es válido"

    @pytest.mark.parametrize("basura", ["", "no-es-un-id", "../../etc/passwd", "1; DROP TABLE"])
    def test_un_identificador_malo_no_revienta(self, ana, basura):
        with pytest.raises(entrada.EntradaNoPermitida):
            entrada.resolver(f"resultado:{basura}", usuario=ana)

    def test_un_trabajo_que_no_termino_no_sirve_de_origen(self, organizado, ana):
        ConversionJob.objects.filter(pk=organizado.pk).update(status=ERROR)
        with pytest.raises(entrada.EntradaNoPermitida):
            entrada.resolver(f"resultado:{organizado.pk}", usuario=ana)

    def test_si_el_archivo_ya_no_esta_se_dice(self, organizado, ana):
        from pathlib import Path

        Path(organizado.output_path).unlink()
        with pytest.raises(entrada.EntradaNoPermitida, match="ya no está"):
            entrada.resolver(f"resultado:{organizado.pk}", usuario=ana)


class TestLaFicha:
    def test_un_pdf_terminado_ofrece_seguir_sin_descargarlo(self, sesion, organizado):
        cuerpo = sesion.get(reverse("jobs:ficha", args=[organizado.pk])).content.decode()
        assert "Seguir con este archivo" in cuerpo
        token = quote(f"resultado:{organizado.pk}")
        assert f"?ruta={token}" in cuerpo
        bloque = cuerpo[cuerpo.index('class="seguir-con"') :]
        bloque = bloque[: bloque.index("</nav>")]
        assert organizado.output_path not in bloque, "los enlaces no llevan la ruta del servidor"

    def test_ofrece_los_pasos_siguientes_y_no_repite_el_que_acaba_de_correr(
        self, sesion, organizado
    ):
        cuerpo = sesion.get(reverse("jobs:ficha", args=[organizado.pk])).content.decode()
        bloque = cuerpo[
            cuerpo.index('class="seguir-con"') : cuerpo.index(
                "</nav>", cuerpo.index('class="seguir-con"')
            )
        ]
        assert reverse("documents:numerar") in bloque
        assert reverse("documents:comprimir") in bloque
        assert reverse("documents:organizar") not in bloque

    def test_lo_que_no_es_un_pdf_no_ofrece_nada(self, sesion, organizado):
        ConversionJob.objects.filter(pk=organizado.pk).update(output_path="C:/x/salida.md")
        cuerpo = sesion.get(reverse("jobs:ficha", args=[organizado.pk])).content.decode()
        assert "Seguir con este archivo" not in cuerpo

    def test_el_fragmento_que_sondea_htmx_lo_lleva_tambien(self, sesion, organizado):
        cuerpo = sesion.get(reverse("jobs:progreso", args=[organizado.pk])).content.decode()
        assert "Seguir con este archivo" in cuerpo

    def test_la_ficha_de_otra_persona_es_un_404(self, client, organizado, beto):
        client.force_login(beto)
        assert client.get(reverse("jobs:ficha", args=[organizado.pk])).status_code == 404


class TestElRecorridoEntero:
    def test_organizar_luego_numerar_el_resultado(self, sesion, entorno, organizado):
        """Organizar (A4 x3 en otro orden) y numerar **lo que salió**, sin tocar el disco."""
        intermedio = organizado.output_path
        antes = hashlib.sha256(open(intermedio, "rb").read()).hexdigest()

        # La pantalla de la herramienta siguiente recibe el resultado por el enlace de la ficha.
        pantalla = sesion.get(reverse("documents:numerar"), {"ruta": f"resultado:{organizado.pk}"})
        assert pantalla.status_code == 200
        assert f"resultado:{organizado.pk}" in pantalla.content.decode()

        respuesta = sesion.post(
            reverse("documents:numerar"),
            {
                "ruta": f"resultado:{organizado.pk}",
                "accion": "numerar",
                "formato": "{n} / {total}",
                "posicion": "pie-derecha",
                "desde": "1",
                "empezar_en": "1",
            },
        )
        assert respuesta.status_code == 302, respuesta.content.decode()[:400]
        assert despachador.procesar_una_vez() == 1

        numerado = ConversionJob.objects.get(herramienta="numerar")
        assert numerado.status == "done", (numerado.status, numerado.reason_detail)
        assert lector.leer_cabecera(numerado.output_path).cuantas == 3
        # **El intermedio no se toca**: encadenar no es sobrescribir el paso anterior.
        assert hashlib.sha256(open(intermedio, "rb").read()).hexdigest() == antes

    def test_la_miniatura_acepta_el_resultado_y_solo_de_su_dueño(self, sesion, organizado, beto):
        url = reverse("documents:miniatura")
        token = f"resultado:{organizado.pk}"
        assert sesion.get(url, {"ruta": token, "pagina": 1}).status_code == 200

        from django.test import Client

        otro = Client()
        otro.force_login(beto)
        assert otro.get(url, {"ruta": token, "pagina": 1}).status_code == 400

    def test_una_pantalla_con_un_resultado_ajeno_no_lo_acepta(self, organizado, beto):
        from django.test import Client

        otro = Client()
        otro.force_login(beto)
        respuesta = otro.post(
            reverse("documents:numerar"),
            {
                "ruta": f"resultado:{organizado.pk}",
                "accion": "numerar",
                "formato": "{n}",
                "posicion": "pie-derecha",
                "desde": "1",
                "empezar_en": "1",
            },
        )
        assert respuesta.status_code in (200, 302)
        assert not ConversionJob.objects.filter(owner=beto).exists()
        assert not re.search(r"memoria_organizado", respuesta.content.decode())
