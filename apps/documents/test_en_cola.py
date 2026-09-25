"""Las herramientas de documentos por la cola, vistas desde la pantalla.

## La prueba que motivó toda la etapa

**Trece de las veinte herramientas no dejaban descargar el resultado de un archivo subido.**
Terminaban en «✓ Hecho: plano_numerado.pdf» y nada más: el archivo quedaba en la carpeta de
trabajo del servidor, sin enlace, y caducaba solo. Para quien trabaja desde su portátil —que
sube, no elige de la carpeta compartida— la herramienta entera no servía para nada.

Esa es la primera clase de aquí. Las demás vigilan lo que la cola trae de paso: el nombre de
la herramienta en el historial, «seguir donde lo dejaste», el dueño, y que lo que se puede
comprobar sin abrir el documento siga fallando en la pantalla y no en la cola.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from apps.jobs import despachador
from apps.jobs.models import ConversionJob

pytestmark = pytest.mark.django_db


def _bytes_de_pdf(paginas: int = 3) -> bytes:
    import io

    memoria = io.BytesIO()
    hoja = canvas.Canvas(memoria, pagesize=A4)
    for n in range(paginas):
        hoja.drawString(72, 720, f"Página {n + 1}")
        hoja.showPage()
    hoja.save()
    return memoria.getvalue()


@pytest.fixture
def entorno(tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    settings.MEDIA_ROOT = str(tmp_path / "media")
    return tmp_path


@pytest.fixture
def sesion(client, entorno):
    client.force_login(
        get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    )
    return client


def _subir_y_numerar(sesion):
    respuesta = sesion.post(
        reverse("documents:numerar"),
        {
            "archivo": SimpleUploadedFile("memoria.pdf", _bytes_de_pdf(), "application/pdf"),
            "accion": "numerar",
            "formato": "{n} / {total}",
            "posicion": "pie-derecha",
            "desde": "1",
            "empezar_en": "1",
        },
    )
    assert respuesta.status_code == 302, respuesta.content.decode()[:500]
    assert despachador.procesar_una_vez() == 1
    return ConversionJob.objects.latest("created_at")


class TestUnArchivoSubidoSeDescarga:
    def test_el_resultado_se_puede_bajar(self, sesion):
        trabajo = _subir_y_numerar(sesion)
        assert trabajo.status == "done", trabajo.reason_detail

        descarga = sesion.get(reverse("jobs:descargar", kwargs={"pk": trabajo.pk}))
        assert descarga.status_code == 200
        contenido = b"".join(descarga.streaming_content)
        assert contenido.startswith(b"%PDF")

    def test_y_no_se_escribe_dentro_de_la_carpeta_de_subidas(self, sesion, entorno):
        """Cinco pantallas escribían el resultado **al lado de la subida**, dentro de
        `MEDIA_ROOT/subidas/<id>/`, donde nadie podía descargarlo."""
        trabajo = _subir_y_numerar(sesion)
        assert str(entorno / "trabajo") in trabajo.output_path
        assert "subidas" not in trabajo.output_path

    def test_la_ficha_ofrece_descargarlo(self, sesion):
        trabajo = _subir_y_numerar(sesion)
        cuerpo = sesion.get(reverse("jobs:ficha", kwargs={"pk": trabajo.pk})).content.decode()
        assert reverse("jobs:descargar", kwargs={"pk": trabajo.pk}) in cuerpo


class TestLoQueTraeLaCola:
    def test_el_historial_dice_la_herramienta(self, sesion):
        """«doc:numerar» sería el mismo defecto que enseñar `geotiff` en lugar de su nombre."""
        _subir_y_numerar(sesion)
        cuerpo = sesion.get(reverse("jobs:lista")).content.decode()
        assert "Numerar páginas" in cuerpo
        assert "doc:numerar" not in cuerpo

    def test_la_ficha_se_titula_por_lo_que_se_hizo(self, sesion):
        trabajo = _subir_y_numerar(sesion)
        cuerpo = sesion.get(reverse("jobs:ficha", kwargs={"pk": trabajo.pk})).content.decode()
        assert "<h1" in cuerpo and "Numerar páginas</h1>" in cuerpo

    def test_seguir_donde_lo_dejaste_vuelve_a_la_herramienta(self, sesion):
        """Antes el uso de PDF no dejaba rastro, y la portada no podía ofrecer repetirlo."""
        _subir_y_numerar(sesion)
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert "Seguir donde lo dejaste" in cuerpo
        assert f'href="{reverse("documents:numerar")}"' in cuerpo

    def test_la_bienvenida_deja_de_salir(self, sesion):
        """La bienvenida es para quien no ha hecho nada. Quien solo usa herramientas de PDF
        la veía para siempre, porque esas no contaban como trabajos."""
        _subir_y_numerar(sesion)
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert "Cómo funciona esto" not in cuerpo

    def test_la_subida_se_reclama_mientras_espera(self, sesion):
        """El modelo lo prometía y ningún código lo hacía: una subida encolada seguía
        caducando a las 24 h, estuviera o no el trabajo en marcha."""
        respuesta = sesion.post(
            reverse("documents:numerar"),
            {
                "archivo": SimpleUploadedFile("m.pdf", _bytes_de_pdf(), "application/pdf"),
                "accion": "numerar",
                "formato": "{n}",
            },
        )
        assert respuesta.status_code == 302
        trabajo = ConversionJob.objects.latest("created_at")
        assert trabajo.entradas.get().subida.expires_at is None

        despachador.procesar_una_vez()
        trabajo.refresh_from_db()
        assert trabajo.entradas.get().subida.expires_at is not None, "al terminar se suelta"


class TestLoQueSeSabeSinAbrirSigueEnLaPantalla:
    """Lo que se puede comprobar sin abrir el documento **no espera a la cola** para fallar."""

    def test_numerar_mas_alla_del_final(self, sesion, entorno):
        memoria = entorno / "memoria.pdf"
        memoria.write_bytes(_bytes_de_pdf(3))
        respuesta = sesion.post(
            reverse("documents:numerar"),
            {"ruta": str(memoria), "accion": "numerar", "desde": "40", "formato": "{n}"},
        )
        assert respuesta.status_code == 200
        assert "no se puede empezar" in respuesta.content.decode()
        assert not ConversionJob.objects.exists()

    def test_una_marca_sin_texto(self, sesion, entorno):
        plano = entorno / "plano.pdf"
        plano.write_bytes(_bytes_de_pdf(1))
        respuesta = sesion.post(
            reverse("documents:marca"), {"ruta": str(plano), "accion": "marcar", "texto": "  "}
        )
        assert respuesta.status_code == 200
        assert not ConversionJob.objects.exists()

    def test_markdown_de_una_extension_que_no_se_lee(self, sesion, entorno):
        raro = entorno / "plano.dwg"
        raro.write_bytes(b"AC1032")
        respuesta = sesion.post(reverse("documents:a_markdown"), {"ruta": str(raro)})
        assert respuesta.status_code == 200
        assert "no se saca Markdown" in respuesta.content.decode()
        assert not ConversionJob.objects.exists()


class TestMarkdownEnLaCola:
    def test_cada_origen_es_su_herramienta(self, sesion, entorno):
        """Así el historial dice «CSV a Markdown» y no una genérica."""
        tabla = entorno / "puntos.csv"
        tabla.write_text("punto;este\nP1;495279.4\n", encoding="utf-8")
        assert sesion.post(reverse("documents:a_markdown"), {"ruta": str(tabla)}).status_code == 302
        assert ConversionJob.objects.latest("created_at").herramienta == "md_csv"

    def test_la_ficha_se_asoma_al_resultado(self, sesion, entorno):
        """Estaba en la pantalla de Markdown y se vino a la ficha con la conversión: es lo
        que evita descargar para descubrir que la hoja que hacía falta era la otra."""
        tabla = entorno / "puntos.csv"
        tabla.write_text("punto;este\nP1;495279.4\n", encoding="utf-8")
        sesion.post(reverse("documents:a_markdown"), {"ruta": str(tabla)})
        despachador.procesar_una_vez()
        trabajo = ConversionJob.objects.latest("created_at")
        cuerpo = sesion.get(reverse("jobs:ficha", kwargs={"pk": trabajo.pk})).content.decode()
        assert 'class="asomo"' in cuerpo and "P1" in cuerpo


class TestComprimirEnLaCola:
    def test_sin_tocar_las_imagenes_llega_como_cero(self, sesion, entorno):
        """**El fallo que había desde que entró Comprimir.** La resolución se leía con un
        ayudante que convierte todo lo menor que 1 en el valor por omisión, así que «sin
        tocar las imágenes» —la única opción que promete no estropear nada— comprimía a
        200 ppp. Ninguna prueba pasaba por la pantalla."""
        plano = entorno / "planos.pdf"
        plano.write_bytes(_bytes_de_pdf(2))
        respuesta = sesion.post(reverse("documents:comprimir"), {"ruta": str(plano), "ppp": "0"})
        assert respuesta.status_code == 302
        assert ConversionJob.objects.latest("created_at").options["ppp"] == 0

    def test_una_resolucion_inventada_falla_en_la_pantalla(self, sesion, entorno):
        plano = entorno / "planos.pdf"
        plano.write_bytes(_bytes_de_pdf(1))
        respuesta = sesion.post(reverse("documents:comprimir"), {"ruta": str(plano), "ppp": "72"})
        assert respuesta.status_code == 200
        assert not ConversionJob.objects.exists()

    def test_el_hijo_convierte_no_valio_la_pena_en_desenlace(self, monkeypatch, entorno):
        """Determinista a propósito: cuánto baja pypdf al recomprimir depende del archivo, y
        una prueba con un `if` que decide si comprobar algo es una prueba que puede no probar
        nada."""
        from apps.documents import comprimir, tarea

        falso = comprimir.Resultado(
            origen_bytes=4_000, salida_bytes=4_200, imagenes_tocadas=0, paginas=1
        )
        monkeypatch.setattr(comprimir, "comprimir", lambda *a, **k: (None, falso))

        informe = tarea.ejecutar(
            "comprimir",
            {"entradas": [{"ruta": str(entorno / "x.pdf")}], "opciones": {"ppp": 200}},
            entorno / "x.parcial.pdf",
        )
        assert informe["desenlace"] == "no-valio-la-pena"
        assert informe["detalles"]["origen_bytes"] == 4_000
        assert informe["detalles"]["salida_bytes"] == 4_200

    def test_la_ficha_lo_dice_con_los_dos_pesos_y_sin_descarga(self, sesion):
        """**Ni verde ni rojo**: el archivo está bien y ya estaba comprimido."""
        trabajo = ConversionJob.objects.create(
            owner=get_user_model().objects.get(username="topografo"),
            herramienta="comprimir",
            source_name="planos.pdf",
            source_path="/x/planos.pdf",
            target_format_code="doc:comprimir",
            status="done",
            desenlace="no-valio-la-pena",
            verification={"origen_bytes": 4_000_000, "salida_bytes": 4_200_000},
        )
        cuerpo = sesion.get(reverse("jobs:ficha", kwargs={"pk": trabajo.pk})).content.decode()
        assert "Ya estaba comprimido" in cuerpo
        assert "4,0" in cuerpo or "3,8" in cuerpo, "el peso de antes"
        assert reverse("jobs:descargar", kwargs={"pk": trabajo.pk}) not in cuerpo

    def test_va_por_el_carril_pesado(self):
        from apps.documents import motor

        assert motor.carril_de("comprimir") == "pesado"


class TestElDueno:
    """El trabajo de otro da **404 y no 403**: además de correcto, no confirma que exista."""

    @pytest.fixture
    def ajeno(self, sesion, client):
        trabajo = _subir_y_numerar(sesion)
        client.logout()
        client.force_login(
            get_user_model().objects.create_user("otra", password="y" * 20)  # nosec B106
        )
        return trabajo

    @pytest.mark.parametrize("vista", ["jobs:ficha", "jobs:progreso", "jobs:descargar"])
    def test_no_se_ve(self, client, ajeno, vista):
        assert client.get(reverse(vista, kwargs={"pk": ajeno.pk})).status_code == 404

    def test_no_se_reencola(self, client, ajeno):
        assert client.post(reverse("jobs:reencolar", kwargs={"pk": ajeno.pk})).status_code == 404

    def test_sin_entrar_se_pide_entrar(self, client, ajeno):
        client.logout()
        respuesta = client.get(reverse("jobs:ficha", kwargs={"pk": ajeno.pk}))
        assert respuesta.status_code == 302 and "/entrar/" in respuesta["Location"]
