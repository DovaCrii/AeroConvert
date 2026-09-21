"""Los dos atajos de teclado, y la regla que impide que hagan daño.

## La regla

**Descubrir un atajo no puede ser necesario.** Todo lo que hacen se puede hacer con el ratón
igual; el atajo solo ahorra el viaje. Por eso lo que se comprueba aquí no es que funcionen
—eso lo hace el navegador— sino las tres cosas que lo convierten en un problema si se
pierden: que se enseñe donde se usa, que no pise los del navegador, y que el fichero llegue
a cargarse, porque con esta política de contenido un manejador en línea **no avisa de nada**:
sencillamente no pasa nada al pulsar.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

ATAJOS = Path(settings.BASE_DIR) / "static" / "js" / "atajos.js"

pytestmark = pytest.mark.django_db


@pytest.fixture
def sesion(client):
    client.force_login(
        get_user_model().objects.create_user("topografo", password="x" * 20)  # nosec B106
    )
    return client


class TestSeEnsenaDondeSeUsa:
    def test_la_tecla_sale_junto_al_campo(self, sesion):
        """Un atajo que no se ve es un atajo que nadie usa, y entonces no era un atajo: era
        código que mantener."""
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert 'class="atajo-pista"' in cuerpo

    def test_y_no_en_una_hoja_de_trucos_aparte(self):
        """NN/g es tajante con los tutoriales que interrumpen. Con cinco personas se explica
        hablando; lo que escala es la pista junto a cada paso."""
        plantillas = Path(settings.BASE_DIR) / "templates"
        assert not list(plantillas.rglob("*atajos*")), (
            "Una pantalla de atajos es lo contrario de enseñarlos donde se usan."
        )


class TestNoPisaNadaDelNavegador:
    def test_cualquier_modificador_lo_desactiva(self):
        """`Ctrl+/`, `Cmd+F` y compañía son del navegador. Robar uno de esos es el error que
        hace que la gente desconfíe del teclado en una aplicación entera."""
        codigo = ATAJOS.read_text("utf-8")
        assert re.search(r"ctrlKey\s*\|\|\s*.*metaKey", codigo)
        assert "altKey" in codigo
        assert "shiftKey" in codigo

    def test_escribiendo_en_un_campo_no_hace_nada(self):
        """La barra tiene que poder teclearse en una ruta o en una contraseña. Sin esto, el
        primer `/` de «D:/obras» manda el foco a otro sitio."""
        codigo = ATAJOS.read_text("utf-8")
        assert "isContentEditable" in codigo
        assert "textarea" in codigo


class TestQueLlegueACargarse:
    def test_esta_declarado_en_la_base(self, sesion):
        cuerpo = sesion.get(reverse("dashboard:que_puedo_hacer")).content.decode()
        assert "js/atajos.js" in cuerpo

    def test_y_no_hay_manejadores_en_linea_que_no_correrian(self):
        """**El fallo silencioso de esta casa.** La política es `script-src 'self'` sin
        `unsafe-inline`: un `onkeydown=` en el atributo no se ejecuta y no da error — parece
        que el atajo no existe.
        """
        plantillas = Path(settings.BASE_DIR) / "templates"
        culpables = [
            f.name
            for f in plantillas.rglob("*.html")
            if re.search(r"\son(key|click|change|submit)\w*\s*=", f.read_text("utf-8"))
        ]
        assert not culpables, f"{culpables}: la CSP los ignora en silencio"
