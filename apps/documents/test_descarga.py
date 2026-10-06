"""Bajarse un resultado.

Hace falta **aunque haya carpeta compartida**: el navegador está en el equipo de la persona y
el recurso está montado en la VM, así que la ruta que se enseña es la del servidor
(`/mnt/entregas/...`) y no la suya (`Z:\\...`). Como texto no sirve para pegarla en ninguna
parte.

Y se entrega por identificador, nunca por ruta. Una vista que aceptara `?ruta=<absoluta>`
convertiría una herramienta que **escribe** en **lectura de cualquier cosa del recurso
compartido**, por GET y sin testigo.

## Un solo camino

Desde la fase 9 las herramientas pasan por la cola y se descargan por la ficha del trabajo
(`jobs:descargar`), que comprueba el dueño. La vista vieja —`documents:descargar`, con sus
filas de `Resultado`— se retiró el 2026-10-06, cuando ya habían caducado las últimas filas
(72 horas desde el 2026-09-25).
"""

import io
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import ArchivoSubido
from apps.formats import pdf as lector
from apps.jobs import despachador
from apps.jobs.models import ConversionJob

pytestmark = pytest.mark.django_db


def _pdf(cuantas=2) -> bytes:
    from pypdf import PdfWriter

    escritor = PdfWriter()
    for _ in range(cuantas):
        escritor.add_blank_page(width=210 / lector.MM_POR_PUNTO, height=297 / lector.MM_POR_PUNTO)
    memoria = io.BytesIO()
    escritor.write(memoria)
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


def _unir_subiendo(sesion) -> ConversionJob:
    sesion.post(
        reverse("documents:componer"),
        {
            "accion": "analizar",
            "archivos_texto": "",
            "archivos": SimpleUploadedFile("memoria.pdf", _pdf(), "application/pdf"),
        },
    )
    subida = ArchivoSubido.objects.get()
    respuesta = sesion.post(
        reverse("documents:componer"),
        {"accion": "generar", "archivos_texto": subida.token, "receta": "0:1:0,0:2:0"},
    )
    assert respuesta.status_code == 302
    assert despachador.procesar_una_vez() == 1
    trabajo = ConversionJob.objects.get()
    assert trabajo.status == "done", trabajo.reason_detail
    return trabajo


def _ficha(sesion, trabajo) -> str:
    return sesion.get(reverse("jobs:ficha", kwargs={"pk": trabajo.pk})).content.decode()


class TestDesdeLaCola:
    def test_el_enlace_esta_en_la_ficha(self, sesion):
        trabajo = _unir_subiendo(sesion)
        assert reverse("jobs:descargar", kwargs={"pk": trabajo.pk}) in _ficha(sesion, trabajo)

    def test_y_entrega_el_archivo_con_el_nombre_que_se_reconoce(self, sesion):
        trabajo = _unir_subiendo(sesion)
        respuesta = sesion.get(reverse("jobs:descargar", kwargs={"pk": trabajo.pk}))
        assert respuesta.status_code == 200
        assert "memoria_unido.pdf" in respuesta["Content-Disposition"]
        assert b"".join(respuesta.streaming_content).startswith(b"%PDF")

    def test_la_vista_y_el_modelo_viejos_ya_no_existen(self):
        """Por identificador y nunca por ruta sigue siendo la regla: lo único que baja un
        archivo es la ficha de un trabajo, con su dueño."""
        from django.urls import NoReverseMatch

        from apps.core import models

        assert not hasattr(models, "Resultado")
        with pytest.raises(NoReverseMatch):
            reverse("documents:descargar", kwargs={"pk": "00000000-0000-0000-0000-000000000000"})

    def test_si_salio_de_una_subida_no_se_ensena_la_ruta_del_servidor(self, sesion, settings):
        """No sirve para nada desde el equipo de la persona, y enseñarla invita a pegarla."""
        trabajo = _unir_subiendo(sesion)
        assert str(Path(settings.CARPETA_DE_TRABAJO)) not in _ficha(sesion, trabajo)

    def test_si_salio_de_una_ruta_si(self, sesion, tmp_path):
        """Ahí la ruta sí sirve: está en la unidad que el equipo tiene montada."""
        pegado = tmp_path / "memoria.pdf"
        pegado.write_bytes(_pdf())
        sesion.post(
            reverse("documents:componer"),
            {"accion": "generar", "archivos_texto": str(pegado), "receta": "0:1:0,0:2:0"},
        )
        despachador.procesar_una_vez()
        trabajo = ConversionJob.objects.get()
        assert str(tmp_path / "memoria_unido.pdf") in _ficha(sesion, trabajo)

    def test_la_de_otra_persona_no_se_baja(self, sesion, client):
        trabajo = _unir_subiendo(sesion)
        otra = get_user_model().objects.create_user("beto", password="x" * 20)  # nosec B106
        client.force_login(otra)
        assert client.get(reverse("jobs:descargar", kwargs={"pk": trabajo.pk})).status_code == 404

    def test_sin_entrar_tampoco(self, sesion, client):
        trabajo = _unir_subiendo(sesion)
        client.logout()
        url = reverse("jobs:descargar", kwargs={"pk": trabajo.pk})
        assert client.get(url).status_code in (302, 403)
