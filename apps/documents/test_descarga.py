"""Bajarse un resultado.

Hace falta **aunque haya carpeta compartida**: el navegador está en el equipo de la persona y
el recurso está montado en la VM, así que la ruta que se enseña es la del servidor
(`/mnt/entregas/...`) y no la suya (`Z:\\...`). Como texto no sirve para pegarla en ninguna
parte.

Y se entrega por identificador, nunca por ruta. Una vista que aceptara `?ruta=<absoluta>`
convertiría una herramienta que **escribe** en **lectura de cualquier cosa del recurso
compartido**, por GET y sin testigo.

## Dos caminos, mientras dure la transición

Desde la fase 9 las herramientas pasan por la cola y se descargan por la ficha del trabajo
(`jobs:descargar`), que ya comprobaba el dueño. La vista vieja —`documents:descargar`, con
sus filas de `Resultado`— sigue viva **solo para las filas que quedan**, hasta que caduquen:
quitarla antes rompería el enlace de alguien que compuso algo ayer.
"""

import io
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core import subidas as subidas_mod
from apps.core.models import ArchivoSubido, Resultado
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

    def test_ya_no_crea_filas_de_resultado(self, sesion):
        """La tabla vieja se vacía sola a medida que caducan las que quedan."""
        _unir_subiendo(sesion)
        assert not Resultado.objects.exists()

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


# --- La vista vieja, mientras le queden filas ---------------------------------


@pytest.fixture
def fila_vieja(sesion, tmp_path):
    """Una fila como las que dejaban Unir e Imágenes antes de pasar por la cola."""
    ruta = tmp_path / "trabajo" / "memoria_unido.pdf"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(_pdf())
    ana = get_user_model().objects.get(username="ana")
    return subidas_mod.anotar_resultado(ruta, usuario=ana, herramienta="unir")


class TestLasFilasDeAntes:
    def test_se_siguen_bajando(self, sesion, fila_vieja):
        respuesta = sesion.get(reverse("documents:descargar", kwargs={"pk": fila_vieja.pk}))
        assert respuesta.status_code == 200
        assert "memoria_unido.pdf" in respuesta["Content-Disposition"]

    def test_la_de_otra_persona_no_se_baja(self, sesion, fila_vieja, client):
        otra = get_user_model().objects.create_user("beto", password="x" * 20)  # nosec B106
        client.force_login(otra)
        url = reverse("documents:descargar", kwargs={"pk": fila_vieja.pk})
        assert client.get(url).status_code == 404

    def test_la_url_solo_admite_un_identificador(self):
        """**La razón entera de que exista una fila.** Con `?ruta=` bastaría un enlace en un
        correo para sacar un archivo por el navegador de otra persona."""
        from django.urls import NoReverseMatch

        with pytest.raises(NoReverseMatch):
            reverse("documents:descargar", kwargs={"pk": "/mnt/entregas/secreto.pdf"})

    def test_si_el_archivo_se_fue_lo_dice_en_vez_de_reventar(self, sesion, fila_vieja):
        Path(fila_vieja.ruta).unlink()
        cuerpo = sesion.get(
            reverse("documents:descargar", kwargs={"pk": fila_vieja.pk}), follow=True
        ).content.decode()
        assert "ya no está donde se dejó" in cuerpo


class TestElBarrido:
    def test_se_lleva_el_enlace_caducado(self, sesion, fila_vieja):
        from datetime import timedelta

        from django.utils import timezone

        from apps.jobs import retencion

        Resultado.objects.filter(pk=fila_vieja.pk).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )
        resumen = retencion.barrer()
        assert resumen.resultados_caducados == 1
        assert Resultado.objects.count() == 0

    def test_pero_no_el_entregable_de_la_carpeta_compartida(self, sesion, tmp_path):
        """**La fila caduca; el archivo no**, salvo que viva en `MEDIA_ROOT`. En el recurso
        compartido el archivo es el entregable de la persona — es el motivo por el que existe
        la política permanente."""
        from datetime import timedelta

        from django.utils import timezone

        from apps.jobs import retencion

        entregable = tmp_path / "memoria_unido.pdf"
        entregable.write_bytes(_pdf())
        ana = get_user_model().objects.get(username="ana")
        fila = subidas_mod.anotar_resultado(entregable, usuario=ana, herramienta="unir")
        Resultado.objects.filter(pk=fila.pk).update(expires_at=timezone.now() - timedelta(hours=1))

        retencion.barrer()
        assert Resultado.objects.count() == 0
        assert entregable.exists(), "se llevó el entregable de la carpeta compartida"
