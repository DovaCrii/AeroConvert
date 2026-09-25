"""Subir el documento desde el propio equipo, en las pantallas de PDF de un archivo.

## Lo que no funcionaba

Cinco de estas pantallas llamaban a `modo.comprobar_ruta()` por su cuenta, saltándose la
puerta única de `apps/core/entrada.py`. Así que **la subida nunca funcionó en ellas**: el
identificador `subida:<uuid>` llegaba a una función que solo entiende rutas del disco, y lo
rechazaba por no estar dentro de las raíces permitidas.

Y no se notaba, porque las pruebas de esas pantallas mandaban siempre una ruta.

## Y lo que no puede volver a pasar

Que el formulario reciba de vuelta **la ruta del servidor**. Para un archivo subido, `ruta` y
`token` son cosas distintas, y devolver la primera dejaría que el POST siguiente la tratara
como una ruta del disco — que es exactamente la separación que `entrada.py` existe para
sostener.
"""

import io

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from pypdf import PdfWriter

from apps.core.models import ArchivoSubido

pytestmark = pytest.mark.django_db

CLAVE = "clave-larga-de-verdad-2026"

#: Las pantallas de un solo documento, con la acción que cada una espera del primer paso.
PANTALLAS = (
    "documents:dividir",
    "documents:numerar",
    "documents:marca",
    "documents:a_imagenes",
    "documents:proteger",
)


def _pdf_en_memoria(paginas: int = 3) -> io.BytesIO:
    escritor = PdfWriter()
    for _ in range(paginas):
        escritor.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    escritor.write(buffer)
    buffer.seek(0)
    buffer.name = "memoria.pdf"
    return buffer


@pytest.fixture
def sesion(client, db, settings, tmp_path):
    settings.MODO = "taller"
    settings.RAICES_PERMITIDAS = str(tmp_path)
    usuario = get_user_model().objects.create_user("ana", password=CLAVE)  # nosec B106
    client.force_login(usuario)
    return client


@pytest.mark.parametrize("pantalla", PANTALLAS)
class TestSubirDesdeElEquipo:
    def test_se_acepta_el_archivo_y_se_lee(self, sesion, pantalla):
        respuesta = sesion.post(
            reverse(pantalla), {"archivo": _pdf_en_memoria(), "accion": "mirar"}
        )
        assert respuesta.status_code == 200
        assert ArchivoSubido.objects.count() == 1, "No se guardó la subida."

    def test_y_el_formulario_vuelve_con_el_identificador_no_con_la_ruta(self, sesion, pantalla):
        cuerpo = sesion.post(
            reverse(pantalla), {"archivo": _pdf_en_memoria(), "accion": "mirar"}
        ).content.decode()

        subida = ArchivoSubido.objects.get()
        assert f'value="subida:{subida.pk}"' in cuerpo
        assert str(subida.ruta) not in cuerpo

    def test_y_se_enseña_el_nombre_que_la_persona_reconoce(self, sesion, pantalla):
        """El del servidor no le dice nada a nadie."""
        cuerpo = sesion.post(
            reverse(pantalla), {"archivo": _pdf_en_memoria(), "accion": "mirar"}
        ).content.decode()
        assert "memoria.pdf" in cuerpo

    def test_sin_archivo_ni_ruta_lo_dice_y_no_revienta(self, sesion, pantalla):
        respuesta = sesion.post(reverse(pantalla), {"accion": "mirar"})
        assert respuesta.status_code == 200
        assert "No indicaste ningún archivo" in respuesta.content.decode()


class TestElFormularioMandaElArchivo:
    """**El cliente de pruebas de Django manda siempre multipart**, así que las pruebas de
    arriba pasaban en Proteger aunque un navegador de verdad no enviara el archivo: al
    formulario le faltaba `enctype="multipart/form-data"`, y sin él el navegador manda solo
    el nombre. Esto mira la plantilla, que es donde estaba el fallo."""

    def test_toda_pantalla_con_subida_la_declara(self):
        import re
        from pathlib import Path

        from django.conf import settings

        carpeta = Path(settings.BASE_DIR) / "templates" / "documents"
        sin_enctype = []
        for plantilla in carpeta.glob("*.html"):
            if plantilla.name.startswith("_"):
                continue  # los fragmentos van dentro del formulario de otra
            texto = plantilla.read_text(encoding="utf-8")
            if 'include "documents/_origen.html"' not in texto and 'type="file"' not in texto:
                continue
            formularios = re.findall(r"<form\b[^>]*>", texto)
            if not any('enctype="multipart/form-data"' in f for f in formularios):
                sin_enctype.append(plantilla.name)
        assert sin_enctype == []


class TestLaCajaDeRutaYaNoEsta:
    """Era la única vía cuando estas pantallas se escribieron para una estación de trabajo, y
    en el servidor se volvió una trampa: pedía una ruta, alguien pegaba la de su propio
    equipo, y recibía «fuera de las carpetas permitidas»."""

    @pytest.mark.parametrize("pantalla", PANTALLAS)
    def test_no_hay_campo_de_texto_para_la_ruta(self, sesion, pantalla):
        cuerpo = sesion.get(reverse(pantalla)).content.decode()
        assert 'id="id_ruta"' not in cuerpo

    @pytest.mark.parametrize("pantalla", PANTALLAS)
    def test_pero_si_las_dos_vias(self, sesion, pantalla):
        cuerpo = sesion.get(reverse(pantalla)).content.decode()
        assert 'name="archivo"' in cuerpo, "Falta subir desde el equipo."
        assert "explorador" in cuerpo, "Falta el explorador de la carpeta compartida."


class TestLaRutaDeLaCarpetaSigueValiendo:
    """El explorador escribe una ruta en el campo oculto, así que la vía de ruta **no
    desaparece**: deja de teclearse, que es otra cosa."""

    def test_una_ruta_dentro_de_las_raices_se_acepta(self, sesion, tmp_path):
        memoria = tmp_path / "plano.pdf"
        escritor = PdfWriter()
        escritor.add_blank_page(width=595, height=842)
        with memoria.open("wb") as destino:
            escritor.write(destino)

        cuerpo = sesion.post(
            reverse("documents:dividir"), {"ruta": str(memoria), "accion": "mirar"}
        ).content.decode()
        assert "1 página(s)" in cuerpo
