"""Unir e «imágenes a PDF» con archivos subidos desde el navegador.

Aquí estaba el riesgo de toda la costura. La pantalla de unir **no tiene estado en el
servidor**: la lista de archivos viaja entera en un campo de texto y la receta indexa
posiciones de esa lista. Un `<input type="file">` rompe esa invariante, porque el navegador
**no reenvía los bytes** al pulsar «bajar», y desde el servidor no se puede repoblar.

Lo que la arregla es que en la lista viajen **identificadores** en vez de rutas. Desde el
segundo POST la pantalla es exactamente tan sin estado como era, y `receta.py` no ha tenido
que cambiar ni una línea.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import ArchivoSubido
from apps.formats import pdf as lector

pytestmark = pytest.mark.django_db


def _pdf(cuantas=2, texto=b"") -> bytes:
    import io

    from pypdf import PdfWriter

    escritor = PdfWriter()
    for _ in range(cuantas):
        escritor.add_blank_page(width=210 / lector.MM_POR_PUNTO, height=297 / lector.MM_POR_PUNTO)
    memoria = io.BytesIO()
    escritor.write(memoria)
    return memoria.getvalue()


def _imagen(tamano=(600, 400)) -> bytes:
    import io

    from PIL import Image

    memoria = io.BytesIO()
    Image.new("RGB", tamano, (200, 40, 40)).save(memoria, "JPEG")
    return memoria.getvalue()


@pytest.fixture
def sesion(client, tmp_path, settings):
    settings.RAICES_PERMITIDAS = str(tmp_path)
    settings.MEDIA_ROOT = str(tmp_path / "medios")
    settings.CARPETA_DE_TRABAJO = str(tmp_path / "trabajo")
    client.force_login(
        get_user_model().objects.create_user("ana", password="x" * 20)  # nosec B106
    )
    return client


def _subir_a_unir(sesion, *nombres, texto=""):
    archivos = [SimpleUploadedFile(n, _pdf(), "application/pdf") for n in nombres]
    return sesion.post(
        reverse("documents:componer"),
        {"accion": "analizar", "archivos_texto": texto, "archivos": archivos},
    )


class TestSubirYUnir:
    def test_un_pdf_subido_aparece_con_sus_paginas(self, sesion):
        cuerpo = _subir_a_unir(sesion, "memoria.pdf").content.decode()
        assert "memoria.pdf" in cuerpo
        assert ArchivoSubido.objects.count() == 1

    def test_dos_a_la_vez(self, sesion):
        _subir_a_unir(sesion, "memoria.pdf", "planos.pdf")
        assert ArchivoSubido.objects.count() == 2

    def test_en_la_lista_va_el_identificador_y_no_la_ruta(self, sesion, settings):
        """**La prueba de la fuga.** Si el campo devolviera la ruta de `MEDIA_ROOT`, el POST
        siguiente la trataría como una ruta del disco del servidor."""
        cuerpo = _subir_a_unir(sesion, "memoria.pdf").content.decode()
        subida = ArchivoSubido.objects.get()
        assert subida.token in cuerpo
        assert str(settings.MEDIA_ROOT) not in cuerpo
        assert str(subida.ruta) not in cuerpo

    def test_se_pueden_mezclar_con_rutas(self, sesion, tmp_path):
        pegado = tmp_path / "del_recurso.pdf"
        pegado.write_bytes(_pdf())
        cuerpo = _subir_a_unir(sesion, "subido.pdf", texto=str(pegado)).content.decode()
        assert "del_recurso.pdf" in cuerpo
        assert "subido.pdf" in cuerpo


class TestLaRecetaSobrevive:
    def test_bajar_una_pagina_no_pierde_los_archivos(self, sesion):
        """**El fallo exacto que esto evita.** El navegador no reenvía los bytes al pulsar
        «bajar»: si la lista llevara rutas de un archivo que solo existe en el equipo de la
        persona, el segundo POST se quedaría sin nada que componer."""
        primera = _subir_a_unir(sesion, "memoria.pdf")
        subida = ArchivoSubido.objects.get()
        receta = _receta_de(primera.content.decode())

        segunda = sesion.post(
            reverse("documents:componer"),
            {"accion": "bajar:0", "archivos_texto": subida.token, "receta": receta},
        )
        cuerpo = segunda.content.decode()
        assert "memoria.pdf" in cuerpo
        assert subida.token in cuerpo

    def test_y_se_puede_generar(self, sesion):
        _subir_a_unir(sesion, "memoria.pdf", "planos.pdf")
        subidas = list(ArchivoSubido.objects.order_by("created_at"))
        texto = "\n".join(s.token for s in subidas)

        respuesta = sesion.post(
            reverse("documents:componer"),
            {
                "accion": "generar",
                "archivos_texto": texto,
                "receta": "0:1:0,0:2:0,1:1:0,1:2:0",
            },
        )
        assert respuesta.status_code == 200
        assert "páginas en" in respuesta.content.decode()


def _receta_de(html: str) -> str:
    import re

    hallado = re.search(r'name="receta" value="([^"]*)"', html)
    return hallado.group(1) if hallado else ""


class TestDondeCaeElResultado:
    def test_si_venia_de_una_subida_va_a_la_carpeta_de_trabajo(self, sesion, settings):
        """No hay «al lado del original» que valga: el original está en `MEDIA_ROOT`, y ahí
        no se escribe nada que la persona vaya a buscar."""
        _subir_a_unir(sesion, "memoria.pdf")
        subida = ArchivoSubido.objects.get()
        sesion.post(
            reverse("documents:componer"),
            {"accion": "generar", "archivos_texto": subida.token, "receta": "0:1:0,0:2:0"},
        )
        from pathlib import Path

        assert (Path(settings.CARPETA_DE_TRABAJO) / "memoria_unido.pdf").exists()

    def test_si_venia_de_una_ruta_va_al_lado(self, sesion, tmp_path):
        """Quien compone una entrega la quiere junto a sus archivos."""
        pegado = tmp_path / "memoria.pdf"
        pegado.write_bytes(_pdf())
        sesion.post(
            reverse("documents:componer"),
            {"accion": "generar", "archivos_texto": str(pegado), "receta": "0:1:0,0:2:0"},
        )
        assert (tmp_path / "memoria_unido.pdf").exists()


class TestLaMiniaturaDeUnaSubida:
    def test_se_dibuja(self, sesion):
        _subir_a_unir(sesion, "memoria.pdf")
        subida = ArchivoSubido.objects.get()
        respuesta = sesion.get(reverse("documents:miniatura"), {"ruta": subida.token, "pagina": 1})
        assert respuesta.status_code == 200
        assert respuesta["Content-Type"] == "image/png"

    def test_pero_no_la_de_otra_persona(self, sesion, client):
        """Algo que con una ruta no se podía comprobar: una subida **sí tiene dueño**."""
        _subir_a_unir(sesion, "memoria.pdf")
        subida = ArchivoSubido.objects.get()

        otra = get_user_model().objects.create_user("beto", password="x" * 20)  # nosec B106
        client.force_login(otra)
        respuesta = client.get(reverse("documents:miniatura"), {"ruta": subida.token})
        assert respuesta.status_code == 400


class TestImagenesAPdf:
    def test_se_suben_y_se_componen(self, sesion, settings):
        archivos = [SimpleUploadedFile(f"foto{n}.jpg", _imagen(), "image/jpeg") for n in (1, 2)]
        sesion.post(reverse("documents:imagenes"), {"archivos": archivos, "tamano": "a4"})

        from pathlib import Path

        salida = Path(settings.CARPETA_DE_TRABAJO) / "foto1_imagenes.pdf"
        assert lector.leer_cabecera(salida).cuantas == 2


class TestElTope:
    def test_algo_demasiado_grande_se_rechaza_y_lo_dice(self, sesion, settings):
        settings.TOPE_MB = 1
        enorme = SimpleUploadedFile("enorme.pdf", b"x" * (2 * 1_048_576), "application/pdf")
        cuerpo = sesion.post(
            reverse("documents:componer"),
            {"accion": "analizar", "archivos_texto": "", "archivos": enorme},
            follow=True,
        ).content.decode()

        assert "carpeta compartida" in cuerpo
        assert ArchivoSubido.objects.count() == 0
