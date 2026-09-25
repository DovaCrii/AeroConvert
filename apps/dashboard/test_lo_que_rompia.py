"""Lo que impedía terminar una conversión y no daba ningún error.

## Por qué estas pruebas van juntas

Cada una sostiene un fallo que se veía como «no funciona»: soltar un archivo no hacía nada,
un error del servidor dejaba la pantalla quieta y en silencio, la ficha aparecía fuera de la
vista, y un error al convertir tiraba el archivo elegido. Ninguno lanzaba una excepción, así
que ninguna prueba los habría cazado mirando solo si algo revienta.

Las de JavaScript son **estructurales** —leen el fichero— porque el portón no ejecuta un
navegador. No prueban que el navegador lo haga; prueban que nadie quite la pieza que lo hace,
que es como se perdieron las veces anteriores. La comprobación de verdad está en el paseo con
el navegador de la verificación de la fase.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.messages import constants
from django.urls import reverse

JS = Path(settings.BASE_DIR) / "static" / "js"

pytestmark = pytest.mark.django_db


@pytest.fixture
def sesion(client):
    client.force_login(
        get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    )
    return client


class TestSoltarUnArchivoLoSube:
    """**Soltar escribía el nombre en un campo oculto y solo enviaba si llevaba una barra**,
    cosa que un nombre soltado no lleva nunca. No hacía nada, debajo de un rótulo que decía
    «Arrastra el archivo aquí»."""

    def test_pone_los_bytes_en_el_campo_de_archivo(self):
        codigo = (JS / "convertir.js").read_text("utf-8")
        assert "campo.files" in codigo, "tiene que asignar el archivo al campo, no su nombre"
        assert 'dispatchEvent(new Event("change"' in codigo, (
            "tiene que disparar el mismo `change` que el botón, para ir por `subida.js`"
        )

    def test_y_no_vuelve_a_escribir_rutas(self):
        """Lo que hacía antes, y la señal de que alguien lo ha devuelto."""
        codigo = (JS / "convertir.js").read_text("utf-8")
        assert ".name;" not in codigo and "campo.value = " not in codigo

    def test_evita_que_el_navegador_abra_el_archivo(self):
        """Sin `preventDefault` en `dragover` a nivel de documento, soltar fuera de la tarjeta
        abre el archivo en la pestaña y la pantalla se pierde."""
        codigo = (JS / "convertir.js").read_text("utf-8")
        assert re.search(r'document\.addEventListener\("dragover"', codigo)
        assert re.search(r'document\.addEventListener\("drop"', codigo)

    def test_la_pantalla_marca_la_zona_y_conserva_el_boton(self, sesion):
        """El botón no sobra: arrastrar no puede ser la única forma (WCAG 2.5.7)."""
        cuerpo = sesion.get(reverse("dashboard:convertir")).content.decode()
        assert "data-zona-soltar" in cuerpo
        zona = cuerpo[cuerpo.index("data-zona-soltar") :]
        assert 'type="file"' in zona[: zona.index("</form>")]


class TestLosErroresSeVen:
    """**htmx no pinta nada cuando el servidor contesta con un error**, y no había ningún
    manejador. Un 500 al mirar un archivo dejaba la barra quieta en «Subido. Mirando qué es…»
    para siempre."""

    @pytest.mark.parametrize("evento", ["htmx:responseError", "htmx:sendError"])
    def test_hay_quien_escuche_los_fallos(self, evento):
        assert f'"{evento}"' in (JS / "respuestas.js").read_text("utf-8")

    def test_el_fallo_se_pinta_como_alerta(self):
        assert 'role="alert"' in (JS / "respuestas.js").read_text("utf-8")

    def test_la_barra_de_subida_se_retira_tambien_al_fallar(self):
        """Solo se retiraba tras un éxito. Ese era el «Subido. Mirando qué es…» eterno."""
        codigo = (JS / "subida.js").read_text("utf-8")
        assert "htmx:responseError" in codigo and "htmx:sendError" in codigo

    def test_esta_cargado_en_todas_las_pantallas(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert "js/respuestas.js" in cuerpo


class TestLoQueLlegaSeVeYSeOye:
    def test_la_ficha_se_enfoca_al_llegar(self, sesion):
        """Aparecía debajo de las dos tarjetas de origen, fuera de la vista, sin moverse nada:
        después de elegir un archivo parecía que no había pasado nada."""
        cuerpo = sesion.get(reverse("dashboard:convertir")).content.decode()
        assert re.search(r'<div id="ficha"[^>]*data-enfocar', cuerpo)

    def test_hay_una_region_que_anuncia(self, sesion):
        """Una región pequeña, y no `aria-live` sobre la ficha entera: eso leería en voz alta
        cuarenta líneas cada vez que llega una."""
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert re.search(r'id="anuncio"[^>]*role="status"[^>]*aria-live="polite"', cuerpo)

    def test_la_busqueda_dice_cuanto_encontro(self, sesion):
        cuerpo = sesion.get(
            reverse("dashboard:que_puedo_hacer"), {"q": "contraseña"}, HTTP_HX_REQUEST="true"
        ).content.decode()
        assert "data-anunciar" in cuerpo
        assert re.search(r"\d+ herramientas? para «contraseña»", cuerpo)


class TestLosMensajesPorSuNivel:
    """Antes todo lo que no era error salía en el ámbar de «cuidado»: un «Hecho» se leía igual
    que un aviso. Y cada nivel lleva **icono y palabra**, no solo color."""

    @pytest.mark.parametrize(
        ("nivel", "clase", "palabra"),
        [
            (constants.SUCCESS, "mensaje-exito", "Hecho:"),
            (constants.INFO, "mensaje-info", "Información:"),
            (constants.WARNING, "mensaje-aviso", "Aviso:"),
            (constants.ERROR, "mensaje-error", "Error:"),
        ],
    )
    def test_cada_nivel_tiene_su_clase_y_su_palabra(self, rf, nivel, clase, palabra):
        from django.contrib.messages.storage.base import Message
        from django.template.loader import render_to_string

        html = render_to_string("base.html", {"messages": [Message(nivel, "algo")]})
        assert clase in html
        assert palabra in html, "sin la palabra, el lector de pantalla solo oye el mensaje"
        assert "mensaje-icono" in html

    def test_el_error_interrumpe_y_el_resto_espera(self):
        from django.contrib.messages.storage.base import Message
        from django.template.loader import render_to_string

        error = render_to_string("base.html", {"messages": [Message(constants.ERROR, "x")]})
        exito = render_to_string("base.html", {"messages": [Message(constants.SUCCESS, "x")]})
        assert 'mensaje-error" role="alert"' in error
        assert 'mensaje-exito" role="status"' in exito


class TestLosCodigosNoSeEnsenanSueltos:
    def test_la_ficha_pliega_el_codigo_bajo_el_mensaje(self, sesion, tmp_path, settings):
        """«Motivo: `ruta-no-permitida`» a la vista era vocabulario de quien programa."""
        settings.RAICES_PERMITIDAS = str(tmp_path)
        cuerpo = sesion.get(
            reverse("dashboard:inspeccionar"), {"ruta": str(tmp_path / "no-existe.tif")}
        ).content.decode()
        assert "Motivo:" not in cuerpo
        assert "detalle-tecnico" in cuerpo
        assert 'role="alert"' in cuerpo

    def test_el_historial_dice_el_programa_y_no_su_identificador(self, sesion):
        from apps.jobs.models import ERROR, ConversionJob

        usuario = get_user_model().objects.get(username="topografo")
        ConversionJob.objects.create(
            owner=usuario,
            source_name="plano.tif",
            source_path="D:/obras/plano.tif",
            target_format_code="geotiff",
            target_profile_id="civil3d",
            status=ERROR,
            reason_code="sin-motor",
            reason_detail="Todavía no hay ningún motor para esta conversión.",
        )
        cuerpo = sesion.get(reverse("jobs:lista")).content.decode()
        assert "Civil 3D" in cuerpo
        assert "Todavía no hay ningún motor" in cuerpo
        assert "<code" not in cuerpo[cuerpo.index("plano.tif") :].split("</tr>")[0]


class TestElTextoNoSeContradice:
    def test_el_indice_de_pdf_no_promete_que_no_hay_tope(self, sesion):
        """Decía «no hay límite de tamaño» con un tope de subida de 2.048 MB."""
        cuerpo = sesion.get(reverse("documents:inicio")).content.decode()
        assert "no hay límite de tamaño" not in cuerpo
        assert "no sale nada de tu equipo" not in cuerpo
