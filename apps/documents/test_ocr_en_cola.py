"""Reconocer el texto por la cola: lo que dentro de la petición moría a los 120 s.

## El fallo que esto arregla

gunicorn corta una petición a los 120 s, y el reconocimiento tarda de dos a cinco segundos
por página. Así que un escaneo de cuarenta páginas **moría a medias sin decir nada**: la
pantalla se quedaba cargando y luego daba un error del servidor. El tope de 100 páginas no
era el límite de verdad; el de verdad era el plazo.

## Lo que se puede comprobar aquí

Tesseract no está en esta estación. Las pruebas de la pantalla y del hijo lo sustituyen por
un programa de mentira que escribe lo que escribiría él —un PDF de una página por imagen—;
lo que se vigila es todo lo que rodea al reconocimiento. **La de extremo a extremo necesita
el programa de verdad** y se salta sola aquí, diciéndolo: tiene que correr en p340.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from apps.documents import motor, ocr, tarea
from apps.jobs.models import ConversionJob, EntradaDeTrabajo

pytestmark = pytest.mark.django_db

hay_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="Tesseract no está en esta máquina: esta prueba tiene que correr en p340",
)


def _pdf(ruta: Path, paginas: int = 3) -> Path:
    hoja = canvas.Canvas(str(ruta), pagesize=A4)
    for _ in range(paginas):
        hoja.rect(50, 50, 400, 600)  # una página «escaneada»: dibujo, ningún texto
        hoja.showPage()
    hoja.save()
    return ruta


@pytest.fixture
def entorno(tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    return tmp_path


@pytest.fixture
def sesion(client, entorno):
    client.force_login(
        get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    )
    return client


@pytest.fixture
def con_tesseract(monkeypatch):
    """Que la sonda diga que está, con español instalado y sin inglés."""
    estado = ocr.Disponible(programa="tesseract-falso", idiomas=frozenset({"spa"}))
    monkeypatch.setattr(ocr, "sondar", lambda **_: estado)
    return estado


@pytest.fixture
def tesseract_falso(monkeypatch):
    """Escribe lo que escribiría Tesseract: `<base>.pdf` con una página y su texto."""
    llamadas = []

    def correr(argv, **_):
        llamadas.append(argv)
        base = Path(argv[2])
        hoja = canvas.Canvas(str(base.with_suffix(".pdf")), pagesize=A4)
        hoja.drawString(72, 720, "ACTA DE RECEPCION")
        hoja.showPage()
        hoja.save()
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(ocr.subprocess, "run", correr)
    return llamadas


class TestLaPantalla:
    def test_mirar_dice_cuantas_paginas_y_cuanto_tardara(self, sesion, entorno, con_tesseract):
        """Con quinientas páginas son cuarenta minutos: se dice **antes** de pulsar."""
        escaneo = _pdf(entorno / "escaneo.pdf", 3)
        cuerpo = sesion.post(
            reverse("documents:ocr"), {"ruta": str(escaneo), "accion": "mirar"}
        ).content.decode()
        assert "3</span> página(s)" in cuerpo
        assert "menos de un minuto" in cuerpo
        assert "puedes cerrar esta pestaña" in cuerpo

    def test_reconocer_encola_en_el_carril_pesado(self, sesion, entorno, con_tesseract):
        escaneo = _pdf(entorno / "escaneo.pdf", 3)
        respuesta = sesion.post(
            reverse("documents:ocr"),
            {"ruta": str(escaneo), "accion": "reconocer", "idioma": "spa"},
        )
        assert respuesta.status_code == 302
        trabajo = ConversionJob.objects.get()
        assert trabajo.herramienta == "ocr"
        assert trabajo.options == {"idioma": "spa", "paginas": 3}
        assert trabajo.output_path == str(entorno / "escaneo_con_texto.pdf")
        assert motor.carril_de(trabajo.herramienta) == "pesado"

    def test_pasado_el_tope_el_boton_sale_apagado_con_el_motivo(
        self, sesion, entorno, con_tesseract, monkeypatch
    ):
        """Apagado y con el motivo, no escondido. Y si se fuerza el POST, no encola."""
        monkeypatch.setattr(ocr, "TOPE_PAGINAS", 2)
        escaneo = _pdf(entorno / "escaneo.pdf", 3)
        mirar = sesion.post(
            reverse("documents:ocr"), {"ruta": str(escaneo), "accion": "mirar"}
        ).content.decode()
        assert 'disabled aria-describedby="motivo-tope"' in mirar
        assert 'id="motivo-tope"' in mirar

        forzado = sesion.post(
            reverse("documents:ocr"),
            {"ruta": str(escaneo), "accion": "reconocer", "idioma": "spa"},
        )
        assert forzado.status_code == 200
        assert "Dividir PDF" in forzado.content.decode()
        assert not ConversionJob.objects.exists()

    def test_un_idioma_que_falta_se_dice_en_la_pantalla(self, sesion, entorno, con_tesseract):
        escaneo = _pdf(entorno / "escaneo.pdf", 1)
        respuesta = sesion.post(
            reverse("documents:ocr"),
            {"ruta": str(escaneo), "accion": "reconocer", "idioma": "eng"},
        )
        assert respuesta.status_code == 200
        assert "no tiene instalado" in respuesta.content.decode()
        assert not ConversionJob.objects.exists()

    def test_la_ficha_recuerda_repasar_el_texto(self, sesion, entorno):
        trabajo = ConversionJob.objects.create(
            owner=get_user_model().objects.get(username="topografo"),
            herramienta="ocr",
            source_name="escaneo.pdf",
            source_path=str(entorno / "escaneo.pdf"),
            target_format_code="doc:ocr",
            status="done",
            output_path=str(_pdf(entorno / "escaneo_con_texto.pdf", 1)),
        )
        cuerpo = sesion.get(reverse("jobs:ficha", kwargs={"pk": trabajo.pk})).content.decode()
        assert "Repasa el texto antes de fiarte" in cuerpo


class TestElHijo:
    def test_reconoce_cada_pagina_y_avisa_del_progreso(
        self, entorno, tesseract_falso, monkeypatch, capsys
    ):
        escaneo = _pdf(entorno / "escaneo.pdf", 3)
        monkeypatch.setenv(tarea.VARIABLE_TESSERACT, "tesseract-falso")
        parcial = entorno / "escaneo_con_texto.parcial.pdf"

        informe = tarea.ejecutar(
            "ocr",
            {"entradas": [{"ruta": str(escaneo)}], "opciones": {"idioma": "spa"}},
            parcial,
        )
        assert informe == {"detalles": {"paginas": 3}}
        assert ocr.ya_tiene_texto(parcial)
        assert len(tesseract_falso) == 3
        assert all(argv[0] == "tesseract-falso" for argv in tesseract_falso)
        # **Una línea por página**: sin ellas, el detector de silencio mataría un trabajo
        # sano de cuarenta minutos por no decir nada.
        salida = capsys.readouterr().out
        assert salida.count("PROGRESO") == 3
        assert "PROGRESO 1.000" in salida

    def test_no_sondea_por_su_cuenta(self, entorno, tesseract_falso, monkeypatch):
        """La sonda guarda en la caché de Django, y el hijo no arranca Django."""

        def no(**_):
            raise AssertionError("el hijo no debe sondear")

        monkeypatch.setattr(ocr, "sondar", no)
        monkeypatch.setenv(tarea.VARIABLE_TESSERACT, "tesseract-falso")
        informe = tarea.ejecutar(
            "ocr",
            {"entradas": [{"ruta": str(_pdf(entorno / "e.pdf", 1))}], "opciones": {}},
            entorno / "e.parcial.pdf",
        )
        assert "codigo" not in informe, informe

    def test_sin_la_ruta_del_programa_es_sin_tesseract(self, entorno, monkeypatch):
        monkeypatch.delenv(tarea.VARIABLE_TESSERACT, raising=False)
        informe = tarea.ejecutar(
            "ocr",
            {"entradas": [{"ruta": str(_pdf(entorno / "e.pdf", 1))}], "opciones": {}},
            entorno / "e.parcial.pdf",
        )
        assert informe["codigo"] == "sin-tesseract"

    def test_pasado_el_tope_lo_dice_con_su_codigo(self, entorno, monkeypatch):
        monkeypatch.setattr(ocr, "TOPE_PAGINAS", 2)
        monkeypatch.setenv(tarea.VARIABLE_TESSERACT, "tesseract-falso")
        informe = tarea.ejecutar(
            "ocr",
            {"entradas": [{"ruta": str(_pdf(entorno / "e.pdf", 3))}], "opciones": {}},
            entorno / "e.parcial.pdf",
        )
        assert informe["codigo"] == "demasiadas-paginas"


class TestElPlan:
    def _trabajo(self, entorno, paginas):
        usuario = get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
        escaneo = _pdf(entorno / "escaneo.pdf", 1)
        job = ConversionJob.objects.create(
            owner=usuario,
            herramienta="ocr",
            source_path=str(escaneo),
            source_name=escaneo.name,
            target_format_code="doc:ocr",
            output_path=str(entorno / "escaneo_con_texto.pdf"),
            options={"idioma": "spa", "paginas": paginas},
        )
        EntradaDeTrabajo.objects.create(job=job, orden=0, ruta=str(escaneo), nombre=escaneo.name)
        return job

    def test_el_plazo_crece_con_las_paginas(self, entorno, con_tesseract):
        """Un plazo fijo es el mismo defecto que el de gunicorn, solo que más largo."""
        corto = motor.plan(self._trabajo(entorno, 10))
        assert corto.timeout_s == ocr.plazo_s(10)
        largo = ocr.plazo_s(500)
        assert largo > 500 * ocr.SEGUNDOS_ESTIMADOS_POR_PAGINA, "tiene que caber el caso real"

    def test_el_hijo_recibe_la_ruta_del_programa(self, entorno, con_tesseract):
        plan = motor.plan(self._trabajo(entorno, 1))
        assert plan.env[tarea.VARIABLE_TESSERACT] == "tesseract-falso"
        assert plan.emite_progreso


class TestLaEstimacion:
    @pytest.mark.parametrize(
        "paginas, dice",
        [(1, "menos de un minuto"), (20, "un minuto"), (500, "unos 25 minutos")],
    )
    def test_se_lee_natural(self, paginas, dice):
        assert ocr.estimacion(paginas) == dice


@hay_tesseract
@pytest.mark.django_db(transaction=True)
class TestDondeTesseractEsta:
    """De punta a punta, con el hijo y el programa de verdad."""

    def test_un_escaneo_sale_con_texto_por_la_cola(self, sesion, entorno):
        from django.core.cache import cache

        from apps.jobs import despachador

        cache.delete(ocr.CLAVE_DE_CACHE)
        escaneo = _pdf(entorno / "escaneo.pdf", 2)
        sesion.post(
            reverse("documents:ocr"),
            {"ruta": str(escaneo), "accion": "reconocer", "idioma": "spa"},
        )
        assert despachador.procesar_una_vez("pesado") == 1
        trabajo = ConversionJob.objects.get()
        assert trabajo.status == "done", trabajo.reason_detail
        assert trabajo.verification["paginas_verificadas"] == 2
