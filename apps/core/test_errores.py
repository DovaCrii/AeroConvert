"""Las páginas de error.

Con `DEBUG=False` salían las de texto plano de Django: sin cabecera, sin navegación y sin la
chapa del modo. Y aquí importa más de lo normal, porque **el 404 es un camino corriente**: lo
levanta cada salida caducada.
"""

from pathlib import Path

import pytest
from django.conf import settings
from django.template import loader
from django.test import override_settings

pytestmark = pytest.mark.django_db

PLANTILLAS = Path(settings.BASE_DIR) / "templates"


class TestLaDelServidor:
    """La 500 es distinta de las demás, y por un motivo muy concreto."""

    def test_se_pinta_sin_peticion_y_sin_contexto(self):
        """**Así es exactamente como la renderiza Django**: `django.views.defaults
        .server_error` hace `loader.get_template("500.html").render()`, sin `request` y sin
        procesadores de contexto. Si la plantilla dependiera de cualquiera de los dos,
        fallaría justo cuando hace falta."""
        salida = loader.get_template("500.html").render()
        assert "AeroConvert" in salida

    def test_no_depende_de_los_estaticos(self):
        """La cadena entera: `collectstatic` sin correr → el manifiesto falta → **todas** las
        páginas dan 500 → y si `500.html` usara `{% static %}`, la página del 500 también
        reventaría. Lo que llegaría al navegador sería «A server error occurred.»

        La página que anuncia el fallo no puede depender de lo que suele fallar.
        """
        crudo = (PLANTILLAS / "500.html").read_text(encoding="utf-8")
        cuerpo = crudo.split("{% endcomment %}", 1)[-1]
        assert "{% static" not in cuerpo
        assert "{% extends" not in cuerpo
        assert "{% url" not in cuerpo

    def test_dice_que_el_original_no_se_toco(self):
        """Es lo primero que quiere saber quien ve un error a mitad de una conversión."""
        salida = loader.get_template("500.html").render()
        assert "no se han tocado" in salida


class TestLasDemas:
    @pytest.mark.parametrize("codigo", ["400", "403", "404"])
    def test_existen_y_llevan_la_identidad(self, codigo, client, django_user_model):
        from django.template.loader import render_to_string

        usuaria = django_user_model.objects.create_user("ana", password="x" * 20)  # nosec B106
        client.force_login(usuaria)
        peticion = client.get("/").wsgi_request
        salida = render_to_string(f"{codigo}.html", request=peticion)
        assert "AeroConvert" in salida

    @override_settings(DEBUG=False)
    def test_un_404_de_verdad_sale_con_la_barra(self, client):
        respuesta = client.get("/no-existe-esta-pagina/")
        assert respuesta.status_code == 404
        assert b"AeroConvert" in respuesta.content

    def test_el_404_habla_de_la_salida_caducada(self):
        """Porque es el caso que de verdad va a pasar, no «la página no existe»."""
        crudo = (PLANTILLAS / "404.html").read_text(encoding="utf-8")
        assert "caducó" in crudo

    def test_el_400_dice_lo_de_allowed_hosts(self):
        """En un despliegue nuevo, el 400 casi siempre es eso, y con `DEBUG=False` Django no
        lo dice: se parece a un problema de red y se buscan horas en el sitio equivocado."""
        crudo = (PLANTILLAS / "400.html").read_text(encoding="utf-8")
        assert "ALLOWED_HOSTS" in crudo

    def test_el_403_no_confirma_que_algo_exista(self):
        crudo = (PLANTILLAS / "403.html").read_text(encoding="utf-8")
        assert "no es tuyo" in crudo.lower()
