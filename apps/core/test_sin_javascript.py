"""Que se pueda navegar y buscar **con JavaScript apagado**.

## Por qué esta regla existe aquí y no en cualquier aplicación

La política de contenido de esta casa es `script-src 'self'` **sin `unsafe-inline`**, y eso
tiene una consecuencia que ya mordió varias veces: cuando algo de JavaScript no llega a
ejecutarse, **no hay error visible**. No sale nada en pantalla, no sale nada en el registro
del servidor; sencillamente no pasa nada al pulsar. Un fichero que no carga, una regla de
CSP que cambia, un navegador de oficina con una extensión de más — y el menú deja de abrir
sin que nadie sepa por qué.

Así que la navegación **no puede depender de JavaScript**. Lo que se apoya en él es la
comodidad: cerrar el menú al pulsar fuera, filtrar mientras se escribe, el atajo de teclado.
Todo eso puede desaparecer y la aplicación sigue usándose entera.

## Lo que comprueba esto, y por qué se mira el HTML del servidor

Se pide la página como la pediría un navegador sin JavaScript —el cliente de pruebas no
ejecuta ninguno— y se mira lo que llega. Si el menú viniera vacío para rellenarlo después, o
si el buscador fuera un botón con un manejador, aquí se vería.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def sesion(client):
    client.force_login(
        get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    )
    return client


class TestElLateralAbreSolo:
    """**Lo que abre y cierra los grupos del lateral es `details`/`summary`, no `lateral.js`.**

    Ese fichero solo añade lo que `details` no trae: ocultar todo el lateral y sacarlo en
    pantallas estrechas. Si desapareciera, el lateral seguiría a la vista, sus grupos
    seguirían abriéndose con un clic y recorriéndose con el tabulador.
    """

    def test_los_grupos_son_un_details_de_verdad(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert re.search(r"<details[^>]*class=\"[^\"]*\blateral-grupo\b", cuerpo), (
            "el grupo dejó de ser un `details`: sin JavaScript ya no abre"
        )
        assert "<summary" in cuerpo, "un `details` sin `summary` no se puede pulsar"

    def test_y_su_contenido_llega_ya_escrito(self, sesion):
        """Si el panel viniera vacío para rellenarlo después, sin JavaScript sería un botón
        que abre un hueco."""
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        lateral = cuerpo[cuerpo.index('<aside class="lateral"') : cuerpo.index("</aside>")]
        assert lateral.count("menu-enlace") >= 5, "el lateral llega sin sus entradas dentro"
        assert reverse("dashboard:convertir") in lateral

    def test_esconderlo_es_cosa_de_javascript_y_nada_lo_esconde_sin_el(self):
        """Sin `lateral.js` nadie añade `js-lateral`, y el CSS solo esconde el lateral con ella."""
        from pathlib import Path

        from django.conf import settings

        css = (Path(settings.BASE_DIR) / "static" / "css" / "app.css").read_text(encoding="utf-8")
        reglas = re.findall(r"([^{}]*\.lateral(?![\w-])[^{}]*)\{[^}]*display:\s*none", css)
        assert reglas, "no hay ninguna regla que esconda el lateral"
        for selector in reglas:
            assert "js-lateral" in selector, selector.strip()


class TestBuscarSinJavaScript:
    """htmx filtra mientras se escribe. Sin él, **la tecla Intro tiene que bastar**.

    Los dos formularios van sin `action` ni `method`, así que por omisión hacen un GET a su
    propia dirección con el campo dentro. Eso funciona *si y solo si* el nombre del campo es
    el que la vista lee — y esa coincidencia no la sostiene nada más que esta prueba.
    """

    @pytest.mark.parametrize(
        ("nombre_url", "campo", "escrito", "esperado"),
        [
            ("dashboard:que_puedo_hacer", "q", "contraseña", "Proteger o desbloquear PDF"),
            ("tino:preguntar", "p", "¿qué es un COG?", "Cloud Optimized GeoTIFF"),
        ],
    )
    def test_un_get_normal_contesta_lo_mismo(
        self, sesion, settings, nombre_url, campo, escrito, esperado
    ):
        settings.TINO_VISIBLE = True  # apagado da 404; aquí se prueba el formulario
        respuesta = sesion.get(reverse(nombre_url), {campo: escrito})
        assert esperado in respuesta.content.decode()

    @pytest.mark.parametrize(
        ("nombre_url", "campo"),
        [("dashboard:que_puedo_hacer", "q"), ("tino:preguntar", "p")],
    )
    def test_el_campo_se_llama_como_la_vista_lo_lee(self, sesion, settings, nombre_url, campo):
        """La comprobación que parece redundante y no lo es: si alguien renombra el campo en
        la plantilla, htmx lo manda igual —lleva el nombre puesto— y **solo se rompe sin
        JavaScript**, que es donde nadie mira."""
        settings.TINO_VISIBLE = True
        cuerpo = sesion.get(reverse(nombre_url)).content.decode()
        assert f'name="{campo}"' in cuerpo


class TestLosAtajosSonSoloComodidad:
    def test_los_ejemplos_son_enlaces_y_no_botones(self, sesion):
        """Cada ejemplo es la búsqueda de verdad, con su dirección propia: se puede copiar,
        compartir y guardar en favoritos. Un botón con manejador no haría nada de eso — y
        con esta CSP, tampoco funcionaría."""
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        ejemplos = re.findall(r'<a class="ejemplo" href="([^"]+)"', cuerpo)
        assert len(ejemplos) >= 3
        assert all(e.startswith("?q=") for e in ejemplos), ejemplos

    def test_la_tecla_que_se_enseña_no_es_la_unica_forma(self, sesion):
        """`/` enfoca el buscador, y el buscador está ahí para pulsarlo con el ratón. **La
        regla que evita el desastre con los atajos**: descubrir uno no puede ser necesario."""
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert 'id="q"' in cuerpo
        assert 'class="atajo-pista"' in cuerpo
