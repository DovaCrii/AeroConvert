"""El panel de administración.

Sin él, quien administre la instalación no ve un solo trabajo: la única lista que existe
filtra por dueño. Lo que estas pruebas vigilan es que siga siendo **un recibo y no una ficha
editable**, porque conservar el recibo es una promesa de la aplicación.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.jobs.models import ConversionJob, JobEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def jefa(client):
    usuaria = get_user_model().objects.create_superuser("jefa", "jefa@example.org", "x" * 20)  # nosec B106
    client.force_login(usuaria)
    return usuaria


@pytest.fixture
def trabajo(jefa):
    fila = ConversionJob.objects.create(
        owner=jefa,
        source_path="/mnt/entregas/orto.tif",
        source_name="orto.tif",
        source_sha256="9f3a" * 16,
        target_format_code="cog",
        engine_id="gdal-translate",
    )
    fila.registrar("Lanzado el motor.")
    return fila


class TestSeVe:
    def test_la_lista_de_trabajos(self, client, trabajo):
        respuesta = client.get(reverse("admin:jobs_conversionjob_changelist"))
        assert respuesta.status_code == 200
        assert b"orto.tif" in respuesta.content

    def test_y_la_ficha_de_uno(self, client, trabajo):
        url = reverse("admin:jobs_conversionjob_change", args=[trabajo.pk])
        assert client.get(url).status_code == 200

    def test_la_bitacora_aparte(self, client, trabajo):
        respuesta = client.get(reverse("admin:jobs_jobevent_changelist"))
        assert respuesta.status_code == 200
        assert b"Lanzado el motor" in respuesta.content

    def test_los_intentos_de_entrada(self, client, jefa):
        """Ahí es donde se desbloquea a alguien que falló ocho veces."""
        assert client.get(reverse("admin:axes_accessattempt_changelist")).status_code == 200


class TestElReciboNoSeToca:
    def test_no_se_puede_crear_un_trabajo_a_mano(self, client, jefa):
        """Un trabajo nace de la pantalla de convertir, siempre."""
        assert client.get(reverse("admin:jobs_conversionjob_add")).status_code == 403

    def test_ni_borrar_uno(self, client, trabajo):
        url = reverse("admin:jobs_conversionjob_delete", args=[trabajo.pk])
        assert client.get(url).status_code == 403

    def test_ni_editar_el_sha_del_original(self, client, trabajo):
        """Si esto se pudiera editar, el `sha256` dejaría de significar nada."""
        url = reverse("admin:jobs_conversionjob_change", args=[trabajo.pk])
        client.post(url, {"source_sha256": "0000", "source_name": "otro.tif"})
        trabajo.refresh_from_db()
        assert trabajo.source_sha256 == "9f3a" * 16
        assert trabajo.source_name == "orto.tif"

    def test_la_bitacora_no_ofrece_borrar(self):
        """`JobEvent.objects` levanta `NotImplementedError` en `delete()`: una casilla de
        borrado aquí daría un 500 opaco."""
        from apps.jobs.admin import BitacoraEnLinea

        assert BitacoraEnLinea.can_delete is False

    def test_ni_borrar_un_evento_suelto(self, client, trabajo):
        evento = JobEvent.objects.filter(job=trabajo).first()
        url = reverse("admin:jobs_jobevent_delete", args=[evento.pk])
        assert client.get(url).status_code == 403


class TestLasAcciones:
    def test_cancelar_solo_lo_pide(self, client, trabajo):
        """No mata nada: el runner mira el campo en cada latido, igual que con el botón."""
        client.post(
            reverse("admin:jobs_conversionjob_changelist"),
            {"action": "pedir_cancelacion", "_selected_action": [str(trabajo.pk)]},
        )
        trabajo.refresh_from_db()
        assert trabajo.cancel_requested_at is not None
        assert trabajo.status != "cancelado"


class TestElRendimiento:
    def test_la_lista_no_hace_una_consulta_por_fila(
        self, client, jefa, django_capture_on_commit_callbacks
    ):
        """Sin `list_select_related`, pintar el dueño cuesta una consulta por trabajo.

        Se comparan **dos tamaños** en vez de fijar un número: el número exacto depende de
        cuántas consultas hace el admin por su cuenta, y clavarlo convierte la prueba en algo
        que se rompe cada vez que Django cambia. Lo que importa es que no crezca.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        url = reverse("admin:jobs_conversionjob_changelist")

        def crear(cuantos, desde):
            for numero in range(desde, desde + cuantos):
                ConversionJob.objects.create(
                    owner=jefa,
                    source_path=f"/mnt/entregas/orto{numero}.tif",
                    source_name=f"orto{numero}.tif",
                    target_format_code="cog",
                )

        crear(3, 0)
        with CaptureQueriesContext(connection) as pocas:
            client.get(url)

        crear(12, 100)
        with CaptureQueriesContext(connection) as muchas:
            client.get(url)

        assert len(muchas) == len(pocas), (
            f"con 15 trabajos hace {len(muchas)} consultas y con 3 hace {len(pocas)}: "
            "falta list_select_related"
        )


class TestLaIdentidad:
    def test_el_panel_dice_donde_estas(self, client, jefa):
        respuesta = client.get(reverse("admin:index"))
        assert b"AeroConvert" in respuesta.content
