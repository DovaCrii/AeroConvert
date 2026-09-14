"""Bajarse un resultado.

Hace falta **aunque haya carpeta compartida**: el navegador está en el equipo de la persona y
el recurso está montado en la VM, así que la ruta que se enseña es la del servidor
(`/mnt/entregas/...`) y no la suya (`Z:\\...`). Como texto no sirve para pegarla en ninguna
parte.

Y se entrega por identificador, nunca por ruta. Una vista que aceptara `?ruta=<absoluta>`
convertiría una herramienta que **escribe** en **lectura de cualquier cosa del recurso
compartido**, por GET y sin testigo.
"""

import io

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import ArchivoSubido, Resultado
from apps.formats import pdf as lector

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


def _unir_subiendo(sesion):
    sesion.post(
        reverse("documents:componer"),
        {
            "accion": "analizar",
            "archivos_texto": "",
            "archivos": SimpleUploadedFile("memoria.pdf", _pdf(), "application/pdf"),
        },
    )
    subida = ArchivoSubido.objects.get()
    return sesion.post(
        reverse("documents:componer"),
        {"accion": "generar", "archivos_texto": subida.token, "receta": "0:1:0,0:2:0"},
    )


class TestElEnlace:
    def test_aparece_despues_de_componer(self, sesion):
        cuerpo = _unir_subiendo(sesion).content.decode()
        fila = Resultado.objects.get()
        assert reverse("documents:descargar", kwargs={"pk": fila.pk}) in cuerpo

    def test_y_entrega_el_archivo(self, sesion):
        _unir_subiendo(sesion)
        fila = Resultado.objects.get()
        respuesta = sesion.get(reverse("documents:descargar", kwargs={"pk": fila.pk}))
        assert respuesta.status_code == 200
        assert b"".join(respuesta.streaming_content).startswith(b"%PDF")

    def test_con_el_nombre_que_la_persona_reconoce(self, sesion):
        _unir_subiendo(sesion)
        fila = Resultado.objects.get()
        respuesta = sesion.get(reverse("documents:descargar", kwargs={"pk": fila.pk}))
        assert "memoria_unido.pdf" in respuesta["Content-Disposition"]

    def test_si_salio_de_una_subida_no_se_ensena_la_ruta_del_servidor(self, sesion, settings):
        """No sirve para nada desde el equipo de la persona, y enseñarla invita a pegarla."""
        cuerpo = _unir_subiendo(sesion).content.decode()
        assert str(settings.CARPETA_DE_TRABAJO) not in cuerpo

    def test_si_salio_de_una_ruta_si(self, sesion, tmp_path):
        """Ahí la ruta sí sirve: está en la unidad que el equipo tiene montada."""
        pegado = tmp_path / "memoria.pdf"
        pegado.write_bytes(_pdf())
        cuerpo = sesion.post(
            reverse("documents:componer"),
            {"accion": "generar", "archivos_texto": str(pegado), "receta": "0:1:0,0:2:0"},
        ).content.decode()
        assert "memoria_unido.pdf" in cuerpo


class TestEsDeSuDueno:
    def test_la_de_otra_persona_no_se_baja(self, sesion, client):
        _unir_subiendo(sesion)
        fila = Resultado.objects.get()

        otra = get_user_model().objects.create_user("beto", password="x" * 20)  # nosec B106
        client.force_login(otra)
        url = reverse("documents:descargar", kwargs={"pk": fila.pk})
        assert client.get(url).status_code == 404

    def test_sin_entrar_tampoco(self, sesion, client):
        _unir_subiendo(sesion)
        fila = Resultado.objects.get()
        client.logout()
        url = reverse("documents:descargar", kwargs={"pk": fila.pk})
        assert client.get(url).status_code in (302, 403)


class TestNoSeAceptaUnaRuta:
    def test_la_url_solo_admite_un_identificador(self):
        """**La razón entera de que exista una fila.** Con `?ruta=` bastaría un enlace en un
        correo para sacar un archivo por el navegador de otra persona."""
        from django.urls import NoReverseMatch

        with pytest.raises(NoReverseMatch):
            reverse("documents:descargar", kwargs={"pk": "/mnt/entregas/secreto.pdf"})


class TestSiElArchivoSeFue:
    def test_lo_dice_en_vez_de_reventar(self, sesion):
        _unir_subiendo(sesion)
        fila = Resultado.objects.get()
        from pathlib import Path

        Path(fila.ruta).unlink()

        cuerpo = sesion.get(
            reverse("documents:descargar", kwargs={"pk": fila.pk}), follow=True
        ).content.decode()
        assert "ya no está donde se dejó" in cuerpo


class TestElBarrido:
    def test_se_lleva_el_enlace_caducado(self, sesion, settings):
        from datetime import timedelta

        from django.utils import timezone

        from apps.jobs import retencion

        _unir_subiendo(sesion)
        fila = Resultado.objects.get()
        Resultado.objects.filter(pk=fila.pk).update(expires_at=timezone.now() - timedelta(hours=1))

        resumen = retencion.barrer()
        assert resumen.resultados_caducados == 1
        assert Resultado.objects.count() == 0

    def test_pero_no_el_entregable_de_la_carpeta_compartida(self, sesion, tmp_path):
        """**La fila caduca; el archivo no**, salvo que viva en `MEDIA_ROOT`. En el recurso
        compartido el archivo es el entregable de la persona — es el motivo por el que existe
        la política permanente."""
        from datetime import timedelta
        from pathlib import Path

        from django.utils import timezone

        from apps.jobs import retencion

        pegado = tmp_path / "memoria.pdf"
        pegado.write_bytes(_pdf())
        sesion.post(
            reverse("documents:componer"),
            {"accion": "generar", "archivos_texto": str(pegado), "receta": "0:1:0,0:2:0"},
        )
        fila = Resultado.objects.get()
        Resultado.objects.filter(pk=fila.pk).update(expires_at=timezone.now() - timedelta(hours=1))

        retencion.barrer()
        assert Resultado.objects.count() == 0
        assert Path(fila.ruta).exists(), "se llevó el entregable de la carpeta compartida"
