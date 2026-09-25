"""Office, PDF a Word y los catálogos de tubería, por la cola.

## Lo que tienen de distinto

Las cuatro dependen de algo de fuera —Office o el motor de Access— que en el servidor no
está. Y en Office **el hijo ya existía**: la pantalla lanzaba pwsh hablando COM. Desde la
cola lo lanza el corredor con el mismo argv, y eso trae la regla número uno de regalo: lo
que decide si funcionó no es el código de salida sino que el archivo exista y verifique.
Word devuelve cero sin escribir nada más veces de las que parece.

## Cómo se prueba sin Office

Con un proceso de Python en el sitio de pwsh, que escribe lo que escribiría Word —o que no
escribe nada, o escribe un `.docx` roto— para ver qué hace el corredor en cada caso. Lo que
no se puede probar así es a Word, y eso sigue siendo manual en la estación de trabajo.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from apps.documents import catalogos, motor, office, tarea
from apps.engines.base import ruta_parcial
from apps.jobs import runner
from apps.jobs.models import ENCOLADO, ConversionJob, EntradaDeTrabajo

pytestmark = pytest.mark.django_db


@pytest.fixture
def entorno(tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    settings.MODO = "taller"
    return tmp_path


@pytest.fixture
def usuario():
    return get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106


@pytest.fixture
def sesion(client, entorno, usuario):
    client.force_login(usuario)
    return client


def _con_office(*programas):
    office.olvidar()
    cache.set(office.CLAVE_DE_CACHE, office.Disponible(frozenset(programas)))


@pytest.fixture
def con_office():
    _con_office("word", "excel", "powerpoint")
    yield
    office.olvidar()


def _docx_valido() -> bytes:
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as paquete:
        paquete.writestr("[Content_Types].xml", "<Types/>")
        paquete.writestr("word/document.xml", "<w:document/>")
    return memoria.getvalue()


def _pdf_con_texto(ruta: Path) -> Path:
    hoja = canvas.Canvas(str(ruta), pagesize=A4)
    for _ in range(3):
        hoja.drawString(72, 720, "Memoria de calculo del colector principal " * 3)
        hoja.showPage()
    hoja.save()
    return ruta


class TestLasPantallasEncolan:
    def test_office_encola_con_el_ajuste_de_ancho(self, sesion, entorno, con_office):
        informe = entorno / "informe.docx"
        informe.write_bytes(_docx_valido())
        respuesta = sesion.post(
            reverse("documents:office"), {"ruta": str(informe), "ajustar_ancho": "si"}
        )
        assert respuesta.status_code == 302
        trabajo = ConversionJob.objects.get()
        assert trabajo.herramienta == "office"
        assert trabajo.options == {"ajustar_ancho": True}
        # Junto al original, y **no** dentro de la carpeta de subidas como antes.
        assert trabajo.output_path == str(entorno / "informe.pdf")

    def test_una_extension_que_no_es_de_office_se_dice_en_la_pantalla(
        self, sesion, entorno, con_office
    ):
        notas = entorno / "notas.txt"
        notas.write_text("hola", encoding="utf-8")
        respuesta = sesion.post(reverse("documents:office"), {"ruta": str(notas)})
        assert respuesta.status_code == 200
        assert "no es un documento de Office" in respuesta.content.decode()
        assert not ConversionJob.objects.exists()

    def test_sin_el_programa_que_hace_falta_tampoco_encola(self, sesion, entorno):
        """Hay Word pero no Excel: la hoja de cálculo no puede ir a la cola a fallar allí."""
        _con_office("word")
        planilla = entorno / "cubicacion.xlsx"
        planilla.write_bytes(b"PK")
        respuesta = sesion.post(reverse("documents:office"), {"ruta": str(planilla)})
        office.olvidar()
        assert respuesta.status_code == 200
        assert "Excel no está instalado" in respuesta.content.decode()
        assert not ConversionJob.objects.exists()

    def test_pdf_a_word_mira_antes_y_encola_al_convertir(self, sesion, entorno, con_office):
        memoria = _pdf_con_texto(entorno / "memoria.pdf")
        mirar = sesion.post(reverse("documents:a_word"), {"ruta": str(memoria), "accion": "mirar"})
        assert mirar.status_code == 200
        assert not ConversionJob.objects.exists(), "mirar no encola"

        respuesta = sesion.post(
            reverse("documents:a_word"), {"ruta": str(memoria), "accion": "convertir"}
        )
        assert respuesta.status_code == 302
        assert ConversionJob.objects.get().output_path == str(entorno / "memoria.docx")

    def test_excel_a_catalogo_guarda_que_es_cada_archivo(self, sesion, entorno, monkeypatch):
        """La hoja y la plantilla **no son intercambiables**: el orden de subida no lo dice."""
        monkeypatch.setattr(
            catalogos, "sondar", lambda **_: catalogos.Disponible(controlador="ACE")
        )
        monkeypatch.setattr(catalogos, "esquema", lambda _ruta: [catalogos.Tabla("PIPE")])
        hoja = entorno / "catalogo.xlsx"
        hoja.write_bytes(b"PK")
        plantilla = entorno / "HDPE_PE100_PN16.mdb"
        plantilla.write_bytes(b"x")

        respuesta = sesion.post(
            reverse("documents:excel_a_catalogo"),
            {"ruta": str(hoja), "plantilla": str(plantilla)},
        )
        assert respuesta.status_code == 302
        trabajo = ConversionJob.objects.get()
        assert [(e.papel, e.nombre) for e in trabajo.entradas.all()] == [
            (EntradaDeTrabajo.HOJA, "catalogo.xlsx"),
            (EntradaDeTrabajo.PLANTILLA, "HDPE_PE100_PN16.mdb"),
        ]

    def test_catalogo_a_excel_encola(self, sesion, entorno, monkeypatch):
        monkeypatch.setattr(
            catalogos, "sondar", lambda **_: catalogos.Disponible(controlador="ACE")
        )
        monkeypatch.setattr(catalogos, "esquema", lambda _ruta: [catalogos.Tabla("PIPE")])
        base = entorno / "HDPE.mdb"
        base.write_bytes(b"x")
        respuesta = sesion.post(reverse("documents:catalogo_a_excel"), {"ruta": str(base)})
        assert respuesta.status_code == 302
        assert ConversionJob.objects.get().output_path == str(entorno / "HDPE.xlsx")


def _trabajo(usuario, origen: Path, herramienta: str, salida: Path, **opciones):
    job = ConversionJob.objects.create(
        owner=usuario,
        herramienta=herramienta,
        source_path=str(origen),
        source_name=origen.name,
        target_format_code=f"doc:{herramienta}",
        output_path=str(salida),
        options=opciones,
        status=ENCOLADO,
    )
    EntradaDeTrabajo.objects.create(job=job, orden=0, ruta=str(origen), nombre=origen.name)
    return job


class TestElPlanDeOffice:
    def test_el_hijo_es_pwsh_y_escribe_en_el_parcial(self, entorno, usuario, con_office):
        informe = entorno / "informe.xlsx"
        informe.write_bytes(b"PK")
        job = _trabajo(usuario, informe, "office", entorno / "informe.pdf", ajustar_ancho=True)
        plan = motor.plan(job)
        argv = list(plan.argv)
        assert argv[0] == "pwsh"
        assert argv[argv.index("-Programa") + 1] == "excel"
        assert argv[argv.index("-Destino") + 1] == str(ruta_parcial(entorno / "informe.pdf"))
        assert "-AjustarAncho" in argv
        assert not plan.emite_progreso, "pwsh no dice nada mientras Word trabaja"

    def test_pdf_a_word_usa_el_camino_de_vuelta(self, entorno, usuario, con_office):
        memoria = _pdf_con_texto(entorno / "memoria.pdf")
        plan = motor.plan(_trabajo(usuario, memoria, "a_word", entorno / "memoria.docx"))
        argv = list(plan.argv)
        assert argv[argv.index("-Programa") + 1] == office.PDF_A_WORD


@pytest.mark.django_db(transaction=True)
class TestElCorredorConUnOfficeDeMentira:
    """Un Python en el sitio de pwsh. Ver el docstring del módulo."""

    def _falso(self, monkeypatch, codigo: str):
        def plan(origen, destino, programa, **_):
            return [sys.executable, "-c", codigo, str(destino)]

        monkeypatch.setattr(office, "plan", plan)

    def _correr(self, job):
        assert runner.reclamar(job.pk)
        job.refresh_from_db()
        runner.ejecutar(job)
        job.refresh_from_db()
        return job

    def test_un_docx_bien_formado_queda_hecho(self, entorno, usuario, con_office, monkeypatch):
        self._falso(
            monkeypatch,
            "import sys, zipfile\n"
            "with zipfile.ZipFile(sys.argv[1], 'w') as z:\n"
            "    z.writestr('word/document.xml', '<w:document/>')\n",
        )
        memoria = _pdf_con_texto(entorno / "memoria.pdf")
        job = self._correr(_trabajo(usuario, memoria, "a_word", entorno / "memoria.docx"))
        assert job.status == "done", job.reason_detail
        assert Path(job.output_path).exists()
        assert job.verification["verificado_con"] == "zipfile"

    def test_salir_con_cero_sin_escribir_nada_no_es_un_exito(
        self, entorno, usuario, con_office, monkeypatch
    ):
        """**La regla número uno.** Word hace esto de verdad."""
        self._falso(monkeypatch, "import sys; sys.exit(0)")
        memoria = _pdf_con_texto(entorno / "memoria.pdf")
        job = self._correr(_trabajo(usuario, memoria, "a_word", entorno / "memoria.docx"))
        assert job.status == "error"
        assert job.reason_code == "sin-salida"

    def test_un_docx_sin_su_parte_principal_no_se_entrega(
        self, entorno, usuario, con_office, monkeypatch
    ):
        self._falso(
            monkeypatch,
            "import sys, zipfile\n"
            "with zipfile.ZipFile(sys.argv[1], 'w') as z:\n"
            "    z.writestr('otra/cosa.xml', '<x/>')\n",
        )
        memoria = _pdf_con_texto(entorno / "memoria.pdf")
        job = self._correr(_trabajo(usuario, memoria, "a_word", entorno / "memoria.docx"))
        assert job.status == "error"
        assert job.reason_code == "salida-invalida"
        assert "word/document.xml" in job.reason_detail
        assert not Path(job.output_path).exists()


class TestLosCatalogosEnElHijo:
    def test_catalogo_a_excel_cuenta_las_tablas(self, entorno, monkeypatch):
        tablas = [catalogos.Tabla("PIPE", filas=126), catalogos.Tabla("ELBOW", filas=40)]
        monkeypatch.setattr(catalogos, "esquema", lambda _ruta: tablas)
        monkeypatch.setattr(catalogos, "a_excel", lambda origen, destino: destino)
        informe = tarea.ejecutar(
            "catalogo_excel", {"entradas": [{"ruta": "x.mdb"}]}, entorno / "x.parcial.xlsx"
        )
        assert informe == {"detalles": {"tablas": [["PIPE", 126], ["ELBOW", 40]]}}

    def test_excel_a_catalogo_devuelve_los_avisos_aparte(self, entorno, monkeypatch):
        """Aparte de los detalles: el corredor los apunta y el trabajo termina «con avisos»."""
        vistos = {}

        def desde_excel(hoja, plantilla, destino):
            vistos.update(hoja=hoja, plantilla=plantilla)
            return destino, ["La tabla BOLT no venía en el Excel y queda vacía."]

        monkeypatch.setattr(catalogos, "desde_excel", desde_excel)
        informe = tarea.ejecutar(
            "excel_catalogo",
            {
                "entradas": [
                    {"ruta": "plantilla.mdb", "papel": "plantilla"},
                    {"ruta": "hoja.xlsx", "papel": "hoja"},
                ]
            },
            entorno / "x.parcial.mdb",
        )
        assert informe["avisos"] == ["La tabla BOLT no venía en el Excel y queda vacía."]
        assert "avisos" not in informe["detalles"]
        # Por su papel, no por su orden.
        assert vistos == {"hoja": "hoja.xlsx", "plantilla": "plantilla.mdb"}

    def test_sin_uno_de_los_dos_no_empieza(self, entorno):
        informe = tarea.ejecutar(
            "excel_catalogo",
            {"entradas": [{"ruta": "hoja.xlsx", "papel": "hoja"}]},
            entorno / "x.parcial.mdb",
        )
        assert informe["codigo"] == "documento-invalido"

    def test_el_hijo_usa_el_controlador_que_le_pasan(self, monkeypatch):
        """No puede sondear: la sonda guarda en la caché de Django."""

        def no(**_):
            raise AssertionError("el hijo no debe sondear")

        monkeypatch.setattr(catalogos, "sondar", no)
        monkeypatch.setenv(tarea.VARIABLE_ACCESS, "Microsoft Access Driver (*.mdb, *.accdb)")
        assert "Access Driver" in catalogos._cadena(Path("x.mdb"))

    def test_y_el_plan_se_lo_pasa(self, entorno, usuario, monkeypatch):
        monkeypatch.setattr(
            catalogos, "sondar", lambda **_: catalogos.Disponible(controlador="ACE de prueba")
        )
        base = entorno / "HDPE.mdb"
        base.write_bytes(b"x")
        plan = motor.plan(_trabajo(usuario, base, "catalogo_excel", entorno / "HDPE.xlsx"))
        assert plan.env[tarea.VARIABLE_ACCESS] == "ACE de prueba"
        motor.borrar_auxiliares(ConversionJob.objects.get())


class TestLasVeinte:
    """**Todas por la cola**, y que una nueva no pueda quedarse fuera sin que se note."""

    def test_cada_herramienta_tiene_su_especificacion(self):
        from apps.documents.herramientas import HERRAMIENTAS

        faltan = [h["id"] for h in HERRAMIENTAS if not motor.va_por_la_cola(h["id"])]
        assert faltan == []

    def test_y_quien_la_ejecute(self):
        """El hijo de Office es pwsh; las demás, una función de `tarea.py`."""
        sin_tarea = [
            h
            for h, espec in motor.ESPECIFICACIONES.items()
            if espec.exige != "office" and h not in tarea.TAREAS
        ]
        assert sin_tarea == []


class TestLaVerificacion:
    def test_un_mdb_se_reconoce_por_su_firma(self, tmp_path):
        base = tmp_path / "x.parcial.mdb"
        base.write_bytes(b"\x00\x01\x00\x00Standard Jet DB\x00" + b"\x00" * 64)
        assert motor.verificar(base, {}).correcta

    def test_y_lo_que_no_la_lleva_no_pasa(self, tmp_path):
        base = tmp_path / "x.parcial.mdb"
        base.write_bytes(b"PK\x03\x04 esto es un zip con otra extension")
        assert motor.verificar(base, {}).codigo_motivo == "salida-invalida"

    def test_un_excel_con_una_hoja_de_menos(self, tmp_path):
        """Catálogo a Excel: una hoja por tabla. Si falta una, se perdió una tabla."""
        libro = tmp_path / "x.parcial.xlsx"
        with zipfile.ZipFile(libro, "w") as paquete:
            paquete.writestr("xl/workbook.xml", "<workbook/>")
            paquete.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
        informe = {"detalles": {"tablas": [["PIPE", 126], ["ELBOW", 40]]}}
        hecho = motor.verificar(libro, informe)
        assert not hecho.correcta
        assert "2 tablas" in hecho.motivo
